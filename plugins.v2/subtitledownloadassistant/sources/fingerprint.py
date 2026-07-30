"""本地媒体与 STRM 目标的内容指纹读取。"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote, urlparse

from app.core.config import settings
from app.utils.http import AsyncRequestUtils

from ..domain.models import MediaContext
from .common import SourceRequestError

_SHOOTER_MINIMUM_SIZE = 8 * 1024
_THUNDER_SAMPLE_SIZE = 0x5000
_THUNDER_FULL_SAMPLE_SIZE = 0xF000
_STRM_READ_LIMIT = 64 * 1024
_CONTENT_RANGE = re.compile(r"^bytes\s+(\d+)-(\d+)/(\d+|\*)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class RemoteMedia:
    """远程媒体长度、传输方式与 Range 能力。"""

    url: str
    size: int
    proxies: dict[str, str]
    transport: str
    supports_ranges: bool


@dataclass(frozen=True, slots=True)
class MediaFingerprints:
    """一次媒体采样生成的两个来源指纹。"""

    media_name: str
    media_size: int
    input_kind: str
    transport: str
    shooter_hash: str | None
    thunder_cid: str | None
    shooter_error: str | None = None
    thunder_error: str | None = None


class RemoteRangeReader(Protocol):
    """远程媒体最小范围读取协议。"""

    async def inspect(self, url: str) -> RemoteMedia:
        """读取媒体长度并确定是否支持范围请求。"""

    async def read(self, media: RemoteMedia, offset: int, length: int) -> bytes:
        """读取指定闭开区间的媒体字节。"""


class HttpRangeReader:
    """通过 MoviePilot HTTP 工具执行有上限的 Range 读取。"""

    _headers = {
        "Accept": "*/*",
        "Accept-Encoding": "identity",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
    }

    @staticmethod
    def _proxy_candidates() -> list[tuple[str, dict[str, str]]]:
        proxies = getattr(settings, "PROXY", None) or {}
        result: list[tuple[str, dict[str, str]]] = []
        if proxies:
            result.append(("代理", dict(proxies)))
        result.append(("直连", {}))
        return result

    @staticmethod
    def _total_size(headers: Any) -> tuple[int | None, bool]:
        content_range = str(headers.get("content-range") or "").strip()
        match = _CONTENT_RANGE.match(content_range)
        if match and match.group(3) != "*":
            return int(match.group(3)), True
        content_length = str(headers.get("content-length") or "").strip()
        if content_length.isdigit():
            accept_ranges = str(headers.get("accept-ranges") or "").casefold()
            return int(content_length), "bytes" in accept_ranges
        return None, False

    @classmethod
    def _range_candidates(cls, media: RemoteMedia) -> list[tuple[str, dict[str, str]]]:
        """优先复用探测成功的链路，并保留另一条链路作为 Range 回退。"""

        result = [(media.transport, dict(media.proxies))]
        for transport, proxies in cls._proxy_candidates():
            if proxies != media.proxies:
                result.append((transport, proxies))
        return result

    async def inspect(self, url: str) -> RemoteMedia:
        """以 1 字节流式请求探测长度，服务端忽略 Range 时也不下载正文。"""

        for transport, proxies in self._proxy_candidates():
            headers = {**self._headers, "Range": "bytes=0-0"}
            request = AsyncRequestUtils(headers=headers, proxies=proxies)
            try:
                async with request.get_stream(url=url) as response:
                    if response is None or response.status_code >= 400:
                        continue
                    size, supports_ranges = self._total_size(response.headers)
                    if size is None or size <= 0:
                        continue
                    return RemoteMedia(
                        url=url,
                        size=size,
                        proxies=proxies,
                        transport=transport,
                        supports_ranges=response.status_code == 206 or supports_ranges,
                    )
            except Exception:  # noqa: BLE001 - 不同宿主版本的流式请求异常不一致
                continue
        raise SourceRequestError("STRM 远程媒体长度探测失败（代理、直连均不可用）")

    async def read(self, media: RemoteMedia, offset: int, length: int) -> bytes:
        """读取一个小范围，当前链路失败时自动尝试代理/直连备用链路。"""

        if offset < 0 or length <= 0 or offset + length > media.size:
            raise SourceRequestError("STRM 远程媒体范围参数无效")
        errors: list[str] = []
        for transport, proxies in self._range_candidates(media):
            try:
                return await self._read_once(media, offset, length, proxies)
            except SourceRequestError as exc:
                errors.append(f"{transport}{exc}")
        summary = "；".join(errors) or "没有可用传输方式"
        raise SourceRequestError(f"STRM 远程媒体范围请求失败（{summary}）")

    async def _read_once(
        self,
        media: RemoteMedia,
        offset: int,
        length: int,
        proxies: dict[str, str],
    ) -> bytes:
        """通过单一传输方式读取范围，并返回不含地址的安全错误。"""

        headers = {
            **self._headers,
            "Range": f"bytes={offset}-{offset + length - 1}",
        }
        request = AsyncRequestUtils(headers=headers, proxies=proxies)
        try:
            async with request.get_stream(url=media.url) as response:
                if response is None:
                    raise SourceRequestError("无响应")
                if response.status_code >= 400:
                    raise SourceRequestError(f"返回 HTTP {response.status_code}")
                if response.status_code != 206 and offset != 0:
                    raise SourceRequestError("不支持 HTTP Range")
                if response.status_code == 206:
                    match = _CONTENT_RANGE.match(str(response.headers.get("content-range") or "").strip())
                    if not match or int(match.group(1)) != offset:
                        raise SourceRequestError("返回了错误的字节范围")
                data = bytearray()
                async for chunk in response.aiter_bytes(min(length, 64 * 1024)):
                    if not chunk:
                        continue
                    remaining = length - len(data)
                    data.extend(chunk[:remaining])
                    if len(data) == length:
                        break
        except SourceRequestError:
            raise
        except Exception as exc:  # noqa: BLE001 - 对外只保留安全错误类型
            raise SourceRequestError(f"读取异常（{type(exc).__name__}）") from exc
        if len(data) != length:
            raise SourceRequestError("返回的字节数不足")
        return bytes(data)


class MediaFingerprintService:
    """共享一次媒体采样，避免射手和迅雷重复读取同一目标。"""

    def __init__(self, remote_reader: RemoteRangeReader | None = None, max_cache_size: int = 128) -> None:
        self._remote_reader = remote_reader or HttpRangeReader()
        self._max_cache_size = max(1, max_cache_size)
        self._tasks: OrderedDict[str, asyncio.Task[MediaFingerprints]] = OrderedDict()
        self._lock = asyncio.Lock()

    @staticmethod
    def _target_signature(context: MediaContext) -> str:
        path = Path(context.target_path)
        try:
            stat = path.stat()
            return f"{path}:{stat.st_size}:{stat.st_mtime_ns}"
        except OSError:
            return str(path)

    async def get(self, context: MediaContext) -> MediaFingerprints:
        """返回缓存指纹，同一目标的并发请求只执行一次采样。"""

        key = await asyncio.to_thread(self._target_signature, context)
        async with self._lock:
            task = self._tasks.get(key)
            if task is None:
                task = asyncio.create_task(self._compute(context))
                self._tasks[key] = task
                while len(self._tasks) > self._max_cache_size:
                    old_key, old_task = next(iter(self._tasks.items()))
                    if not old_task.done():
                        break
                    self._tasks.pop(old_key, None)
            else:
                self._tasks.move_to_end(key)
        try:
            return await asyncio.shield(task)
        except BaseException:
            async with self._lock:
                if self._tasks.get(key) is task:
                    self._tasks.pop(key, None)
            raise

    async def clear(self) -> None:
        """清除当前运行代次的指纹任务缓存。"""

        async with self._lock:
            tasks = list(self._tasks.values())
            self._tasks.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    def _read_strm(path: Path) -> str:
        with path.open("rb") as stream:
            raw = stream.read(_STRM_READ_LIMIT + 1)
        if len(raw) > _STRM_READ_LIMIT:
            raise SourceRequestError("STRM 文件内容超过 64 KiB，拒绝解析")
        text = raw.decode("utf-8-sig", errors="replace")
        return next((line.strip() for line in text.splitlines() if line.strip()), "")

    @classmethod
    def _resolve_local_strm(cls, strm_path: Path, locator: str) -> Path | None:
        parsed = urlparse(locator)
        if parsed.scheme.casefold() == "file" and parsed.hostname in (None, "", "localhost"):
            return Path(unquote(parsed.path))
        if parsed.scheme:
            return None
        candidate = Path(locator)
        return candidate if candidate.is_absolute() else strm_path.parent / candidate

    @staticmethod
    def _fallback_media_name(context: MediaContext) -> str:
        name = Path(context.target_file_name).name
        return Path(name).stem if Path(name).suffix.casefold() == ".strm" else name

    async def _compute(self, context: MediaContext) -> MediaFingerprints:
        target = Path(context.target_path)
        fallback_name = self._fallback_media_name(context)
        if target.suffix.casefold() != ".strm":
            return await asyncio.to_thread(self._compute_local, target, fallback_name)
        locator = await asyncio.to_thread(self._read_strm, target)
        if not locator:
            raise SourceRequestError("STRM 文件没有可用的媒体地址")
        parsed = urlparse(locator)
        if parsed.scheme.casefold() in {"http", "https"}:
            return await self._compute_remote(locator, fallback_name)
        local = self._resolve_local_strm(target, locator)
        if local is None:
            raise SourceRequestError("STRM 媒体地址不是受支持的本地路径或 HTTP(S) 地址")
        return await asyncio.to_thread(self._compute_local, local, fallback_name)

    @staticmethod
    def _shooter_hash_from_bytes(data: bytes, size: int) -> str | None:
        if size < _SHOOTER_MINIMUM_SIZE or len(data) != size:
            return None
        offsets = (4 * 1024, size // 3 * 2, size // 3, size - 8 * 1024)
        return ";".join(hashlib.md5(data[offset : offset + 4096]).hexdigest() for offset in offsets)  # noqa: S324

    @staticmethod
    def _thunder_cid_from_bytes(data: bytes, size: int) -> str:
        if size < _THUNDER_FULL_SAMPLE_SIZE:
            sample = data
        else:
            sample = b"".join(
                (
                    data[:_THUNDER_SAMPLE_SIZE],
                    data[size // 3 : size // 3 + _THUNDER_SAMPLE_SIZE],
                    data[size - _THUNDER_SAMPLE_SIZE :],
                )
            )
        return hashlib.sha1(sample).hexdigest().upper()  # noqa: S324

    @classmethod
    def _compute_local(cls, path: Path, media_name: str) -> MediaFingerprints:
        try:
            size = path.stat().st_size
            if size <= 0 or not path.is_file():
                raise OSError
            with path.open("rb") as stream:
                if size < _THUNDER_FULL_SAMPLE_SIZE:
                    data = stream.read()
                    shooter_hash = cls._shooter_hash_from_bytes(data, size)
                    thunder_cid = cls._thunder_cid_from_bytes(data, size)
                else:
                    start = stream.read(_THUNDER_SAMPLE_SIZE)
                    stream.seek(size // 3)
                    third = stream.read(_THUNDER_SAMPLE_SIZE)
                    stream.seek(size // 3 * 2)
                    two_thirds = stream.read(4096)
                    stream.seek(size - _THUNDER_SAMPLE_SIZE)
                    tail = stream.read(_THUNDER_SAMPLE_SIZE)
                    if min(len(start), len(third), len(tail)) < _THUNDER_SAMPLE_SIZE or len(two_thirds) < 4096:
                        raise OSError
                    shooter_hash = ";".join(
                        (
                            hashlib.md5(start[4096:8192]).hexdigest(),  # noqa: S324
                            hashlib.md5(two_thirds).hexdigest(),  # noqa: S324
                            hashlib.md5(third[:4096]).hexdigest(),  # noqa: S324
                            hashlib.md5(tail[-8192:-4096]).hexdigest(),  # noqa: S324
                        )
                    )
                    thunder_cid = hashlib.sha1(start + third + tail).hexdigest().upper()  # noqa: S324
        except OSError as exc:
            raise SourceRequestError("本地媒体文件无法读取") from exc
        return MediaFingerprints(
            media_name=media_name,
            media_size=size,
            input_kind="local",
            transport="本地文件",
            shooter_hash=shooter_hash,
            thunder_cid=thunder_cid,
            shooter_error=None if shooter_hash else "媒体文件小于 8 KiB，无法计算射手指纹",
        )

    async def _compute_remote(self, url: str, media_name: str) -> MediaFingerprints:
        media = await self._remote_reader.inspect(url)
        if media.size < _THUNDER_FULL_SAMPLE_SIZE:
            data = await self._remote_reader.read(media, 0, media.size)
            shooter_hash = self._shooter_hash_from_bytes(data, media.size)
            return MediaFingerprints(
                media_name=media_name,
                media_size=media.size,
                input_kind="strm_http",
                transport=media.transport,
                shooter_hash=shooter_hash,
                thunder_cid=self._thunder_cid_from_bytes(data, media.size),
                shooter_error=None if shooter_hash else "远程媒体小于 8 KiB，无法计算射手指纹",
            )
        if not media.supports_ranges:
            return MediaFingerprints(
                media_name=media_name,
                media_size=media.size,
                input_kind="strm_http",
                transport=media.transport,
                shooter_hash=None,
                thunder_cid=None,
                shooter_error="STRM 远程媒体不支持 HTTP Range",
                thunder_error="STRM 远程媒体不支持 HTTP Range",
            )
        # 顺序读取四个小范围，避免媒体反代把并发 Range 判定为滥用请求。
        start = await self._remote_reader.read(media, 0, _THUNDER_SAMPLE_SIZE)
        third = await self._remote_reader.read(media, media.size // 3, _THUNDER_SAMPLE_SIZE)
        two_thirds = await self._remote_reader.read(media, media.size // 3 * 2, 4096)
        tail = await self._remote_reader.read(media, media.size - _THUNDER_SAMPLE_SIZE, _THUNDER_SAMPLE_SIZE)
        shooter_hash = ";".join(
            (
                hashlib.md5(start[4096:8192]).hexdigest(),  # noqa: S324
                hashlib.md5(two_thirds).hexdigest(),  # noqa: S324
                hashlib.md5(third[:4096]).hexdigest(),  # noqa: S324
                hashlib.md5(tail[-8192:-4096]).hexdigest(),  # noqa: S324
            )
        )
        thunder_cid = hashlib.sha1(start + third + tail).hexdigest().upper()  # noqa: S324
        return MediaFingerprints(
            media_name=media_name,
            media_size=media.size,
            input_kind="strm_http",
            transport=media.transport,
            shooter_hash=shooter_hash,
            thunder_cid=thunder_cid,
        )


def fallback_media_name(context: MediaContext) -> str:
    """为无需或无法读取指纹的来源返回安全媒体查询名。"""

    return MediaFingerprintService._fallback_media_name(context)
