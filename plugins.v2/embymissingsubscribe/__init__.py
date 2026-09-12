"""Emby 缺集自动订阅（MoviePilot V3）。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

import requests
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from app.application.configuration import get_chain_runtime_config_snapshot
from app.chain.subscribe.facade import SubscribeChain
from app.chain.tmdb import TmdbChain
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import MediaSource, MediaType


class EmbyMissingSubscribe(_PluginBase):
    """读取 Emby 电视剧缺集并创建 MoviePilot 季订阅。"""

    plugin_name = "Emby缺集自动订阅"
    plugin_desc = "扫描 Emby 媒体库，发现已播缺集后自动创建 MoviePilot 订阅"
    plugin_icon = "https://raw.githubusercontent.com/KiritoJia/KiritoJia-MoviePilot-Plugins/main/icons/EmbyMissingSubscribe.svg"
    plugin_version = "1.0.1"
    plugin_author = "KiritoJia"
    author_url = "https://github.com/KiritoJia"
    plugin_config_prefix = "embymissingsubscribe_"
    plugin_order = 46
    auth_level = 1

    def __init__(self) -> None:
        super().__init__()
        self._enabled = False
        self._onlyonce = False
        self._emby_url = ""
        self._user_id = ""
        self._api_key = ""
        self._cron = "0 */6 * * *"
        self._aired_only = True
        self._timeout = 20
        self._last_summary: dict[str, Any] = {}
        self._scan_lock = Lock()
        self._state_file = self.get_data_path() / "scan_state.json"

    def init_plugin(self, config: dict | None = None) -> None:
        config = config or {}
        self.stop_service()
        self._enabled = bool(config.get("enabled", False))
        self._onlyonce = bool(config.get("onlyonce", False))
        self._emby_url = str(config.get("emby_url", "") or "").strip().rstrip("/")
        self._user_id = str(config.get("user_id", "") or "").strip()
        self._api_key = str(config.get("api_key", "") or "").strip()
        self._cron = str(config.get("cron", "0 */6 * * *") or "0 */6 * * *").strip()
        self._aired_only = bool(config.get("aired_only", True))
        try:
            self._timeout = max(5, min(120, int(config.get("timeout", 20))))
        except (TypeError, ValueError):
            self._timeout = 20
        self._last_summary = self._load_state()
        if self._enabled and not self._ready():
            logger.warning("[Emby缺集自动订阅] 配置不完整，插件未启动")
            self._enabled = False
            self.__update_config()

    def get_state(self) -> bool:
        return self._enabled

    def get_command(self) -> list[dict[str, Any]]:
        return []

    def get_api(self) -> list[dict[str, Any]]:
        return [{
            "path": "/scan",
            "endpoint": self.scan_library,
            "methods": ["GET"],
            "summary": "立即扫描 Emby 缺集",
        }, {
            "path": "/summary",
            "endpoint": self.get_summary,
            "methods": ["GET"],
            "summary": "获取 Emby 缺集扫描状态",
        }]

    def get_summary(self) -> dict[str, Any]:
        return self._last_summary or {"success": True, "message": "尚未执行扫描"}

    def get_page(self) -> list[dict[str, Any]]:
        if not self._last_summary:
            return [{"component": "VAlert", "props": {"type": "info", "text": "尚未执行扫描"}}]
        return [{
            "component": "VAlert",
            "props": {
                "type": "info",
                "variant": "tonal",
                "text": (
                    f"上次扫描：{self._last_summary.get('finished_at', '未执行')}；"
                    f"剧集 {self._last_summary.get('series', 0)} 部；"
                    f"发现缺集 {self._last_summary.get('missing', 0)} 集；"
                    f"新增订阅 {self._last_summary.get('subscriptions', 0)} 个；"
                    f"已有订阅 {self._last_summary.get('existing_subscriptions', 0)} 个"
                ),
            },
        }]

    def get_form(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return [{
            "component": "VForm",
            "content": [
                {"component": "VSwitch", "props": {"model": "enabled", "label": "启用插件"}},
                {"component": "VSwitch", "props": {"model": "onlyonce", "label": "保存后立即扫描一次"}},
                {"component": "VSwitch", "props": {"model": "aired_only", "label": "只订阅已播缺集"}},
                {"component": "VTextField", "props": {"model": "emby_url", "label": "Emby 地址", "hint": "例如 http://192.168.1.20:8096", "persistent-hint": True}},
                {"component": "VTextField", "props": {"model": "user_id", "label": "Emby 用户 ID", "hint": "填写 Emby 用户 UUID", "persistent-hint": True}},
                {"component": "VTextField", "props": {"model": "api_key", "label": "Emby API Key", "type": "password"}},
                {"component": "VCronField", "props": {"model": "cron", "label": "扫描周期", "placeholder": "0 */6 * * *"}},
            ],
        }], {
            "enabled": False,
            "onlyonce": False,
            "emby_url": "",
            "user_id": "",
            "api_key": "",
            "cron": "0 */6 * * *",
            "aired_only": True,
            "timeout": 20,
        }

    def get_service(self) -> list[dict[str, Any]]:
        if not self._ready():
            return []
        services: list[dict[str, Any]] = []
        if self._onlyonce:
            services.append({
                "id": "EmbyMissingSubscribeScanOnce",
                "name": "Emby缺集立即扫描",
                "trigger": DateTrigger(run_date=datetime.now() + timedelta(seconds=3)),
                "func": self._scan_once,
                "kwargs": {},
            })
        if self._enabled and self._cron:
            try:
                services.append({
                    "id": "EmbyMissingSubscribeScan",
                    "name": "Emby缺集自动订阅扫描",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "func": self.scan_library,
                    "kwargs": {},
                })
            except ValueError as exc:
                logger.error(f"[Emby缺集自动订阅] cron 配置无效：{exc}")
        return services

    def stop_service(self) -> None:
        return None

    def _scan_once(self) -> dict[str, Any]:
        try:
            return self.scan_library(force=True)
        finally:
            self._onlyonce = False
            self.__update_config()

    def scan_library(self, force: bool = False) -> dict[str, Any]:
        if not self._ready():
            return {"success": False, "message": "Emby 配置不完整"}
        if not self._scan_lock.acquire(blocking=False):
            return {"success": False, "message": "扫描任务正在运行"}
        session = requests.Session()
        try:
            series_items = self._request_json(
                session,
                f"{self._emby_url}/Users/{self._user_id}/Items",
                {
                    "UserId": self._user_id,
                    "IncludeItemTypes": "Series",
                    "Recursive": "true",
                    "Fields": "ProviderIds,ProductionYear,ChildCount",
                    "StartIndex": 0,
                    "Limit": 10000,
                    "SortBy": "SortName",
                    "SortOrder": "Ascending",
                },
            ).get("Items", [])
            summary = {
                "success": True,
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "series": len(series_items),
                "missing": 0,
                "subscriptions": 0,
                "existing_subscriptions": 0,
                "subscribe_failures": 0,
                "skipped": 0,
                "missing_by_key": {},
                "handled_by_key": dict(self._last_summary.get("handled_by_key", {})),
            }
            for series in series_items:
                try:
                    summary["missing"] += self._scan_series(session, series, summary, force=force)
                except Exception as exc:  # noqa: BLE001
                    summary["skipped"] += 1
                    logger.warning(f"[Emby缺集自动订阅] 扫描 {series.get('Name', '未知剧集')} 失败：{exc}")
            self._last_summary = summary
            self._save_state(summary)
            logger.info(
                f"[Emby缺集自动订阅] 扫描完成：剧集 {summary['series']} 部，"
                f"缺集 {summary['missing']} 集，新增订阅 {summary['subscriptions']} 个"
            )
            return summary
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[Emby缺集自动订阅] 扫描失败：{exc}")
            return {"success": False, "message": str(exc)}
        finally:
            session.close()
            self._scan_lock.release()

    def _scan_series(self, session: requests.Session, series: dict[str, Any], summary: dict[str, Any], *, force: bool) -> int:
        provider_ids = {str(k).lower(): str(v) for k, v in (series.get("ProviderIds") or {}).items()}
        tmdb_id = provider_ids.get("tmdb") or provider_ids.get("themoviedb")
        if not tmdb_id or not tmdb_id.isdigit():
            return 0
        seasons = self._request_json(session, f"{self._emby_url}/Shows/{series['Id']}/Seasons", {
            "UserId": self._user_id,
            "Fields": "ProviderIds,ChildCount,IndexNumber,Name",
            "Limit": 1000,
        }).get("Items", [])
        total_missing = 0
        for season_item in seasons:
            season_number = season_item.get("IndexNumber")
            if not isinstance(season_number, int) or season_number <= 0:
                continue
            episodes = self._request_json(session, f"{self._emby_url}/Shows/{series['Id']}/Episodes", {
                "UserId": self._user_id,
                "SeasonId": season_item.get("Id"),
                "Fields": "IndexNumber,ParentIndexNumber,PremiereDate,ProviderIds",
                "IsVirtualUnaired": "false",
                "Limit": 1000,
            }).get("Items", [])
            existing = {item["IndexNumber"] for item in episodes if isinstance(item.get("IndexNumber"), int) and item["IndexNumber"] > 0}
            details = self._expected_episodes(int(tmdb_id), season_number)
            expected = self._aired_episode_numbers(details) if self._aired_only else self._episode_numbers(details)
            missing = sorted(expected - existing)
            key = f"{tmdb_id}:S{season_number}"
            if not missing:
                summary["handled_by_key"].pop(key, None)
                continue
            total_missing += len(missing)
            summary["missing_by_key"][key] = missing
            if not force and summary["handled_by_key"].get(key) == missing:
                continue
            sid, message = self._subscribe(series, int(tmdb_id), season_number, total_episode=len(self._episode_numbers(details)), lack_episode=len(missing))
            if sid:
                summary["handled_by_key"][key] = missing
                if "已存在" in str(message):
                    summary["existing_subscriptions"] += 1
                else:
                    summary["subscriptions"] += 1
                logger.info(f"[Emby缺集自动订阅] {series.get('Name')} S{season_number:02d} 缺失 {missing}，{message}（ID: {sid}）")
            else:
                summary["subscribe_failures"] += 1
                logger.warning(f"[Emby缺集自动订阅] {series.get('Name')} S{season_number:02d} 订阅失败：{message}")
        return total_missing

    @staticmethod
    def _episode_numbers(episodes: list[Any]) -> set[int]:
        return {number for episode in episodes if isinstance((number := getattr(episode, "episode_number", None)), int) and number > 0}

    @staticmethod
    def _aired_episode_numbers(episodes: list[Any]) -> set[int]:
        today = date.today()
        result: set[int] = set()
        for episode in episodes:
            number = getattr(episode, "episode_number", None)
            air_date = getattr(episode, "air_date", None)
            if not isinstance(number, int) or not air_date:
                continue
            try:
                if date.fromisoformat(str(air_date)[:10]) <= today:
                    result.add(number)
            except ValueError:
                continue
        return result

    @staticmethod
    def _expected_episodes(tmdb_id: int, season: int) -> list[Any]:
        return TmdbChain().tmdb_episodes(tmdb_id, season) or []

    def _subscribe(self, series: dict[str, Any], tmdb_id: int, season: int, *, total_episode: int, lack_episode: int) -> tuple[Any, str]:
        username = get_chain_runtime_config_snapshot().superuser
        return SubscribeChain().add(
            title=str(series.get("Name") or "").strip(),
            year=str(series.get("ProductionYear") or ""),
            mtype=MediaType.TV,
            season=season,
            media_source=MediaSource.TMDB,
            media_id=str(tmdb_id),
            username=username,
            message=False,
            exist_ok=True,
            total_episode=total_episode,
            lack_episode=lack_episode,
        )

    def _request_json(self, session: requests.Session, url: str, params: dict[str, Any]) -> dict[str, Any]:
        request_params = dict(params)
        request_params["api_key"] = self._api_key
        response = session.get(url, params=request_params, timeout=self._timeout)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Emby 返回格式不是 JSON 对象")
        return payload

    def _ready(self) -> bool:
        return bool(self._emby_url and self._user_id and self._api_key)

    def _load_state(self) -> dict[str, Any]:
        try:
            if self._state_file.exists():
                value = json.loads(self._state_file.read_text(encoding="utf-8"))
                return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            pass
        return {}

    def _save_state(self, summary: dict[str, Any]) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    def __update_config(self) -> None:
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "emby_url": self._emby_url,
            "user_id": self._user_id,
            "api_key": self._api_key,
            "cron": self._cron,
            "aired_only": self._aired_only,
            "timeout": self._timeout,
        })
