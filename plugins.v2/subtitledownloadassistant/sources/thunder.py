"""迅雷影音内容指纹字幕源。"""

from __future__ import annotations

import hashlib
import html
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
    SourceRequestError,
    _proxy_kwargs,
    download_file,
    request_res_with_proxy_fallback,
    safe_file_name,
    subtitle_format,
)
from .fingerprint import MediaFingerprintService, fallback_media_name

THUNDER_API = "https://api-shoulei-ssl.xunlei.com/oracle/subtitle"
_USER_AGENT = "MoviePilot-SubtitleDownloadAssistant-Thunder"


class ThunderSource:
    """按文件名查询迅雷候选，并用 CID 标记内容精确匹配。"""

    source = SubtitleSource.THUNDER

    def __init__(
        self,
        enabled: bool,
        allowed_formats: set[str],
        fingerprints: MediaFingerprintService,
    ) -> None:
        self.enabled = enabled
        self._allowed_formats = {item.upper().lstrip(".") for item in allowed_formats}
        self._fingerprints = fingerprints
        self._active_proxies: dict[str, str] = {}
        self._last_details: dict[str, Any] = {"attribution": "MeiamSubtitles / 迅雷影音"}

    @property
    def configured(self) -> bool:
        """迅雷源不需要账号凭据。"""

        return True

    @staticmethod
    def _integer(value: Any) -> int | None:
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _valid_download_url(value: Any) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        parsed = urlparse(value.strip())
        return value.strip() if parsed.scheme.casefold() in {"http", "https"} and parsed.netloc else None

    @staticmethod
    def _language_text(value: Any) -> str:
        values = value if isinstance(value, list) else []
        decoded: list[str] = []
        for item in values:
            text = html.unescape(html.unescape(str(item or ""))).strip()
            if text and text.casefold() not in {"amp", "eng"} and text not in decoded:
                decoded.append(text)
        return "、".join(decoded)

    async def _request(
        self,
        context: MediaContext,
        custom_query: str | None = None,
    ) -> tuple[list[CandidateHandle], int, dict[str, int], dict[str, Any]]:
        cid: str | None = None
        fingerprint_error: str | None = None
        media_name = fallback_media_name(context)
        fingerprint_input = "unavailable"
        fingerprint_transport = "不可用"
        media_size: int | None = None
        if Path(context.target_path).suffix.casefold() == ".strm":
            fingerprint_input = "strm_filename"
            fingerprint_transport = "未读取 STRM 地址"
        else:
            try:
                fingerprints = await self._fingerprints.get(context)
                cid = fingerprints.thunder_cid
                fingerprint_error = fingerprints.thunder_error
                media_name = fingerprints.media_name or media_name
                fingerprint_input = fingerprints.input_kind
                fingerprint_transport = fingerprints.transport
                media_size = fingerprints.media_size
            except SourceRequestError as exc:
                fingerprint_error = str(exc)
        query = (custom_query or "").strip() or media_name
        response, transport_details, active_proxies = await request_res_with_proxy_fallback(
            "get_res",
            THUNDER_API,
            headers={"Accept": "*/*", "User-Agent": _USER_AGENT},
            proxies=getattr(settings, "PROXY", None),
            params={"name": query},
        )
        self._active_proxies = active_proxies
        details = {
            **transport_details,
            "query_type": "filename",
            "query": query,
            "fingerprint_input": fingerprint_input,
            "fingerprint_transport": fingerprint_transport,
            "fingerprint_available": bool(cid),
            "fingerprint_error": fingerprint_error,
            "media_size": media_size,
        }
        self._last_details.update(details)
        if response is None:
            attempts = "、".join(transport_details.get("transport_attempts") or ["直连"])
            raise SourceRequestError(f"迅雷字幕接口请求失败（{attempts}均无响应）")
        try:
            if response.status_code != 200:
                raise SourceRequestError(f"迅雷字幕接口返回 HTTP {response.status_code}")
            try:
                payload = response.json()
            except Exception as exc:
                raise SourceRequestError("迅雷字幕接口返回格式无效") from exc
        finally:
            await response.aclose()
        if not isinstance(payload, dict) or self._integer(payload.get("code")) != 0:
            raise SourceRequestError("迅雷字幕接口返回错误状态")
        data = payload.get("data") or []
        if not isinstance(data, list):
            raise SourceRequestError("迅雷字幕接口候选列表无效")
        handles: list[CandidateHandle] = []
        raw_count = 0
        rejected: dict[str, int] = {}
        hash_matches = 0
        for item in data:
            if not isinstance(item, dict):
                continue
            raw_count += 1
            url = self._valid_download_url(item.get("url"))
            native_name = safe_file_name(str(item.get("name") or ""), "thunder-subtitle")
            extension = subtitle_format(native_name, str(item.get("ext") or ""))
            if not url:
                rejected["download_locator"] = rejected.get("download_locator", 0) + 1
                continue
            if extension not in self._allowed_formats:
                rejected["format"] = rejected.get("format", 0) + 1
                continue
            item_cid = str(item.get("cid") or "").strip().upper()
            hash_match = bool(cid and item_cid and cid == item_cid)
            hash_matches += int(hash_match)
            digest = hashlib.sha256(f"{url}\0{native_name}".encode("utf-8")).hexdigest()
            language = self._language_text(item.get("languages"))
            candidate = SubtitleCandidate(
                stable_key=f"thunder:{digest}",
                source=self.source,
                name=native_name,
                file_name=native_name,
                format=extension,
                language=language,
                translation_type=TranslationType.UNKNOWN,
                package_scope=PackageScope.EPISODE if hash_match else PackageScope.UNKNOWN,
                season=context.season if hash_match else None,
                episode=context.episode if hash_match else None,
                exact_id_match=hash_match,
                trusted=hash_match,
                score=float(self._integer(item.get("fingerprintf_score")) or self._integer(item.get("score")) or 0),
                metadata={
                    "content_hash_match": hash_match,
                    "native_name": native_name,
                    "description": native_name,
                    "actual_query": query,
                },
            )
            handles.append(
                CandidateHandle(
                    candidate=candidate,
                    opaque={"url": url, "file_name": native_name},
                )
            )
        details["content_hash_match_count"] = hash_matches
        self._last_details.update(details)
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
        """按文件名查询，并按语言规则过滤自动候选。"""

        started = time.monotonic()
        if not self.enabled:
            return SourceSearchResult(source=self.source)
        try:
            pool, raw_count, rejected, details = await self._request(context)
            candidates, automatic_rejected = self._filter_automatic(pool, allow_machine)
            for key, count in automatic_rejected.items():
                rejected[key] = rejected.get(key, 0) + count
            return SourceSearchResult(
                source=self.source,
                candidates=candidates,
                duration_ms=int((time.monotonic() - started) * 1000),
                raw_count=raw_count,
                admitted_count=len(candidates),
                rejection_summary=rejected,
                details=details,
            )
        except SourceRequestError as exc:
            return SourceSearchResult(
                source=self.source,
                duration_ms=int((time.monotonic() - started) * 1000),
                error_summary=str(exc),
            )
        except Exception:  # noqa: BLE001 - 外部来源异常必须收敛
            return SourceSearchResult(
                source=self.source,
                duration_ms=int((time.monotonic() - started) * 1000),
                error_summary="迅雷字幕搜索失败",
            )

    async def manual_search(
        self,
        context: MediaContext,
        custom_query: str | None = None,
    ) -> ManualSourceSearchResult:
        """按默认文件名或自定义名称返回全部可下载候选。"""

        started = time.monotonic()
        default_name = fallback_media_name(context)
        if not self.enabled:
            return ManualSourceSearchResult(source=self.source, status="disabled", default_queries=[default_name])
        try:
            candidates, raw_count, _rejected, details = await self._request(context, custom_query)
            query = str(details.get("query") or default_name)
            return ManualSourceSearchResult(
                source=self.source,
                status="success",
                candidates=candidates,
                default_queries=[default_name],
                executed_queries=[query],
                matched_query=query,
                duration_ms=int((time.monotonic() - started) * 1000),
                raw_count=raw_count,
                admitted_count=len(candidates),
                details=details,
            )
        except SourceRequestError as exc:
            return ManualSourceSearchResult(
                source=self.source,
                status="error",
                default_queries=[default_name],
                duration_ms=int((time.monotonic() - started) * 1000),
                error_summary=str(exc),
            )
        except Exception:  # noqa: BLE001 - 外部来源异常必须收敛
            return ManualSourceSearchResult(
                source=self.source,
                status="error",
                default_queries=[default_name],
                duration_ms=int((time.monotonic() - started) * 1000),
                error_summary="迅雷字幕搜索失败",
            )

    async def download(self, handle: CandidateHandle, directory: Path) -> DownloadedAsset:
        """下载迅雷返回的直接字幕文件。"""

        url = str(handle.opaque.get("url") or "")
        file_name = safe_file_name(handle.opaque.get("file_name"), "thunder-subtitle.srt")
        if not self._valid_download_url(url):
            raise SourceRequestError("迅雷候选缺少有效下载地址")
        path = await download_file(
            AsyncRequestUtils(headers={"User-Agent": _USER_AGENT}, **_proxy_kwargs(self._active_proxies)),
            url,
            directory,
            file_name,
            prefer_response_name=False,
        )
        self._last_details["last_download_at"] = utc_now().isoformat()
        return DownloadedAsset(path=path, file_name=file_name)

    async def refresh(self, manual: bool = False) -> SourceStatus:
        """用无关测试名称探测迅雷 API。"""

        del manual
        status = SourceStatus(source=self.source, enabled=self.enabled, configured=True)
        status.details = dict(self._last_details)
        if not self.enabled:
            status.health = SourceHealth.DISABLED
            return status
        started = utc_now()
        status.last_checked_at = started
        try:
            response, details, active_proxies = await request_res_with_proxy_fallback(
                "get_res",
                THUNDER_API,
                headers={"Accept": "*/*", "User-Agent": _USER_AGENT},
                proxies=getattr(settings, "PROXY", None),
                params={"name": "MoviePilot-health-check"},
            )
            self._active_proxies = active_proxies
            self._last_details.update(details)
            if response is None:
                raise SourceRequestError("迅雷字幕接口无响应")
            try:
                if response.status_code != 200:
                    raise SourceRequestError(f"迅雷字幕接口返回 HTTP {response.status_code}")
                payload = response.json()
                if not isinstance(payload, dict) or self._integer(payload.get("code")) != 0:
                    raise SourceRequestError("迅雷字幕接口返回错误状态")
            finally:
                await response.aclose()
            status.health = SourceHealth.HEALTHY
            status.last_success_at = utc_now()
        except SourceRequestError as exc:
            status.health = SourceHealth.ERROR
            status.last_error_at = utc_now()
            status.last_error_summary = str(exc)
        except Exception as exc:  # noqa: BLE001 - 健康检查必须返回安全状态
            status.health = SourceHealth.ERROR
            status.last_error_at = utc_now()
            status.last_error_summary = f"迅雷字幕接口检测失败（{type(exc).__name__}）"
        status.details = dict(self._last_details)
        status.last_duration_ms = elapsed_ms(started)
        return status

    async def close(self) -> None:
        """清理共享内容指纹缓存。"""

        await self._fingerprints.clear()

    def runtime_details(self) -> dict[str, Any]:
        """返回非敏感来源观测。"""

        return dict(self._last_details)
