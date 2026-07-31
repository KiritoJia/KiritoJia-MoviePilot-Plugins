"""外部字幕源健康检查的安全错误诊断测试。"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace


class DummyCache:
    def __init__(self, **_kwargs: object) -> None:
        pass

    async def clear(self, **_kwargs: object) -> None:
        pass

    async def close(self) -> None:
        pass


class DummyLogger:
    def __getattr__(self, _name: str):
        return lambda *_args, **_kwargs: None


class FakeLimiter:
    def __init__(self) -> None:
        self.acquire_calls: list[bool] = []

    async def acquire(self, wait: bool) -> None:
        self.acquire_calls.append(wait)

    async def reset(self) -> None:
        pass


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers: dict[str, str] = {}
        self.is_closed = False

    def json(self) -> dict[str, object]:
        return self._payload

    async def aclose(self) -> None:
        self.is_closed = True


class FakeRequest:
    response: FakeResponse | None = None
    error: Exception | None = None
    responses: list[FakeResponse | None] = []
    proxy_attempts: list[dict[str, str]] = []

    def __init__(self, **kwargs: object) -> None:
        proxies = kwargs.get("proxies")
        self.proxy_attempts.append(dict(proxies) if isinstance(proxies, dict) else {})

    @classmethod
    def next_response(cls) -> FakeResponse | None:
        if cls.responses:
            return cls.responses.pop(0)
        return cls.response

    async def post_res(self, *_args: object, **_kwargs: object) -> FakeResponse | None:
        if self.error is not None:
            raise self.error
        return self.next_response()

    async def get_res(self, *_args: object, **_kwargs: object) -> FakeResponse | None:
        if self.error is not None:
            raise self.error
        return self.next_response()


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


def _load_sources() -> tuple[types.ModuleType, types.ModuleType]:
    root = Path(__file__).resolve().parents[1]
    package = "subtitledownloadassistant_source_test"

    _module("app").__path__ = []
    _module("app.core").__path__ = []
    _module("app.core.cache", AsyncMemoryBackend=DummyCache)
    _module("app.core.config", settings=SimpleNamespace(PROXY=None))
    _module("app.log", logger=DummyLogger())
    _module("app.utils").__path__ = []
    _module("app.utils.http", AsyncRequestUtils=FakeRequest)
    _module("anyio", Path=Path)

    package_module = _module(package)
    package_module.__path__ = [str(root)]
    for suffix in ("domain", "application", "sources"):
        module = _module(f"{package}.{suffix}")
        module.__path__ = [str(root / suffix)]

    for suffix in (
        "domain.enums",
        "domain.models",
        "domain.language",
        "domain.query",
        "application.ports",
        "sources.common",
        "sources.limiter",
    ):
        _load_module(f"{package}.{suffix}", root / (suffix.replace(".", "/") + ".py"))
    opensubtitles = _load_module(
        f"{package}.sources.opensubtitles",
        root / "sources/opensubtitles.py",
    )
    assrt = _load_module(f"{package}.sources.assrt", root / "sources/assrt.py")
    opensubtitles.AsyncRequestUtils = FakeRequest
    assrt.AsyncRequestUtils = FakeRequest
    return opensubtitles, assrt


def test_source_refresh_diagnostics() -> None:
    opensubtitles, assrt = _load_sources()

    async def run() -> None:
        os_limiter = FakeLimiter()
        os_source = opensubtitles.OpenSubtitlesSource(
            enabled=True,
            credentials={"api_key": "test", "username": "test", "password": "test"},
            allowed_formats={"SRT"},
            limiter=os_limiter,
        )
        FakeRequest.error = None
        FakeRequest.responses = []
        FakeRequest.proxy_attempts = []
        FakeRequest.response = FakeResponse(401, {"status": 401})
        os_status = await os_source.refresh()
        assert os_status.last_error_summary == (
            "OpenSubtitles 用户名或密码无效（必须使用用户名，不能使用邮箱；HTTP 401）"
        )

        FakeRequest.response = None
        FakeRequest.error = OSError("secret network detail")
        os_network_status = await os_source.refresh()
        assert os_network_status.last_error_summary == "OpenSubtitles 登录请求失败（直连均无响应）"
        assert "secret" not in os_network_status.last_error_summary

        assrt_source = assrt.AssrtSource(
            enabled=True,
            credentials={"token": "test"},
            allowed_formats={"ASS"},
        )
        FakeRequest.error = None
        FakeRequest.responses = []
        FakeRequest.response = FakeResponse(401, {"status": 401})
        assrt_auth_status = await assrt_source.refresh(manual=True)
        assert assrt_auth_status.last_error_summary == "ASSRT Token 无效或无权限（HTTP 401）"

        FakeRequest.response = FakeResponse(200, {"status": 10001})
        assrt_api_status = await assrt_source.refresh(manual=True)
        assert assrt_api_status.last_error_summary == "ASSRT 返回错误状态 10001"

        FakeRequest.response = FakeResponse(200, {"status": 0, "user": {"quota": 4}})
        assrt_ok_status = await assrt_source.refresh(manual=True)
        assert assrt_ok_status.health.value == "healthy"
        assert assrt_ok_status.details["quota"] == 4

        opensubtitles.settings.PROXY = {"https": "http://proxy.invalid:7890"}
        FakeRequest.response = None
        FakeRequest.responses = [None, FakeResponse(200, {"token": "session"})]
        FakeRequest.proxy_attempts = []
        os_fallback_status = await os_source.refresh()
        assert os_fallback_status.health.value == "healthy"
        assert os_fallback_status.details["transport"] == "直连"
        assert os_fallback_status.details["proxy_fallback"] is True
        assert FakeRequest.proxy_attempts == [
            {"https": "http://proxy.invalid:7890"},
            {},
        ]

        FakeRequest.responses = [None, None]
        FakeRequest.proxy_attempts = []
        os_unreachable_status = await os_source.refresh()
        assert os_unreachable_status.last_error_summary == "OpenSubtitles 登录请求失败（代理、直连均无响应）"
        assert os_unreachable_status.details["transport_attempts"] == ["代理", "直连"]
        assert os_limiter.acquire_calls == [True, True, True, True]

    asyncio.run(run())
