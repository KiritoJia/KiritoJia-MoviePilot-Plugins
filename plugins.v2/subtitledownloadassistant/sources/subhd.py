"""SubHD 账号会话、标题搜索与字幕下载来源。"""

from __future__ import annotations

import asyncio
import html
import re
import time
from html.parser import HTMLParser
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse

from app.core.cache import AsyncMemoryBackend
from app.core.config import settings
from app.utils.http import AsyncRequestUtils

from ..application.ports import (
    CandidateHandle,
    DownloadedAsset,
    ManualSourceSearchResult,
    SourceSearchResult,
)
from ..domain.enums import PackageScope, SourceHealth, SubtitleSource, TranslationType
from ..domain.language import candidate_has_supported_chinese, candidate_is_allowed
from ..domain.models import MediaContext, SourceStatus, SubtitleCandidate, elapsed_ms, utc_now
from .common import (
    SourceLimitedError,
    SourceRequestError,
    _proxy_kwargs,
    cache_key,
    decode_candidate_pool,
    download_file,
    encode_candidate_pool,
    request_res_with_proxy_fallback,
    safe_file_name,
)
from .limiter import SlidingWindowLimiter

SEARCH_CACHE_TTL_SECONDS = 30 * 60
SEARCH_CACHE_REGION = "subtitledownloadassistant_source_subhd"
DEFAULT_BASE_URL = "https://subhd.tv"
_USER_AGENT = "MoviePilot SubtitleDownloadAssistant/1.1.10"
_DETAIL_PATH = re.compile(r"^/a/([A-Za-z0-9_-]+)$")
_MEDIA_PATH = re.compile(r"^/d/([A-Za-z0-9_-]+)$")
_FORMAT_PATTERN = re.compile(r"\b(ASS|SSA|SRT|SUP|VTT|SUB)\b", re.IGNORECASE)
_EPISODE_PATTERN = re.compile(r"\bS(\d{1,3})E(\d{1,4})\b", re.IGNORECASE)
_CONTEXT_MARKER_PATTERN = re.compile(
    r"简体|简中|简英|繁体|繁體|繁中|英语|英語|英文|English|\bENG\b|双语|雙語|中英|"
    r"\b(?:ASS|SSA|SRT|SUP|VTT|SUB)\b",
    re.IGNORECASE,
)
_BLOCK_TAGS = frozenset({"article", "div", "li", "section", "tr"})


class _SubHDSearchParser(HTMLParser):
    """从 SubHD 服务端渲染页面提取字幕与媒体详情链接。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, Any]] = []
        self._text: list[str] = []
        self._anchor: dict[str, Any] | None = None
        self._blocks: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag in _BLOCK_TAGS:
            self._blocks.append({"tag": tag, "start": len(self._text), "links": []})
        href = values.get("href", "")
        if tag == "a" and (_DETAIL_PATH.match(href) or _MEDIA_PATH.match(href)):
            self._anchor = {
                "href": href,
                "text": [],
                "start": len(self._text),
                "end": len(self._text),
                "containers": [],
            }
            for block in self._blocks:
                block["links"].append(self._anchor)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        normalized = " ".join(data.split())
        if normalized:
            self._text.append(normalized)
        if self._anchor is not None:
            self._anchor["text"].append(data)
            self._anchor["end"] = len(self._text)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._anchor is not None:
            self._anchor["text"] = " ".join(" ".join(self._anchor["text"]).split())
            if self._anchor["text"]:
                self.links.append(self._anchor)
            self._anchor = None
        if tag in _BLOCK_TAGS:
            index = next(
                (position for position in range(len(self._blocks) - 1, -1, -1) if self._blocks[position]["tag"] == tag),
                None,
            )
            if index is not None:
                block = self._blocks.pop(index)
                for link in block["links"]:
                    link["containers"].append((int(block["start"]), len(self._text)))

    def context(self, link: dict[str, Any], radius: int = 16) -> str:
        """返回链接附近的可见文字，用于识别语言和字幕格式标签。"""

        containers = sorted(
            (tuple(item) for item in link.get("containers") or []),
            key=lambda item: item[1] - item[0],
        )
        for start, end in containers:
            text = " ".join(self._text[start:end])
            if _CONTEXT_MARKER_PATTERN.search(text):
                return text

        subtitles = self.subtitle_links
        index = next((position for position, item in enumerate(subtitles) if item is link), 0)
        previous_end = int(subtitles[index - 1].get("end") or 0) if index > 0 else 0
        start = max(previous_end, int(link.get("start") or 0) - radius)
        end = min(len(self._text), int(link.get("end") or 0) + 2)
        return " ".join(self._text[start:end])

    @property
    def subtitle_links(self) -> list[dict[str, Any]]:
        return [item for item in self.links if _DETAIL_PATH.match(str(item.get("href") or ""))]

    @property
    def media_links(self) -> list[dict[str, Any]]:
        return [item for item in self.links if _MEDIA_PATH.match(str(item.get("href") or ""))]


class _SubHDDetailParser(HTMLParser):
    """提取详情页下载按钮、正文与后备下载链接。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sid = ""
        self.text: list[str] = []
        self.download_links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        classes = set(values.get("class", "").split())
        if tag == "button" and "subtitle-prepare-download" in classes and values.get("data-sid"):
            self.sid = values["data-sid"].strip()
        if tag == "a" and values.get("href") and re.search(
            r"(?i)(?:/download|/file|\.zip(?:\?|$)|\.rar(?:\?|$)|\.7z(?:\?|$)|\.srt(?:\?|$)|\.ass(?:\?|$))",
            values["href"],
        ):
            self.download_links.append(values["href"])

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.text.append(data.strip())


