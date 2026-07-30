"""射手网文件指纹字幕源。"""

from __future__ import annotations

import hashlib
import json
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
from ..domain.models import MediaContext, SourceStatus, SubtitleCandidate, elapsed_ms, utc_now
from .common import (
    SourceRequestError,
    _proxy_kwargs,
    download_file,
    request_res_with_proxy_fallback,
    safe_file_name,
    subtitle_format,
)
from .fingerprint import MediaFingerprintService

SHOOTER_API = "https://www.shooter.cn/api/subapi.php"
_USER_AGENT = "MoviePilot-SubtitleDownloadAssistant-Shooter"


class ShooterSource:
    """按射手四段 MD5 指纹搜索并下载直接字幕文件。"""

    source = SubtitleSource.SHOOTER

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
        self._last_details: dict[str, Any] = {"attribution": "MeiamSubtitles / 射手网"}

    @property
    def configured(self) -> bool:
        """射手源不需要账号凭据。"""

        return True

    @staticmethod
    def _field(item: dict[str, Any], name: str) -> Any:
        return item.get(name) if name in item else item.get(name.casefold())

    @staticmethod
    def _valid_download_url(value: Any) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        parsed = urlparse(value.strip())
        return value.strip() if parsed.scheme.casefold() in {"http", "https"} and parsed.netloc else None

    @staticmethod
    def _response_payload(response: Any) -> list[Any]:
        """区分射手的 FF 无结果哨兵与网关/WAF 返回的异常正文。"""

        raw_content = getattr(response, "content", None)
        if isinstance(raw_content, bytearray):
            raw_content = bytes(raw_content)
        if isinstance(raw_content, bytes) and raw_content in {b"", b"\xff"}:
            return []

        body = str(getattr(response, "text", "") or "").strip()
        if not body or body == "\ufffd":
            return []
        if not body.startswith("["):
            raise SourceRequestError("射手字幕接口返回非 JSON 内容，可能被网络或 Cloudflare 拦截")
        try:
            payload = response.json()
        except Exception:
            try:
                payload = json.loads(body)
            except (TypeError, ValueError) as exc:
                raise SourceRequestError("射手字幕接口返回的 JSON 无法解析") from exc
        if not isinstance(payload, list):
            raise SourceRequestError("射手字幕接口返回格式无效")
        return payload

    async def _request(
        self,
        context: MediaContext,
        query_name: str | None = None,
    ) -> tuple[list[CandidateHandle], int, dict[str, int], dict[str, Any]]:
        fingerprints = await self._fingerprints.get(context)
        if not fingerprints.shooter_hash:
            raise SourceRequestError(f"射手指纹不可用：{fingerprints.shooter_error or '视频内容无法读取'}")
        media_name = (query_name or "").strip() or fingerprints.media_name
        response, transport_details, active_proxies = await request_res_with_proxy_fallback(
            "post_res",
            SHOOTER_API,
            headers={"Accept": "*/*", "User-Agent": _USER_AGENT},
            proxies=getattr(settings, "PROXY", None),
            data={
                "filehash": fingerprints.shooter_hash,
                "pathinfo": media_name,
                "format": "json",
                "lang": "chn",
            },
        )
        self._active_proxies = active_proxies
        details = {
            **transport_details,
            "query_type": "content_fingerprint",
            "query": media_name,
            "fingerprint_input": fingerprints.input_kind,
            "fingerprint_transport": fingerprints.transport,
            "media_size": fingerprints.media_size,
        }
        self._last_details.update(details)
        if response is None:
            attempts = "、".join(transport_details.get("transport_attempts") or ["直连"])
            raise SourceRequestError(f"射手字幕接口请求失败（{attempts}均无响应）")
        try:
            if response.status_code != 200:
                raise SourceRequestError(f"射手字幕接口返回 HTTP {response.status_code}")
            payload = self._response_payload(response)
        finally:
            await response.aclose()
        handles: list[CandidateHandle] = []
        raw_count = 0
        rejected: dict[str, int] = {}
        for group in payload:
            if not isinstance(group, dict):
                continue
            files = self._field(group, "Files") or []
            if not isinstance(files, list):
                continue
            for file_info in files:
                if not isinstance(file_info, dict):
                    continue
                raw_count += 1
                url = self._valid_download_url(self._field(file_info, "Link"))
                extension = subtitle_format(None, str(self._field(file_info, "Ext") or ""))
                if not url:
                    rejected["download_locator"] = rejected.get("download_locator", 0) + 1
                    continue
                if extension not in self._allowed_formats:
                    rejected["format"] = rejected.get("format", 0) + 1
                    continue
                digest = hashlib.sha256(f"{url}\0{extension}".encode("utf-8")).hexdigest()
                file_name = f"shooter-{digest[:16]}.{extension.casefold()}"
                candidate = SubtitleCandidate(
                    stable_key=f"shooter:{digest}",
                    source=self.source,
                    name=f"{Path(context.target_file_name).stem} · 射手字幕",
                    file_name=file_name,
                    format=extension,
                    language="简体中文",
                    translation_type=TranslationType.UNKNOWN,
                    package_scope=PackageScope.EPISODE,
                    season=context.season,
                    episode=context.episode,
                    exact_id_match=True,
                    trusted=True,
                    metadata={
                        "content_hash_match": True,
                        "native_name": file_name,
                        "actual_query": media_name,
                    },
                )
                handles.append(
                    CandidateHandle(
                        candidate=candidate,
                        opaque={"url": url, "file_name": file_name},
                    )
                )
        return handles, raw_count, rejected, details

    async def search(self, context: MediaContext, allow_machine: bool) -> SourceSearchResult:
        """按目标内容指纹返回自动候选。"""

        del allow_machine
        started = time.monotonic()
        if not self.enabled:
            return SourceSearchResult(source=self.source)
        try:
            candidates, raw_count, rejected, details = await self._request(context)
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
                error_summary="射手字幕搜索失败",
            )

    async def manual_search(
        self,
        context: MediaContext,
        custom_query: str | None = None,
    ) -> ManualSourceSearchResult:
        """执行一次内容指纹搜索；自定义词仅替换 pathinfo。"""

        started = time.monotonic()
        default_name = Path(context.target_file_name).stem
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
                error_summary="射手字幕搜索失败",
            )

    async def download(self, handle: CandidateHandle, directory: Path) -> DownloadedAsset:
        """下载射手返回的直接字幕文件。"""

        url = str(handle.opaque.get("url") or "")
        file_name = safe_file_name(handle.opaque.get("file_name"), "shooter-subtitle.srt")
        if not self._valid_download_url(url):
            raise SourceRequestError("射手候选缺少有效下载地址")
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
        """以无效测试指纹探测射手 API，不产生字幕下载。"""

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
                "post_res",
                SHOOTER_API,
                headers={"Accept": "*/*", "User-Agent": _USER_AGENT},
                proxies=getattr(settings, "PROXY", None),
                data={
                    "filehash": ";".join(["0" * 32] * 4),
                    "pathinfo": "MoviePilot-health-check.mkv",
                    "format": "json",
                    "lang": "chn",
                },
            )
            self._active_proxies = active_proxies
            self._last_details.update(details)
            if response is None:
                raise SourceRequestError("射手字幕接口无响应")
            try:
                if response.status_code != 200:
                    raise SourceRequestError(f"射手字幕接口返回 HTTP {response.status_code}")
                self._response_payload(response)
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
            status.last_error_summary = f"射手字幕接口检测失败（{type(exc).__name__}）"
        status.details = dict(self._last_details)
        status.last_duration_ms = elapsed_ms(started)
        return status

    async def close(self) -> None:
        """清理共享内容指纹缓存。"""

        await self._fingerprints.clear()

    def runtime_details(self) -> dict[str, Any]:
        """返回非敏感来源观测。"""

        return dict(self._last_details)
