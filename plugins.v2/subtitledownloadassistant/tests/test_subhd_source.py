"""SubHD 账号会话、页面解析和下载协议测试。"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote


class DummyCache:
    def __init__(self, **_kwargs: object) -> None:
        self.values: dict[tuple[str | None, str], object] = {}

    async def get(self, key: str, region: str | None = None) -> object | None:
        return self.values.get((region, key))

    async def set(self, key: str, value: object, region: str | None = None) -> None:
        self.values[(region, key)] = value

    async def clear(self, region: str | None = None) -> None:
        self.values = {
            cache_key: value
            for cache_key, value in self.values.items()
            if cache_key[0] != region
        }

    async def close(self) -> None:
        self.values.clear()


class DummyRequest:
    def __init__(self, **kwargs: object) -> None:
        self.options = kwargs


class FakeLimiter:
    async def acquire(self, wait: bool) -> None:
        assert wait is True

    async def reset(self) -> None:
        pass


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        payload: object | None = None,
        *,
        text: str = "",
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.closed = False

    def json(self) -> object:
        return self._payload

    async def aclose(self) -> None:
        self.closed = True


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


def _load_subhd() -> tuple[types.ModuleType, types.ModuleType, types.ModuleType, types.ModuleType]:
    root = Path(__file__).resolve().parents[1]
    package = "subtitledownloadassistant_subhd_test"

    _module("app").__path__ = []
    _module("app.core").__path__ = []
    _module("app.core.cache", AsyncMemoryBackend=DummyCache)
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
        "application.path_mapping",
        "application.config",
        "application.ports",
        "sources.common",
        "sources.limiter",
        "sources.subhd",
    ):
        loaded[suffix] = _load_module(f"{package}.{suffix}", root / (suffix.replace(".", "/") + ".py"))
    return (
        loaded["sources.subhd"],
        loaded["domain.models"],
        loaded["application.ports"],
        loaded["application.config"],
    )


def _source(module: types.ModuleType, base_url: str = "https://subhd.tv"):
    return module.SubHDSource(
        enabled=True,
        credentials={"email": "user@example.com", "password": "secret"},
        allowed_formats={"ASS", "SRT"},
        base_url=base_url,
        limiter=FakeLimiter(),
    )


def _context(models: types.ModuleType, file_name: str = "惊天魔盗团2 (2016) - 2160p.strm"):
    return models.MediaContext(
        title="惊天魔盗团2",
        english_title="Now You See Me 2",
        year=2016,
        target_path=f"/media/{file_name}",
        target_file_name=file_name,
    )


def test_subhd_parser_classifies_language_priority_candidates() -> None:
    subhd, models, _ports, _config = _load_subhd()
    source = _source(subhd)
    body = """
        <main>
          <div><span>简英双语 ASS</span><a href="/a/dual-1">影片 2016 简英</a></div>
          <div><span>简体中文 SRT</span><a href="/a/simple-2">影片 2016 简中</a></div>
          <div><span>繁體中文 ASS</span><a href="/a/traditional-3">影片 2016 繁中</a></div>
        </main>
    """

    handles, raw_count, media_paths = source._parse_cards(body, _context(models), "影片 2016")

    assert raw_count == 3
    assert media_paths == []
    assert [item.candidate.stable_key for item in handles] == [
        "subhd:dual-1",
        "subhd:simple-2",
        "subhd:traditional-3",
    ]
    assert handles[0].candidate.metadata["language_flags"] == {
        "zh-cn": True,
        "zh-tw": False,
        "eng": True,
    }
    assert handles[1].candidate.metadata["language_flags"]["zh-cn"] is True
    assert handles[2].candidate.metadata["language_flags"]["zh-tw"] is True


def test_subhd_login_captures_cookie_and_reports_invalid_credentials() -> None:
    subhd, _models, _ports, _config = _load_subhd()
    source = _source(subhd, "https://subhd-proxy.example")
    requests: list[tuple[str, str, dict[str, object]]] = []
    responses = [
        FakeResponse(200, {"success": True}, headers={"set-cookie": "subhd_session=abc123; Path=/; HttpOnly"}),
        FakeResponse(200, {"success": False, "msg": "账号或密码错误"}),
        FakeResponse(200, {"success": True}),
    ]

    async def fake_request(method: str, url: str, **kwargs: object):
        requests.append((method, url, kwargs))
        return responses.pop(0), {"transport": "直连"}, {}

    subhd.request_res_with_proxy_fallback = fake_request

    async def run() -> None:
        healthy = await source.refresh()
        assert healthy.health.value == "healthy"
        assert source._cookies == {"subhd_session": "abc123"}
        assert requests[0][0] == "post_res"
        assert requests[0][1] == "https://subhd-proxy.example/api/set/login"
        assert requests[0][2]["json"] == {"email": "user@example.com", "pwd": "secret"}
        assert "secret" not in str(source.runtime_details())
        assert "abc123" not in str(source.runtime_details())

        invalid = await source.refresh()
        assert invalid.health.value == "error"
        assert invalid.last_error_summary == "账号或密码错误"
        assert source._authenticated is False

        missing_cookie = await source.refresh()
        assert missing_cookie.health.value == "error"
        assert missing_cookie.last_error_summary == "SubHD 登录成功但未返回会话 Cookie"

    asyncio.run(run())


def test_subhd_strm_search_uses_filename_and_media_detail_fallback() -> None:
    subhd, models, _ports, _config = _load_subhd()
    source = _source(subhd)
    requested_urls: list[str] = []
    responses = [
        FakeResponse(text='<a href="/d/2048">惊天魔盗团2 (2016)</a>'),
        FakeResponse(text='<span>简英双语 ASS</span><a href="/a/sub-2048">Now You See Me 2 简英</a>'),
    ]

    async def no_login(force: bool = False) -> None:
        del force
        source._authenticated = True

    async def fake_request(method: str, url: str, **_kwargs: object):
        assert method == "get_res"
        requested_urls.append(url)
        return responses.pop(0), {"transport": "直连"}, {}

    source._login = no_login
    subhd.request_res_with_proxy_fallback = fake_request

    async def run() -> None:
        assert source._queries(_context(models)) == ["惊天魔盗团2 (2016) - 2160p"]
        result = await source.search(_context(models), allow_machine=False)
        assert result.error_summary is None
        assert len(result.candidates) == 1
        assert result.details["query_type"] == "filename"
        assert result.details["detail_page_count"] == 1
        assert unquote(requested_urls[0]).endswith("/search/惊天魔盗团2 (2016) - 2160p")
        assert requested_urls[1].endswith("/d/2048")

    asyncio.run(run())


def test_subhd_download_authorization_and_captcha_error(tmp_path: Path) -> None:
    subhd, _models, ports, _config = _load_subhd()
    source = _source(subhd, "https://subhd-mirror.example")
    handle = ports.CandidateHandle(
        candidate=SimpleNamespace(),
        opaque={"sid": "subtitle-1", "page_url": "https://subhd-mirror.example/a/subtitle-1"},
    )
    calls: list[tuple[str, dict[str, object], str]] = []

    async def no_login(force: bool = False) -> None:
        del force

    async def fake_page(url: str, referer: str):
        del referer
        parser = subhd._SubHDDetailParser()
        if "/a/" in url:
            parser.feed('<button class="subtitle-prepare-download" data-sid="subtitle-1"></button>')
        return "", parser

    async def successful_post(path: str, payload: dict[str, object], referer: str):
        calls.append((path, payload, referer))
        if path.endswith("prepare-download"):
            return {"success": True, "url": "/down/download-1"}
        return {
            "success": True,
            "url": "https://subhd.tv/files/subtitle-1.ass",
            "filename": "subtitle-1.ass",
        }

    async def fake_download(_request: object, url: str, directory: Path, file_name: str, **_kwargs: object):
        assert url == "https://subhd-mirror.example/files/subtitle-1.ass"
        path = directory / file_name
        path.write_bytes(b"subtitle")
        return path

    source._login = no_login
    source._page = fake_page
    source._post_json = successful_post
    subhd.download_file = fake_download

    async def run() -> None:
        asset = await source.download(handle, tmp_path)
        assert asset.file_name == "subtitle-1.ass"
        assert calls[0][1] == {"sid": "subtitle-1"}
        assert calls[1][1] == {"sid": "download-1", "cap": ""}

        async def captcha_post(path: str, payload: dict[str, object], referer: str):
            del payload, referer
            if path.endswith("prepare-download"):
                return {"success": True, "url": "/down/download-2"}
            return {"success": False, "pass": False, "msg": "<svg>captcha</svg>"}

        source._post_json = captcha_post
        try:
            await source.download(handle, tmp_path)
        except subhd.SourceRequestError as exc:
            assert "验证码" in str(exc)
        else:
            raise AssertionError("SubHD 要求验证码时必须返回明确错误")

    asyncio.run(run())


def test_subhd_custom_base_url_validation() -> None:
    _subhd, _models, _ports, config = _load_subhd()

    assert config.normalize_subhd_base_url("https://mirror.example/") == "https://mirror.example"
    assert config.normalize_subhd_base_url("http://192.168.1.8:8080") == "http://192.168.1.8:8080"
    assert config.PluginConfig.from_mapping(
        {"subhd_base_url": "https://mirror.example/"},
        ["ASS", "SRT"],
    ).subhd_base_url == "https://mirror.example"

    for value in (
        "subhd.tv",
        "ftp://subhd.tv",
        "https://user:secret@subhd.tv",
        "https://subhd.tv/proxy",
        "https://subhd.tv?token=secret",
        "https://subhd.tv:invalid",
    ):
        try:
            config.normalize_subhd_base_url(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"必须拒绝不安全或不受支持的 SubHD 服务地址：{value}")