class SubHDSource:
    """使用 SubHD 邮箱账号登录后按媒体文件名搜索并下载字幕。"""

    source = SubtitleSource.SUBHD

    def __init__(
        self,
        enabled: bool,
        credentials: dict[str, str],
        allowed_formats: set[str],
        base_url: str = DEFAULT_BASE_URL,
        cache: AsyncMemoryBackend | None = None,
        limiter: SlidingWindowLimiter | None = None,
    ) -> None:
        self.enabled = enabled
        self.base_url = base_url.rstrip("/")
        self._credentials = dict(credentials)
        self._allowed_formats = {item.upper().lstrip(".") for item in allowed_formats}
        self._cache = cache or AsyncMemoryBackend(
            cache_type="ttl",
            maxsize=256,
            ttl=SEARCH_CACHE_TTL_SECONDS,
        )
        self._limiter = limiter or SlidingWindowLimiter(limit=1, window_seconds=1)
        self._login_lock = asyncio.Lock()
        self._cookies: dict[str, str] = {}
        self._authenticated = False
        self._active_proxies: dict[str, str] = settings.PROXY or {}
        self._last_details: dict[str, Any] = {
            "attribution": "https://subhd.tv",
            "base_url": self.base_url,
        }
        self._credential_generation = 0

    @property
    def configured(self) -> bool:
        """判断 SubHD 邮箱和密码是否完整。"""

        return all(self._credentials.get(key, "").strip() for key in ("email", "password"))

    async def replace_credentials(self, credentials: dict[str, str]) -> None:
        """替换长期凭据并清除当前 Cookie 会话与候选缓存。"""

        self._credentials = dict(credentials)
        self._cookies.clear()
        self._authenticated = False
        self._credential_generation += 1
        await self.clear_cache()

    def _headers(self, *, referer: str | None = None, json_request: bool = False) -> dict[str, str]:
        headers = {
            "Accept": "application/json" if json_request else "text/html,application/xhtml+xml,*/*;q=0.8",
            "User-Agent": _USER_AGENT,
        }
        if referer:
            headers["Referer"] = referer
        if json_request:
            headers["Content-Type"] = "application/json"
            headers["X-Requested-With"] = "XMLHttpRequest"
        if self._cookies:
            headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in sorted(self._cookies.items()))
        return headers

    @staticmethod
    def _parse_set_cookie(value: Any) -> dict[str, str]:
        cookie = SimpleCookie()
        try:
            cookie.load(str(value))
        except (CookieError, TypeError, ValueError):
            return {}
        return {key: morsel.value for key, morsel in cookie.items()}

    def _capture_cookies(self, response: Any) -> None:
        jar = getattr(response, "cookies", None)
        if jar is not None:
            try:
                self._cookies.update({str(key): str(value) for key, value in jar.items()})
            except (AttributeError, TypeError, ValueError):
                pass
        headers = getattr(response, "headers", None)
        if headers is None:
            return
        try:
            values = headers.get_list("set-cookie")
        except AttributeError:
            value = headers.get("set-cookie")
            values = [value] if value else []
        for value in values:
            self._cookies.update(self._parse_set_cookie(value))

    async def _request(self, method: str, url: str, **kwargs: Any) -> tuple[Any, dict[str, Any]]:
        await self._limiter.acquire(wait=True)
        response, details, active_proxies = await request_res_with_proxy_fallback(
            method,
            url,
            proxies=getattr(settings, "PROXY", None),
            **kwargs,
        )
        self._last_details.update(details)
        self._active_proxies = active_proxies
        if response is None:
            attempts = "、".join(details.get("transport_attempts") or ["直连"])
            raise SourceRequestError(f"SubHD 请求失败（{attempts}均无响应）")
        self._capture_cookies(response)
        return response, details

    @staticmethod
    def _safe_message(value: Any, fallback: str) -> str:
        text = " ".join(str(value or "").split())
        return text[:160] if text else fallback

    async def _login(self, force: bool = False) -> None:
        if not self.configured:
            raise SourceRequestError("SubHD 凭据不完整")
        async with self._login_lock:
            if self._authenticated and not force:
                return
            if force:
                self._cookies.clear()
                self._authenticated = False
            response, _ = await self._request(
                "post_res",
                f"{self.base_url}/api/set/login",
                headers=self._headers(referer=f"{self.base_url}/set/login", json_request=True),
                json={"email": self._credentials["email"], "pwd": self._credentials["password"]},
            )
            try:
                if response.status_code == 429:
                    raise SourceLimitedError("SubHD 登录请求暂时受限")
                if response.status_code in {401, 403}:
                    raise SourceRequestError(f"SubHD 邮箱或密码无效（HTTP {response.status_code}）")
                if response.status_code >= 400:
                    raise SourceRequestError(f"SubHD 登录返回 HTTP {response.status_code}")
                try:
                    payload = response.json()
                except (TypeError, ValueError) as exc:
                    raise SourceRequestError("SubHD 登录响应无法解析") from exc
                if not isinstance(payload, dict) or not payload.get("success"):
                    message = payload.get("msg") if isinstance(payload, dict) else None
                    raise SourceRequestError(self._safe_message(message, "SubHD 邮箱或密码无效"))
                if not self._cookies:
                    raise SourceRequestError("SubHD 登录成功但未返回会话 Cookie")
                self._authenticated = True
                self._last_details.update(
                    {
                        "session_active": True,
                        "last_login_at": utc_now().isoformat(),
                    }
                )
            finally:
                await response.aclose()

    @staticmethod
    def _queries(context: MediaContext, custom_query: str | None = None) -> list[str]:
        custom = (custom_query or "").strip()
        if custom:
            return [custom]
        target = Path(context.target_file_name)
        if target.suffix.casefold() == ".strm":
            return [target.stem] if target.stem else []
        values = [
            target.stem,
            context.title,
            context.english_title or "",
            context.original_title or "",
        ]
        result: list[str] = []
        for value in values:
            normalized = " ".join(str(value or "").split())
            if normalized and normalized.casefold() not in {item.casefold() for item in result}:
                result.append(normalized)
        return result

    def _format(self, text: str) -> str:
        formats = [item.upper() for item in _FORMAT_PATTERN.findall(text)]
        return next((item for item in formats if item in self._allowed_formats), formats[0] if formats else "UNKNOWN")

    @staticmethod
    def _language(text: str) -> tuple[str, dict[str, bool]]:
        simplified = bool(re.search(r"简体|简中|简英", text, re.IGNORECASE))
        traditional = bool(re.search(r"繁体|繁體|繁中", text, re.IGNORECASE))
        english = bool(re.search(r"英语|英語|英文|English|\bENG\b", text, re.IGNORECASE))
        bilingual = bool(re.search(r"双语|雙語|中英|简英", text, re.IGNORECASE))
        if bilingual and not english:
            english = True
        if bilingual and not simplified and not traditional:
            simplified = True
        labels = []
        if simplified:
            labels.append("简体中文")
        if traditional:
            labels.append("繁体中文")
        if english:
            labels.append("英语")
        return "、".join(labels) or "未知", {
            "zh-cn": simplified,
            "zh-tw": traditional,
            "eng": english,
        }

    def _parse_cards(
        self,
        body: str,
        context: MediaContext,
        query: str,
    ) -> tuple[list[CandidateHandle], int, list[str]]:
        parser = _SubHDSearchParser()
        parser.feed(body)
        handles: list[CandidateHandle] = []
        seen: set[str] = set()
        for selected in parser.subtitle_links:
            match = _DETAIL_PATH.match(str(selected.get("href") or ""))
            if not match or match.group(1) in seen:
                continue
            sid = match.group(1)
            seen.add(sid)
            title = str(selected.get("text") or "").strip() or f"SubHD 字幕 {sid}"
            description = parser.context(selected) or title
            language, language_flags = self._language(f"{title} {description}")
            extension = self._format(f"{title} {description}")
            episode_match = _EPISODE_PATTERN.search(title)
            season = int(episode_match.group(1)) if episode_match else context.season
            episode = int(episode_match.group(2)) if episode_match else context.episode
            candidate = SubtitleCandidate(
                stable_key=f"subhd:{sid}",
                source=self.source,
                name=title,
                format=extension,
                language=language,
                translation_type=TranslationType.HUMAN,
                package_scope=PackageScope.EPISODE if episode is not None else PackageScope.UNKNOWN,
                year=context.year,
                season=season,
                episode=episode,
                trusted=bool(re.search(r"官方字幕|原创翻译|原創翻譯", description)),
                metadata={
                    "actual_query": query,
                    "description": description,
                    "language_flags": language_flags,
                    "release": title,
                },
            )
            handles.append(
                CandidateHandle(
                    candidate=candidate,
                    opaque={"sid": sid, "page_url": f"{self.base_url}/a/{sid}"},
                )
            )
        media_paths = list(dict.fromkeys(str(item["href"]) for item in parser.media_links))
        return handles, len(seen), media_paths

    async def _candidate_pool(
        self,
        context: MediaContext,
        query: str,
    ) -> tuple[list[CandidateHandle], int, dict[str, int], dict[str, Any]]:
        generation = self._credential_generation
        key = cache_key(self.source.value, {"base_url": self.base_url, "query": query})
        decoded = decode_candidate_pool(await self._cache.get(key, region=SEARCH_CACHE_REGION))
        if decoded is not None:
            handles, cached = decoded
            details = {
                "query": query,
                "query_type": "filename",
                "cache_hit": True,
                "cache_stored_at": cached.get("cache_stored_at"),
                "session_active": self._authenticated,
            }
            return handles, int(cached["raw_count"]), dict(cached["rejection_summary"]), details

        response, transport_details = await self._request(
            "get_res",
            f"{self.base_url}/search/{quote(query, safe='')}",
            headers=self._headers(referer=self.base_url),
        )
        try:
            if response.status_code == 429:
                raise SourceLimitedError("SubHD 搜索请求暂时受限")
            if response.status_code >= 400:
                raise SourceRequestError(f"SubHD 搜索返回 HTTP {response.status_code}")
            body = str(getattr(response, "text", "") or "")
            if not body:
                raise SourceRequestError("SubHD 搜索返回空页面")
        finally:
            await response.aclose()
        handles, raw_count, media_paths = self._parse_cards(body, context, query)
        detail_page_count = 0
        if not handles:
            for media_path in media_paths[:4]:
                detail_response, _ = await self._request(
                    "get_res",
                    urljoin(self.base_url, media_path),
                    headers=self._headers(referer=f"{self.base_url}/search/{quote(query, safe='')}"),
                )
                try:
                    if detail_response.status_code == 429:
                        raise SourceLimitedError("SubHD 搜索请求暂时受限")
                    if detail_response.status_code >= 400:
                        continue
                    detail_body = str(getattr(detail_response, "text", "") or "")
                finally:
                    await detail_response.aclose()
                detail_page_count += 1
                detail_handles, detail_raw_count, _ = self._parse_cards(detail_body, context, query)
                raw_count += detail_raw_count
                existing = {item.candidate.stable_key for item in handles}
                handles.extend(item for item in detail_handles if item.candidate.stable_key not in existing)
                if handles:
                    break
        rejected: dict[str, int] = {}
        details = {
            **transport_details,
            "query": query,
            "query_type": "filename",
            "cache_hit": False,
            "session_active": self._authenticated,
            "detail_page_count": detail_page_count,
        }
        if generation == self._credential_generation:
            await self._cache.set(
                key,
                encode_candidate_pool(handles, raw_count, rejected),
                region=SEARCH_CACHE_REGION,
            )
        self._last_details.update({**details, "last_search_at": utc_now().isoformat()})
        return handles, raw_count, rejected, details

    @staticmethod
    def _filter_automatic(
        handles: list[CandidateHandle],
        allow_machine: bool,
    ) -> tuple[list[CandidateHandle], dict[str, int]]:
        result: list[CandidateHandle] = []
        rejected: dict[str, int] = {}
        for handle in handles:
            if not candidate_has_supported_chinese(handle.candidate):
                rejected["language"] = rejected.get("language", 0) + 1
                continue
            if not candidate_is_allowed(handle.candidate, allow_machine):
                rejected["machine_translation"] = rejected.get("machine_translation", 0) + 1
                continue
            result.append(handle)
        return result, rejected

    async def search(self, context: MediaContext, allow_machine: bool) -> SourceSearchResult:
        """登录后搜索；STRM 只使用文件名，真实媒体允许标题回退。"""

        started = time.monotonic()
        if not self.enabled:
            return SourceSearchResult(source=self.source)
        if not self.configured:
            return SourceSearchResult(source=self.source, error_summary="SubHD 凭据不完整")
        try:
            await self._login()
            total_raw = 0
            for query in self._queries(context):
                pool, raw_count, rejected, details = await self._candidate_pool(context, query)
                total_raw += raw_count
                candidates, automatic_rejected = self._filter_automatic(pool, allow_machine)
                for key, count in automatic_rejected.items():
                    rejected[key] = rejected.get(key, 0) + count
                if candidates:
                    return SourceSearchResult(
                        source=self.source,
                        candidates=candidates,
                        duration_ms=int((time.monotonic() - started) * 1000),
                        raw_count=total_raw,
                        admitted_count=len(candidates),
                        rejection_summary=rejected,
                        details=details,
                    )
            return SourceSearchResult(
                source=self.source,
                duration_ms=int((time.monotonic() - started) * 1000),
                raw_count=total_raw,
                details=dict(self._last_details),
            )
        except SourceLimitedError as exc:
            return SourceSearchResult(
                source=self.source,
                duration_ms=int((time.monotonic() - started) * 1000),
                error_summary=str(exc),
                limited=True,
            )
        except SourceRequestError as exc:
            return SourceSearchResult(
                source=self.source,
                duration_ms=int((time.monotonic() - started) * 1000),
                error_summary=str(exc),
            )
        except Exception:  # noqa: BLE001 - 外部字幕源异常必须收敛为安全结果
            return SourceSearchResult(
                source=self.source,
                duration_ms=int((time.monotonic() - started) * 1000),
                error_summary="SubHD 搜索失败",
            )

    async def manual_search(
        self,
        context: MediaContext,
        custom_query: str | None = None,
    ) -> ManualSourceSearchResult:
        """登录后执行默认文件名或自定义关键词搜索。"""

        started = time.monotonic()
        defaults = self._queries(context)
        if not self.enabled:
            return ManualSourceSearchResult(source=self.source, status="disabled", default_queries=defaults)
        if not self.configured:
            return ManualSourceSearchResult(source=self.source, status="unconfigured", default_queries=defaults)
        executed: list[str] = []
        total_raw = 0
        try:
            await self._login()
            for query in self._queries(context, custom_query):
                executed.append(query)
                candidates, raw_count, _rejected, details = await self._candidate_pool(context, query)
                total_raw += raw_count
                if candidates:
                    return ManualSourceSearchResult(
                        source=self.source,
                        status="success",
                        candidates=candidates,
                        default_queries=defaults,
                        executed_queries=executed,
                        matched_query=query,
                        duration_ms=int((time.monotonic() - started) * 1000),
                        raw_count=total_raw,
                        admitted_count=len(candidates),
                        details=details,
                    )
            return ManualSourceSearchResult(
                source=self.source,
                status="success",
                default_queries=defaults,
                executed_queries=executed,
                duration_ms=int((time.monotonic() - started) * 1000),
                raw_count=total_raw,
                details=dict(self._last_details),
            )
        except SourceLimitedError as exc:
            return ManualSourceSearchResult(
                source=self.source,
                status="limited",
                default_queries=defaults,
                executed_queries=executed,
                duration_ms=int((time.monotonic() - started) * 1000),
                error_summary=str(exc),
            )
        except SourceRequestError as exc:
            return ManualSourceSearchResult(
                source=self.source,
                status="error",
                default_queries=defaults,
                executed_queries=executed,
                duration_ms=int((time.monotonic() - started) * 1000),
                error_summary=str(exc),
            )
        except Exception:  # noqa: BLE001 - 外部字幕源异常必须收敛为安全结果
            return ManualSourceSearchResult(
                source=self.source,
                status="error",
                default_queries=defaults,
                executed_queries=executed,
                duration_ms=int((time.monotonic() - started) * 1000),
                error_summary="SubHD 搜索失败",
            )

    async def _post_json(self, path: str, payload: dict[str, Any], referer: str) -> dict[str, Any]:
        response, _ = await self._request(
            "post_res",
            urljoin(self.base_url, path),
            headers=self._headers(referer=referer, json_request=True),
            json=payload,
        )
        try:
            if response.status_code == 429:
                raise SourceLimitedError("SubHD 下载请求暂时受限")
            if response.status_code >= 400:
                raise SourceRequestError(f"SubHD 下载接口返回 HTTP {response.status_code}")
            try:
                data = response.json()
            except (TypeError, ValueError) as exc:
                raise SourceRequestError("SubHD 下载接口响应无法解析") from exc
            if not isinstance(data, dict):
                raise SourceRequestError("SubHD 下载接口响应结构无效")
            return data
        finally:
            await response.aclose()

    @classmethod
    def _download_url(cls, value: Any) -> str:
        if isinstance(value, str):
            text = html.unescape(value.strip())
            if text.startswith(("https://", "http://", "/")):
                return text
            return ""
        if isinstance(value, list):
            return next((found for item in value if (found := cls._download_url(item))), "")
        if not isinstance(value, dict):
            return ""
        for key in (
            "url",
            "download_url",
            "downloadUrl",
            "down_url",
            "downUrl",
            "file_url",
            "fileUrl",
            "link",
            "href",
            "path",
            "location",
            "redirect",
            "data",
            "result",
            "file",
            "download",
        ):
            found = cls._download_url(value.get(key))
            if found:
                return found
        return ""

    def _resolve_url(self, value: str) -> str:
        resolved = urljoin(self.base_url, value)
        parsed = urlparse(resolved)
        base = urlparse(self.base_url)
        if parsed.hostname in {"subhd.tv", "www.subhd.tv"} and (parsed.scheme, parsed.netloc) != (
            base.scheme,
            base.netloc,
        ):
            suffix = parsed.path or "/"
            if parsed.query:
                suffix = f"{suffix}?{parsed.query}"
            return urljoin(f"{self.base_url}/", suffix.lstrip("/"))
        return resolved

    async def _page(self, url: str, referer: str) -> tuple[str, _SubHDDetailParser]:
        response, _ = await self._request(
            "get_res",
            url,
            headers=self._headers(referer=referer),
        )
        try:
            if response.status_code >= 400:
                raise SourceRequestError(f"SubHD 页面返回 HTTP {response.status_code}")
            body = str(getattr(response, "text", "") or "")
        finally:
            await response.aclose()
        parser = _SubHDDetailParser()
        parser.feed(body)
        return body, parser

    async def download(self, handle: CandidateHandle, directory: Path) -> DownloadedAsset:
        """使用登录 Cookie 完成下载准备、验证和最终文件下载。"""

        await self._login()
        page_url = str(handle.opaque.get("page_url") or "")
        sid = str(handle.opaque.get("sid") or "")
        if not page_url or not sid:
            raise SourceRequestError("SubHD 候选缺少详情页或字幕 ID")
        _body, page = await self._page(page_url, self.base_url)
        sid = page.sid or sid
        prepared = await self._post_json("/api/sub/prepare-download", {"sid": sid}, page_url)
        down_path = self._download_url(prepared)
        if not prepared.get("success") or "/down/" not in down_path:
            raise SourceRequestError(self._safe_message(prepared.get("msg"), "SubHD 下载准备失败"))
        down_url = self._resolve_url(down_path)
        _down_body, down_page = await self._page(down_url, page_url)
        down_sid = Path(urlparse(down_url).path).name or sid
        authorized = await self._post_json("/api/sub/down", {"sid": down_sid, "cap": ""}, down_url)
        if authorized.get("pass") is False:
            raise SourceRequestError("SubHD 要求下载验证码；当前账号会话未通过验证，请稍后在 SubHD 网站完成验证后重试")
        if not authorized.get("success"):
            raise SourceRequestError(self._safe_message(authorized.get("msg"), "SubHD 下载授权失败"))
        file_url = self._download_url(authorized)
        if not file_url and down_page.download_links:
            file_url = down_page.download_links[0]
        if not file_url:
            raise SourceRequestError("SubHD 下载授权未返回文件地址")
        resolved_url = self._resolve_url(file_url)
        fallback_name = safe_file_name(
            str(authorized.get("filename") or authorized.get("file_name") or ""),
            f"subhd-{down_sid}.zip",
        )
        request = AsyncRequestUtils(
            headers=self._headers(referer=down_url),
            **_proxy_kwargs(self._active_proxies),
        )
        path = await download_file(
            request,
            resolved_url,
            directory,
            fallback_name,
            prefer_response_name=True,
        )
        self._last_details["last_download_at"] = utc_now().isoformat()
        return DownloadedAsset(path=path, file_name=path.name)

    async def refresh(self, manual: bool = False) -> SourceStatus:
        """重新登录验证账号，不触发字幕搜索或下载。"""

        del manual
        status = SourceStatus(source=self.source, enabled=self.enabled, configured=self.configured)
        if not self.enabled or not self.configured:
            status.health = SourceHealth.DISABLED
            status.details = {**self._last_details, "session_active": False}
            return status
        started = utc_now()
        status.last_checked_at = started
        try:
            await self._login(force=True)
            status.health = SourceHealth.HEALTHY
            status.last_success_at = utc_now()
        except SourceLimitedError as exc:
            status.health = SourceHealth.LIMITED
            status.last_error_at = utc_now()
            status.last_error_summary = str(exc)
        except SourceRequestError as exc:
            status.health = SourceHealth.ERROR
            status.last_error_at = utc_now()
            status.last_error_summary = str(exc)
        except Exception as exc:  # noqa: BLE001 - 健康检查必须返回安全状态
            status.health = SourceHealth.ERROR
            status.last_error_at = utc_now()
            status.last_error_summary = f"SubHD 网络或响应异常（{type(exc).__name__}）"
        status.details = {**self._last_details, "session_active": self._authenticated}
        status.last_duration_ms = elapsed_ms(started)
        return status

    async def clear_cache(self) -> None:
        """清除 SubHD 候选缓存。"""

        await self._cache.clear(region=SEARCH_CACHE_REGION)

    async def close(self) -> None:
        """清除 Cookie 会话并关闭来源缓存。"""

        self._cookies.clear()
        self._authenticated = False
        await self._limiter.reset()
        await self._cache.close()

    def runtime_details(self) -> dict[str, Any]:
        """返回不包含邮箱、密码和 Cookie 的运行观测。"""

        return {**self._last_details, "session_active": self._authenticated}
