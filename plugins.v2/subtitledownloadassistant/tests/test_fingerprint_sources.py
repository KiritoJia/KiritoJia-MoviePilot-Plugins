"""射手、迅雷来源与媒体内容指纹测试。"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace


class DummyRequest:
    def __init__(self, **_kwargs: object) -> None:
        pass


class FakeResponse:
    def __init__(self, payload: object, text: str | None = None, content: bytes | None = None) -> None:
        self.status_code = 200
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload, ensure_ascii=False)
        self.content = content if content is not None else self.text.encode("utf-8")
        self.closed = False

    def json(self) -> object:
        return self._payload

    async def aclose(self) -> None:
        self.closed = True


class FakeStreamResponse:
    def __init__(self, status_code: int, headers: dict[str, str], content: bytes = b"") -> None:
        self.status_code = status_code
        self.headers = headers
        self._content = content

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args: object) -> None:
        pass

    async def aiter_bytes(self, _chunk_size: int):
        if self._content:
            yield self._content


def _module(name: str, **values: object) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in values.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _load_module(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_sources() -> dict[str, types.ModuleType]:
    root = Path(__file__).resolve().parents[1]
    package = "subtitledownloadassistant_fingerprint_test"

    _module("app").__path__ = []
    _module("app.core").__path__ = []
    _module("app.core.config", settings=SimpleNamespace(PROXY=None))
    _module("app.utils").__path__ = []
    _module("app.utils.http", AsyncRequestUtils=DummyRequest)
    _module("anyio", Path=Path)

    package_module = _module(package)
    package_module.__path__ = [str(root)]
    for suffix in ("domain", "application", "sources"):
        module = _module(f"{package}.{suffix}")
        module.__path__ = [str(root / suffix)]

    loaded: dict[str, types.ModuleType] = {}
    for suffix in (
        "domain.enums",
        "domain.models",
        "domain.language",
        "application.ports",
        "sources.common",
        "sources.fingerprint",
        "sources.shooter",
        "sources.thunder",
    ):
        loaded[suffix] = _load_module(f"{package}.{suffix}", root / (suffix.replace(".", "/") + ".py"))
    return loaded


def _context(models: types.ModuleType, path: Path):
    return models.MediaContext(
        title="示例电影",
        year=2026,
        target_path=str(path),
        target_file_name=path.name,
    )


def _expected_hashes(data: bytes) -> tuple[str, str]:
    size = len(data)
    shooter = ";".join(
        hashlib.md5(data[offset : offset + 4096]).hexdigest()  # noqa: S324
        for offset in (4096, size // 3 * 2, size // 3, size - 8192)
    )
    thunder = hashlib.sha1(  # noqa: S324
        data[:0x5000] + data[size // 3 : size // 3 + 0x5000] + data[size - 0x5000 :]
    ).hexdigest().upper()
    return shooter, thunder


def test_local_and_remote_strm_fingerprints(tmp_path: Path) -> None:
    modules = _load_sources()
    models = modules["domain.models"]
    fingerprint = modules["sources.fingerprint"]
    data = bytes((index * 17 + 3) % 256 for index in range(120_000))
    expected_shooter, expected_thunder = _expected_hashes(data)
    video = tmp_path / "Example.2026.mkv"
    video.write_bytes(data)

    async def run_local() -> None:
        service = fingerprint.MediaFingerprintService()
        result = await service.get(_context(models, video))
        assert result.shooter_hash == expected_shooter
        assert result.thunder_cid == expected_thunder
        assert result.input_kind == "local"

    asyncio.run(run_local())

    class FakeRangeReader:
        def __init__(self) -> None:
            self.calls: list[tuple[int, int]] = []

        async def inspect(self, url: str):
            return fingerprint.RemoteMedia(
                url=url,
                size=len(data),
                proxies={},
                transport="直连",
                supports_ranges=True,
            )

        async def read(self, _media: object, offset: int, length: int) -> bytes:
            self.calls.append((offset, length))
            return data[offset : offset + length]

    strm = tmp_path / "Example.2026.strm"
    strm.write_text("https://media.example/Example.2026.mkv\n", encoding="utf-8")

    async def run_remote() -> None:
        reader = FakeRangeReader()
        service = fingerprint.MediaFingerprintService(remote_reader=reader)
        context = _context(models, strm)
        first, second = await asyncio.gather(service.get(context), service.get(context))
        assert first is second
        assert first.shooter_hash == expected_shooter
        assert first.thunder_cid == expected_thunder
        assert first.input_kind == "strm_http"
        assert first.media_name == "Example.2026"
        assert reader.calls == [
            (0, 0x5000),
            (len(data) // 3, 0x5000),
            (len(data) // 3 * 2, 4096),
            (len(data) - 0x5000, 0x5000),
        ]

    asyncio.run(run_remote())


def test_http_range_reader_falls_back_after_proxy_403() -> None:
    modules = _load_sources()
    fingerprint = modules["sources.fingerprint"]
    proxy = {"https": "http://proxy.invalid:7890"}
    fingerprint.settings.PROXY = proxy

    class FakeRangeRequest:
        attempts: list[tuple[dict[str, str], str]] = []

        def __init__(self, **kwargs: object) -> None:
            self.proxies = dict(kwargs.get("proxies") or {})
            self.headers = dict(kwargs.get("headers") or {})

        def get_stream(self, **_kwargs: object) -> FakeStreamResponse:
            requested_range = self.headers["Range"]
            self.attempts.append((self.proxies, requested_range))
            if requested_range == "bytes=0-0":
                return FakeStreamResponse(206, {"content-range": "bytes 0-0/100000"}, b"x")
            if self.proxies:
                return FakeStreamResponse(403, {})
            return FakeStreamResponse(206, {"content-range": "bytes 4096-4105/100000"}, b"0123456789")

    fingerprint.AsyncRequestUtils = FakeRangeRequest

    async def run() -> None:
        reader = fingerprint.HttpRangeReader()
        media = await reader.inspect("https://media.example/video.mkv")
        assert media.transport == "代理"
        assert await reader.read(media, 4096, 10) == b"0123456789"
        assert FakeRangeRequest.attempts == [
            (proxy, "bytes=0-0"),
            (proxy, "bytes=4096-4105"),
            ({}, "bytes=4096-4105"),
        ]

    asyncio.run(run())


def test_http_range_reader_reports_each_403_transport() -> None:
    modules = _load_sources()
    fingerprint = modules["sources.fingerprint"]
    proxy = {"https": "http://proxy.invalid:7890"}
    fingerprint.settings.PROXY = proxy

    class RejectingRangeRequest:
        def __init__(self, **kwargs: object) -> None:
            self.proxies = dict(kwargs.get("proxies") or {})
            self.headers = dict(kwargs.get("headers") or {})

        def get_stream(self, **_kwargs: object) -> FakeStreamResponse:
            if self.headers["Range"] == "bytes=0-0":
                return FakeStreamResponse(206, {"content-range": "bytes 0-0/100000"}, b"x")
            return FakeStreamResponse(403, {})

    fingerprint.AsyncRequestUtils = RejectingRangeRequest

    async def run() -> None:
        reader = fingerprint.HttpRangeReader()
        media = await reader.inspect("https://media.example/video.mkv")
        try:
            await reader.read(media, 4096, 10)
        except fingerprint.SourceRequestError as exc:
            assert str(exc) == "STRM 远程媒体范围请求失败（代理返回 HTTP 403；直连返回 HTTP 403）"
        else:
            raise AssertionError("代理和直连均返回 403 时必须抛出来源错误")

    asyncio.run(run())


def test_thunder_uses_strm_filename_without_reading_media() -> None:
    modules = _load_sources()
    models = modules["domain.models"]
    thunder = modules["sources.thunder"]
    requested: dict[str, object] = {}

    class RejectingFingerprints:
        async def get(self, _context: object):
            raise AssertionError("迅雷处理 STRM 时不应读取内部媒体地址")

        async def clear(self) -> None:
            pass

    async def fake_request(method: str, _url: str, **kwargs: object):
        assert method == "get_res"
        requested.update(kwargs)
        return FakeResponse({"code": 0, "data": []}), {"transport": "直连"}, {}

    thunder.request_res_with_proxy_fallback = fake_request
    context = models.MediaContext(
        title="惊天魔盗团2",
        year=2016,
        target_path="/media/惊天魔盗团2 (2016) - 2160p.strm",
        target_file_name="惊天魔盗团2 (2016) - 2160p.strm",
    )

    async def run() -> None:
        source = thunder.ThunderSource(True, {"ASS", "SRT"}, RejectingFingerprints())
        result = await source.search(context, allow_machine=False)
        assert result.error_summary is None
        assert result.details["fingerprint_input"] == "strm_filename"
        assert result.details["fingerprint_transport"] == "未读取 STRM 地址"
        assert requested["params"] == {"name": "惊天魔盗团2 (2016) - 2160p"}

    asyncio.run(run())


def test_shooter_and_thunder_candidate_parsing(tmp_path: Path) -> None:
    modules = _load_sources()
    models = modules["domain.models"]
    fingerprint = modules["sources.fingerprint"]
    shooter = modules["sources.shooter"]
    thunder = modules["sources.thunder"]
    target = tmp_path / "Example.S01E02.mkv"
    target.write_bytes(b"test")
    context = models.MediaContext(
        title="示例剧集",
        media_type=modules["domain.enums"].MediaType.TV,
        season=1,
        episode=2,
        target_path=str(target),
        target_file_name=target.name,
    )

    class FakeFingerprints:
        async def get(self, _context: object):
            return fingerprint.MediaFingerprints(
                media_name=target.name,
                media_size=1_000_000,
                input_kind="local",
                transport="本地文件",
                shooter_hash="a" * 32 + ";" + ";".join(["b" * 32] * 3),
                thunder_cid="CID-MATCH",
            )

        async def clear(self) -> None:
            pass

    responses = {
        "post_res": FakeResponse([{"Files": [{"Ext": "ass", "Link": "https://sub.example/a.ass"}]}]),
        "get_res": FakeResponse(
            {
                "code": 0,
                "data": [
                    {
                        "cid": "CID-MATCH",
                        "url": "https://sub.example/bilingual.srt",
                        "ext": "srt",
                        "name": "Example.S01E02.chs&eng.srt",
                        "languages": ["简体&英语"],
                        "fingerprintf_score": 10,
                    },
                    {
                        "cid": "OTHER",
                        "url": "https://sub.example/simplified.ass",
                        "ext": "ass",
                        "name": "Example.S01E02.chs.ass",
                        "languages": ["简体"],
                    },
                    {
                        "cid": "OTHER-EN",
                        "url": "https://sub.example/english.srt",
                        "ext": "srt",
                        "name": "Example.S01E02.eng.srt",
                        "languages": ["英语"],
                    },
                ],
            }
        ),
    }

    async def fake_request(method: str, _url: str, **_kwargs: object):
        response = responses[method]
        response.closed = False
        return response, {"transport": "直连", "proxy_fallback": False}, {}

    shooter.request_res_with_proxy_fallback = fake_request
    thunder.request_res_with_proxy_fallback = fake_request

    assert shooter.ShooterSource._response_payload(FakeResponse(None, text="\ufffd", content=b"\xff")) == []
    try:
        shooter.ShooterSource._response_payload(
            FakeResponse(None, text="<html>Cloudflare challenge</html>"),
        )
    except shooter.SourceRequestError as exc:
        assert "可能被网络或 Cloudflare 拦截" in str(exc)
    else:
        raise AssertionError("射手 HTML 拦截页必须被识别为来源错误")

    async def run() -> None:
        shooter_source = shooter.ShooterSource(True, {"ASS", "SRT"}, FakeFingerprints())
        shooter_result = await shooter_source.search(context, allow_machine=False)
        assert len(shooter_result.candidates) == 1
        assert shooter_result.candidates[0].candidate.metadata["content_hash_match"] is True
        assert shooter_result.candidates[0].candidate.season == 1
        assert responses["post_res"].closed is True

        thunder_source = thunder.ThunderSource(True, {"ASS", "SRT"}, FakeFingerprints())
        thunder_result = await thunder_source.search(context, allow_machine=False)
        assert len(thunder_result.candidates) == 2
        assert thunder_result.raw_count == 3
        assert thunder_result.rejection_summary == {"language": 1}
        assert thunder_result.details["content_hash_match_count"] == 1
        assert thunder_result.candidates[0].candidate.metadata["content_hash_match"] is True
        assert responses["get_res"].closed is True

    asyncio.run(run())
