"""插件非敏感配置解析与公开模型。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from ..domain.enums import PackageAttributionStrategy, SubtitleSource
from ..domain.language import normalize_format_priority
from .path_mapping import PathMapping, validate_path_mappings

DEFAULT_SUBHD_BASE_URL = "https://subhd.tv"


def normalize_subhd_base_url(value: Any) -> str:
    """校验 SubHD 官方站、镜像或反向代理的服务根地址。"""

    text = str(value or DEFAULT_SUBHD_BASE_URL).strip().rstrip("/")
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("SubHD 服务地址必须是完整的 HTTP 或 HTTPS 网址")
    if parsed.username or parsed.password:
        raise ValueError("SubHD 服务地址不能包含用户名或密码")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("SubHD 服务地址只能填写协议、域名和可选端口")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("SubHD 服务地址端口无效") from exc
    return text


def normalize_custom_media_directories(values: Any) -> tuple[str, ...]:
    """校验并规范化用于定位本地媒体或 STRM 的根目录。"""

    if values in (None, ""):
        return ()
    if isinstance(values, str):
        values = values.splitlines()
    if not isinstance(values, (list, tuple)):
        raise ValueError("自定义媒体目录必须是路径列表")
    result: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(values):
        path = str(value or "").strip()
        if not path:
            continue
        if not os.path.isabs(path):
            raise ValueError(f"第 {index + 1} 个自定义媒体目录必须是绝对路径")
        if "*" in path or "?" in path:
            raise ValueError(f"第 {index + 1} 个自定义媒体目录不支持通配符")
        normalized = os.path.normpath(path)
        key = os.path.normcase(normalized)
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return tuple(result)


@dataclass(slots=True)
class PluginConfig:
    """字幕下载助手运行所需的非敏感配置。"""

    enabled: bool = False
    moviepilot_enabled: bool = True
    opensubtitles_enabled: bool = False
    assrt_enabled: bool = False
    shooter_enabled: bool = False
    thunder_enabled: bool = False
    subhd_enabled: bool = False
    subhd_base_url: str = DEFAULT_SUBHD_BASE_URL
    allow_machine_translation: bool = False
    max_concurrent_tasks: int = 2
    max_candidate_attempts: int = 3
    source_priority: list[str] = field(
        default_factory=lambda: ["shooter", "thunder", "moviepilot", "assrt", "opensubtitles", "subhd"]
    )
    format_priority: list[str] = field(default_factory=list)
    path_mappings: tuple[PathMapping, ...] = field(default_factory=tuple)
    custom_media_directories: tuple[str, ...] = field(default_factory=tuple)
    directory_monitor_enabled: bool = True
    directory_monitor_interval: int = 60
    package_attribution_strategy: PackageAttributionStrategy = PackageAttributionStrategy.TRUST_PACKAGE
    # 字幕归属 AI 接管是独立授权，默认关闭；宿主 AI 总开关在运行时再复核。
    ai_attribution_takeover_enabled: bool = False

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None, allowed_formats: list[str]) -> PluginConfig:
        """从宿主配置解析并归一化运行配置。"""

        values = raw or {}
        source_order: list[str] = []
        for item in values.get("source_priority") or [
            "shooter",
            "thunder",
            "moviepilot",
            "assrt",
            "opensubtitles",
            "subhd",
        ]:
            normalized = str(item).strip().lower()
            if normalized in {source.value for source in SubtitleSource} and normalized not in source_order:
                source_order.append(normalized)
        source_order.extend(source.value for source in SubtitleSource if source.value not in source_order)
        try:
            concurrent_tasks = int(values.get("max_concurrent_tasks", 2))
        except (TypeError, ValueError):
            concurrent_tasks = 2
        try:
            attempts = int(values.get("max_candidate_attempts", 3))
        except (TypeError, ValueError):
            attempts = 3
        try:
            monitor_interval = int(values.get("directory_monitor_interval", 60))
        except (TypeError, ValueError):
            monitor_interval = 60
        strategy = PackageAttributionStrategy(
            str(
                values.get(
                    "package_attribution_strategy",
                    PackageAttributionStrategy.TRUST_PACKAGE.value,
                )
            )
        )
        return cls(
            enabled=bool(values.get("enabled", False)),
            moviepilot_enabled=bool(values.get("moviepilot_enabled", True)),
            opensubtitles_enabled=bool(values.get("opensubtitles_enabled", False)),
            assrt_enabled=bool(values.get("assrt_enabled", False)),
            shooter_enabled=bool(values.get("shooter_enabled", False)),
            thunder_enabled=bool(values.get("thunder_enabled", False)),
            subhd_enabled=bool(values.get("subhd_enabled", False)),
            subhd_base_url=normalize_subhd_base_url(values.get("subhd_base_url")),
            allow_machine_translation=bool(values.get("allow_machine_translation", False)),
            max_concurrent_tasks=min(4, max(1, concurrent_tasks)),
            max_candidate_attempts=min(10, max(1, attempts)),
            source_priority=source_order,
            format_priority=normalize_format_priority(allowed_formats, values.get("format_priority")),
            path_mappings=validate_path_mappings(values.get("path_mappings")),
            custom_media_directories=normalize_custom_media_directories(values.get("custom_media_directories")),
            directory_monitor_enabled=bool(values.get("directory_monitor_enabled", True)),
            directory_monitor_interval=min(3600, max(30, monitor_interval)),
            package_attribution_strategy=strategy,
            ai_attribution_takeover_enabled=bool(values.get("ai_attribution_takeover_enabled", False)),
        )

    def enabled_sources(self) -> dict[SubtitleSource, bool]:
        """返回全部来源的启用状态。"""

        return {
            SubtitleSource.MOVIEPILOT: self.moviepilot_enabled,
            SubtitleSource.OPENSUBTITLES: self.opensubtitles_enabled,
            SubtitleSource.ASSRT: self.assrt_enabled,
            SubtitleSource.SHOOTER: self.shooter_enabled,
            SubtitleSource.THUNDER: self.thunder_enabled,
            SubtitleSource.SUBHD: self.subhd_enabled,
        }

    def saved_payload(self) -> dict[str, Any]:
        """返回可以交给宿主保存的完整非敏感配置。"""

        return {
            "enabled": self.enabled,
            "moviepilot_enabled": self.moviepilot_enabled,
            "opensubtitles_enabled": self.opensubtitles_enabled,
            "assrt_enabled": self.assrt_enabled,
            "shooter_enabled": self.shooter_enabled,
            "thunder_enabled": self.thunder_enabled,
            "subhd_enabled": self.subhd_enabled,
            "subhd_base_url": self.subhd_base_url,
            "allow_machine_translation": self.allow_machine_translation,
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "max_candidate_attempts": self.max_candidate_attempts,
            "source_priority": list(self.source_priority),
            "format_priority": list(self.format_priority),
            "path_mappings": [mapping.as_dict() for mapping in self.path_mappings],
            "custom_media_directories": list(self.custom_media_directories),
            "directory_monitor_enabled": self.directory_monitor_enabled,
            "directory_monitor_interval": self.directory_monitor_interval,
            "package_attribution_strategy": self.package_attribution_strategy.value,
            "ai_attribution_takeover_enabled": self.ai_attribution_takeover_enabled,
        }

    def public_payload(
        self,
        plugin_id: str,
        allowed_formats: list[str],
        opensubtitles_configured: bool,
        assrt_configured: bool,
        subhd_configured: bool,
        host_ai_enabled: bool = False,
    ) -> dict[str, Any]:
        """返回 Vue Config 使用且不含秘密的初始模型。"""

        return {
            "plugin_id": plugin_id,
            **self.saved_payload(),
            "opensubtitles_configured": opensubtitles_configured,
            "assrt_configured": assrt_configured,
            "subhd_configured": subhd_configured,
            "host_ai_enabled": bool(host_ai_enabled),
            "allowed_formats": [str(item).lstrip(".").upper() for item in allowed_formats],
        }
