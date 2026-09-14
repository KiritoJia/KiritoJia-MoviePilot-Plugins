"""Emby 缺集自动订阅（MoviePilot V3）。"""

from __future__ import annotations

import json
import hashlib
import inspect
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urlencode

import requests
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from fastapi import Query, Request

try:
    from app.chain.subscribe.facade import SubscribeChain
except ImportError:
    # MoviePilot V2 exposes SubscribeChain from app.chain.subscribe.
    from app.chain.subscribe import SubscribeChain
from app.chain.tmdb import TmdbChain
from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import NotificationType
from app.schemas.types import MediaType


class KiritoEmbyMissingSubscribe(_PluginBase):
    """读取 Emby 电视剧缺集并创建 MoviePilot 季订阅。"""

    plugin_name = "Kirito Emby缺集自动订阅"
    plugin_desc = "扫描 Emby 媒体库，发现已播缺集后自动创建 MoviePilot 订阅"
    plugin_icon = "https://raw.githubusercontent.com/KiritoJia/KiritoJia-MoviePilot-Plugins/main/icons/KiritoEmbyMissingSubscribe.svg"
    plugin_version = "1.0.14"
    plugin_author = "KiritoJia"
    author_url = "https://github.com/KiritoJia/KiritoJia-MoviePilot-Plugins"
    plugin_config_prefix = "kiritoembymissingsubscribe_"
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
        self._notify_enabled = True
        self._notify_on_start = False
        self._notify_on_complete = True
        self._notify_new = True
        self._notify_existing = False
        self._notify_failure = True
        self._notify_only_changes = True
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
        self._notify_enabled = bool(config.get("notify_enabled", True))
        self._notify_on_start = bool(config.get("notify_on_start", False))
        self._notify_on_complete = bool(config.get("notify_on_complete", True))
        self._notify_new = bool(config.get("notify_new", True))
        self._notify_existing = bool(config.get("notify_existing", False))
        self._notify_failure = bool(config.get("notify_failure", True))
        self._notify_only_changes = bool(config.get("notify_only_changes", True))
        try:
            self._timeout = max(5, min(120, int(config.get("timeout", 20))))
        except (TypeError, ValueError):
            self._timeout = 20
        self._last_summary = self._load_state()
        if self._enabled and not self._ready():
            logger.warning("[Kirito Emby缺集自动订阅] 配置不完整，插件未启动")
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
            "auth": "bear",
            "summary": "立即扫描 Emby 缺集",
        }, {
            "path": "/summary",
            "endpoint": self.get_summary,
            "methods": ["GET"],
            "auth": "bear",
            "summary": "获取 Emby 缺集扫描状态",
        }, {
            "path": "/config",
            "endpoint": self.get_frontend_config,
            "methods": ["GET"],
            "auth": "bear",
            "summary": "获取 Emby 缺集订阅配置",
        }, {
            "path": "/config",
            "endpoint": self.save_frontend_config,
            "methods": ["POST"],
            "auth": "bear",
            "summary": "保存 Emby 缺集订阅配置",
        }, {
            "path": "/test-notify",
            "endpoint": self.test_notification,
            "methods": ["POST"],
            "auth": "bear",
            "summary": "测试 Emby 缺集订阅通知",
        }]

    def get_sidebar_nav(self) -> list[dict[str, Any]]:
        """注册主界面全页入口，使用前端 AppPage 组件。"""
        if not self.get_state():
            return []
        return [{
            "nav_key": "main",
            "title": "Emby缺集订阅",
            "icon": "mdi-television-guide",
            "section": "subscribe",
            "permission": "manage",
            "order": 46,
        }]

    def get_render_mode(self) -> tuple[str, str]:
        """使用前端联邦组件渲染配置页。"""
        return "vue", "frontend/dist/assets"

    def get_form(self) -> tuple[None, dict[str, Any]]:
        """Vue 配置页使用第二项作为初始配置数据。"""
        return None, {
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "emby_url": self._emby_url,
            "user_id": self._user_id,
            "api_key": self._api_key,
            "cron": self._cron,
            "aired_only": self._aired_only,
            "timeout": self._timeout,
            "notify_enabled": self._notify_enabled,
            "notify_on_start": self._notify_on_start,
            "notify_on_complete": self._notify_on_complete,
            "notify_new": self._notify_new,
            "notify_existing": self._notify_existing,
            "notify_failure": self._notify_failure,
            "notify_only_changes": self._notify_only_changes,
        }

    def get_frontend_config(self) -> dict[str, Any]:
        """返回全页 Vue 入口所需的配置。"""
        return {
            "plugin_id": self.__class__.__name__,
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "emby_url": self._emby_url,
            "user_id": self._user_id,
            "api_key": self._api_key,
            "cron": self._cron,
            "aired_only": self._aired_only,
            "timeout": self._timeout,
            "notify_enabled": self._notify_enabled,
            "notify_on_start": self._notify_on_start,
            "notify_on_complete": self._notify_on_complete,
            "notify_new": self._notify_new,
            "notify_existing": self._notify_existing,
            "notify_failure": self._notify_failure,
            "notify_only_changes": self._notify_only_changes,
        }

    async def save_frontend_config(self, request: Request) -> dict[str, Any]:
        """接收全页 Vue 入口保存的配置并重新装载插件。"""
        incoming = await request.json()
        if not isinstance(incoming, dict):
            incoming = {}
        current = self.get_frontend_config()
        current.update({key: value for key, value in incoming.items() if key in {
            "enabled", "onlyonce", "emby_url", "user_id", "api_key", "cron", "aired_only", "timeout",
            "notify_enabled", "notify_on_start", "notify_on_complete", "notify_new", "notify_existing",
            "notify_failure", "notify_only_changes",
        }})
        self.update_config(current)
        self.init_plugin(current)
        return {"success": True, "message": "配置已保存", **self.get_frontend_config()}

    def test_notification(self) -> dict[str, Any]:
        """通过 MoviePilot 全局通知渠道发送一条不含敏感信息的测试消息。"""
        try:
            self.post_message(
                mtype=NotificationType.Plugin,
                title="【Emby缺集自动订阅】测试通知",
                text="通知渠道测试成功。后续扫描结果会按插件中的通知设置发送。",
            )
            return {"success": True, "message": "测试通知已提交"}
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[Kirito Emby缺集自动订阅] 测试通知失败：{exc}", exc_info=True)
            return {"success": False, "message": f"测试通知失败：{exc}"}

    def get_summary(
        self,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=10, ge=10, le=100),
    ) -> dict[str, Any]:
        if not self._last_summary:
            return {"success": True, "message": "尚未执行扫描"}
        result = dict(self._last_summary)
        all_history = list(self._last_summary.get("subscription_history", []))
        total = len(all_history)
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, total_pages)
        start = (page - 1) * page_size
        result["subscription_history"] = [
            {**item, "poster": self._history_poster(item)}
            for item in all_history[start : start + page_size]
        ]
        result["subscription_history_total"] = total
        result["subscription_history_page"] = page
        result["subscription_history_page_size"] = page_size
        result["subscription_history_total_pages"] = total_pages
        return result

    def get_page(self) -> None:
        """Vue 配置页不使用 MoviePilot 原生页面定义。"""
        return None

    def get_service(self) -> list[dict[str, Any]]:
        if not self._ready():
            return []
        services: list[dict[str, Any]] = []
        if self._onlyonce:
            services.append({
                "id": "KiritoEmbyMissingSubscribeScanOnce",
                "name": "Emby缺集立即扫描",
                "trigger": DateTrigger(run_date=datetime.now() + timedelta(seconds=3)),
                "func": self._scan_once,
                "kwargs": {},
            })
        if self._enabled and self._cron:
            try:
                services.append({
                    "id": "KiritoEmbyMissingSubscribeScan",
                    "name": "Kirito Emby缺集自动订阅扫描",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "func": self.scan_library,
                    "kwargs": {},
                })
            except ValueError as exc:
                logger.error(f"[Kirito Emby缺集自动订阅] cron 配置无效：{exc}")
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
            if self._notify_enabled and self._notify_on_start:
                self._send_notification(
                    "【Emby缺集自动订阅】开始扫描",
                    "正在读取 Emby 媒体库并检查已播缺集，请稍候。",
                )
            series_items = self._request_json(
                session,
                f"{self._emby_url}/Users/{self._user_id}/Items",
                {
                    "UserId": self._user_id,
                    "IncludeItemTypes": "Series",
                    "Recursive": "true",
                    "Fields": "ProviderIds,ProductionYear,ChildCount,ImageTags",
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
                "subscription_history": list(self._last_summary.get("subscription_history", []))[:500],
                "new_subscriptions": [],
                "existing_subscription_details": [],
                "failure_details": [],
                "notification_fingerprints": list(self._last_summary.get("notification_fingerprints", []))[-100:],
            }
            for series in series_items:
                try:
                    summary["missing"] += self._scan_series(session, series, summary, force=force)
                except Exception as exc:  # noqa: BLE001
                    summary["skipped"] += 1
                    logger.warning(f"[Kirito Emby缺集自动订阅] 扫描 {series.get('Name', '未知剧集')} 失败：{exc}")
            self._last_summary = summary
            self._send_scan_notifications(summary)
            self._save_state(summary)
            logger.info(
                f"[Kirito Emby缺集自动订阅] 扫描完成：剧集 {summary['series']} 部，"
                f"缺集 {summary['missing']} 集，新增订阅 {summary['subscriptions']} 个"
            )
            return summary
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[Kirito Emby缺集自动订阅] 扫描失败：{exc}")
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
                    summary["existing_subscription_details"].append(
                        self._subscription_detail(series, season_number, missing, key, "已复用")
                    )
                else:
                    summary["subscriptions"] += 1
                    summary["new_subscriptions"].append(
                        self._subscription_detail(series, season_number, missing, key, "已创建")
                    )
                self._record_subscription(summary, key, series, season_number, missing, message)
                logger.info(f"[Kirito Emby缺集自动订阅] {series.get('Name')} S{season_number:02d} 缺失 {missing}，{message}（ID: {sid}）")
            else:
                summary["subscribe_failures"] += 1
                summary["failure_details"].append({
                    "key": key,
                    "name": str(series.get("Name") or "未知剧集"),
                    "season": season_number,
                    "missing": missing,
                    "error": str(message),
                })
                logger.warning(f"[Kirito Emby缺集自动订阅] {series.get('Name')} S{season_number:02d} 订阅失败：{message}")
        return total_missing

    def _record_subscription(
        self,
        summary: dict[str, Any],
        key: str,
        series: dict[str, Any],
        season: int,
        missing: list[int],
        message: str,
    ) -> None:
        """保留最近订阅对象，供详情页展示并跨重启保留。"""
        image_tag = str((series.get("ImageTags") or {}).get("Primary") or "")
        history = [item for item in summary.get("subscription_history", []) if item.get("key") != key]
        history.insert(0, {
            "key": key,
            "name": str(series.get("Name") or "未知剧集"),
            "year": str(series.get("ProductionYear") or ""),
            "season": season,
            "missing": missing,
            "item_id": str(series.get("Id") or ""),
            "image_tag": image_tag,
            "status": "已存在" if "已存在" in str(message) else "已创建",
            "updated_at": summary.get("finished_at", ""),
        })
        summary["subscription_history"] = history[:500]

    @staticmethod
    def _subscription_detail(
        series: dict[str, Any], season: int, missing: list[int], key: str, status: str
    ) -> dict[str, Any]:
        return {
            "key": key,
            "name": str(series.get("Name") or "未知剧集"),
            "year": str(series.get("ProductionYear") or ""),
            "season": season,
            "missing": list(missing),
            "status": status,
        }

    def _send_scan_notifications(self, summary: dict[str, Any]) -> None:
        if not self._notify_enabled:
            return
        new_items = summary.get("new_subscriptions", []) if self._notify_new else []
        existing_items = summary.get("existing_subscription_details", []) if self._notify_existing else []
        failures = summary.get("failure_details", []) if self._notify_failure else []
        has_changes = bool(new_items or existing_items or failures)
        if not self._notify_on_complete:
            if failures:
                failure_text = "\n".join(
                    f"- {item.get('name', '未知剧集')} S{int(item.get('season', 0)):02d}：{item.get('error', '未知错误')}"
                    for item in failures
                )
                text = "本次扫描有订阅创建失败：\n" + failure_text
                fingerprint = self._notification_fingerprint("failure", text)
                if fingerprint not in summary.get("notification_fingerprints", []) and self._send_notification(
                    "【Emby缺集自动订阅】订阅失败", text
                ):
                    self._remember_notification(summary, fingerprint)
            return
        if self._notify_only_changes and not has_changes:
            return

        sections = [
            f"扫描完成：剧集 {summary.get('series', 0)} 部，发现缺集 {summary.get('missing', 0)} 集。",
            f"新增订阅 {summary.get('subscriptions', 0)} 个，复用订阅 {summary.get('existing_subscriptions', 0)} 个，失败 {summary.get('subscribe_failures', 0)} 个。",
        ]
        if new_items:
            sections.append("\n新建订阅：\n" + self._format_subscription_details(new_items))
        if existing_items:
            sections.append("\n复用已有订阅：\n" + self._format_subscription_details(existing_items))
        if failures:
            sections.append("\n订阅失败：\n" + "\n".join(
                f"- {item.get('name', '未知剧集')} S{int(item.get('season', 0)):02d}：{item.get('error', '未知错误')}"
                for item in failures
            ))
        text = "\n".join(sections)
        fingerprint = self._notification_fingerprint("scan", text)
        if fingerprint in summary.get("notification_fingerprints", []):
            return
        if self._send_notification("【Emby缺集自动订阅】扫描结果", text):
            self._remember_notification(summary, fingerprint)

    @staticmethod
    def _format_subscription_details(items: list[dict[str, Any]]) -> str:
        return "\n".join(
            f"- {item.get('name', '未知剧集')} S{int(item.get('season', 0)):02d}：{KiritoEmbyMissingSubscribe._format_missing(item.get('missing'))}"
            for item in items
        )

    @staticmethod
    def _format_missing(missing: Any) -> str:
        values = missing if isinstance(missing, list) else []
        return "、".join(f"E{int(value):02d}" for value in values) or "缺集信息未知"

    @staticmethod
    def _notification_fingerprint(kind: str, text: str) -> str:
        return hashlib.sha256(f"{kind}\n{text}".encode("utf-8")).hexdigest()

    @staticmethod
    def _remember_notification(summary: dict[str, Any], fingerprint: str) -> bool:
        fingerprints = summary.setdefault("notification_fingerprints", [])
        if fingerprint in fingerprints:
            return False
        fingerprints.append(fingerprint)
        del fingerprints[:-100]
        return True

    def _send_notification(self, title: str, text: str) -> bool:
        try:
            self.post_message(mtype=NotificationType.Plugin, title=title, text=text)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[Kirito Emby缺集自动订阅] 发送通知失败：{exc}", exc_info=True)
            return False

    def _history_poster(self, item: dict[str, Any]) -> str:
        item_id = str(item.get("item_id") or "").strip()
        image_tag = str(item.get("image_tag") or "").strip()
        if not item_id or not self._emby_url:
            return ""
        params = {"fillWidth": 240, "quality": 82, "api_key": self._api_key}
        if image_tag:
            params["tag"] = image_tag
        return f"{self._emby_url}/Items/{item_id}/Images/Primary?{urlencode(params)}"

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
        username = getattr(settings, "SUPERUSER", "") or "admin"
        add = SubscribeChain().add
        params = inspect.signature(add).parameters
        kwargs: dict[str, Any] = {
            "title": str(series.get("Name") or "").strip(),
            "year": str(series.get("ProductionYear") or ""),
            "mtype": MediaType.TV,
            "season": season,
            "username": username,
            # 交给 MoviePilot 原生订阅通知链路发送“订阅已添加”消息。
            "message": True,
            "exist_ok": True,
            "total_episode": total_episode,
            "lack_episode": lack_episode,
        }
        if "tmdbid" in params:
            kwargs["tmdbid"] = str(tmdb_id)
        elif "media_source" in params and "media_id" in params:
            kwargs["media_source"] = "themoviedb"
            kwargs["media_id"] = str(tmdb_id)
        else:
            raise RuntimeError("当前 MoviePilot 订阅接口不支持 TMDB 媒体标识参数")
        return add(**kwargs)

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
            "notify_enabled": self._notify_enabled,
            "notify_on_start": self._notify_on_start,
            "notify_on_complete": self._notify_on_complete,
            "notify_new": self._notify_new,
            "notify_existing": self._notify_existing,
            "notify_failure": self._notify_failure,
            "notify_only_changes": self._notify_only_changes,
        })
