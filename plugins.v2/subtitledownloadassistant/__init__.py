"""MoviePilot 字幕下载助手插件入口。"""

from __future__ import annotations

import asyncio
import weakref
from pathlib import Path
from typing import Any

from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import global_vars, settings
from app.core.event import Event, eventmanager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import ChainEventType, EventType

from .api.router import ApiController
from .application.config import PluginConfig
from .application.inventory import SubtitleInventory
from .application.ports import SubtitleSourcePort
from .application.record_lock import ReentrantAsyncLock
from .application.retargeting import RetargetService
from .application.searches import ManualSearchService, TargetQueryService
from .application.source_gate import SourceConcurrencyGate
from .application.tasks import TaskCoordinator, TaskWorkItem, build_media_context
from .domain.enums import SourceHealth, SubtitleSource, TaskStatus, TaskTrigger
from .domain.models import SourceStatus
from .infrastructure.ai_attribution import AiAttributionAdapter
from .infrastructure.archive import ArchiveExtractor
from .infrastructure.filesystem import SubtitleFileSystem
from .infrastructure.matching import MoviePilotMatcher
from .infrastructure.store import PluginStore, StoreInitializationError
from .sources.assrt import AssrtSource
from .sources.fingerprint import MediaFingerprintService
from .sources.moviepilot import MoviePilotSource
from .sources.opensubtitles import OpenSubtitlesSource
from .sources.shooter import ShooterSource
from .sources.thunder import ThunderSource

_PLUGIN_INSTANCES: weakref.WeakValueDictionary[str, SubtitleDownloadAssistant] = weakref.WeakValueDictionary()


@eventmanager.register(ChainEventType.PluginDataReset)
def _handle_plugin_data_reset(event: Event) -> None:
    """在宿主删除 PluginData 前同步清理当前插件自有文件。"""

    payload = event.event_data
    plugin_id = getattr(payload, "plugin_id", None)
    if not plugin_id or not bool(getattr(payload, "reset_data", False)):
        return
    plugin = _PLUGIN_INSTANCES.get(str(plugin_id))
    if plugin is not None:
        plugin.reset_data_sync()


class SubtitleDownloadAssistant(_PluginBase):
    """提供字幕搜索、归属、落盘、维护与审计的全生命周期管理。"""

    plugin_name = "字幕下载助手"
    plugin_desc = "自动刮削媒体库影片字幕，支持常见视频格式及 STRM 格式。"
    plugin_icon = "https://raw.githubusercontent.com/KiritoJia/SubtitleDownloadAssistant/main/icons/SubtitleDownloadAssistant.png"
    plugin_version = "1.1.8"
    plugin_author = "Kirito"
    plugin_label = "字幕"
    plugin_config_prefix = "subtitledownloadassistant_"
    plugin_order = 30
    auth_level = 1

    def __init__(self) -> None:
        """初始化插件基类与空运行态。"""

        super().__init__()
        self._enabled = False
        self.config = PluginConfig()
        self.store: PluginStore | None = None
        self.filesystem: SubtitleFileSystem | None = None
        self.inventory: SubtitleInventory | None = None
        self.coordinator: TaskCoordinator | None = None
        self.api_controller: ApiController | None = None
        self.targets: TargetQueryService | None = None
        self.manual_search: ManualSearchService | None = None
        self.retargeting: RetargetService | None = None
        self.record_mutation_lock: ReentrantAsyncLock | None = None
        self._history_scan_lock = asyncio.Lock()

    def init_plugin(self, config: dict | None = None) -> None:
        """停止旧运行代次并按新配置完整重建插件服务。"""

        logger.info("字幕下载助手开始初始化或重载")
        self.stop_service()
        self._enabled = False
        try:
            self.config = PluginConfig.from_mapping(config, settings.RMT_SUBEXT)
        except ValueError as exc:
            self.config = PluginConfig()
            logger.error(f"字幕下载助手配置无效，未启动服务：{exc}")
            self.store = None
            self.api_controller = None
            return
        store = PluginStore(self)
        try:
            store.initialize()
        except StoreInitializationError as exc:
            logger.error(f"字幕下载助手数据初始化失败：{type(exc).__name__}")
            self.store = None
            self.api_controller = None
            return
        store.mark_nonterminal_interrupted_sync("任务在服务重启前未完成，已中断且不会自动恢复")
        store.ensure_source_statuses_sync(self.config.enabled_sources())

        filesystem = SubtitleFileSystem(
            data_root=self.get_data_path(),
            allowed_formats=settings.RMT_SUBEXT,
        )
        record_mutation_lock = ReentrantAsyncLock()
        inventory = SubtitleInventory(
            store=store,
            filesystem=filesystem,
            records=store.list_records_sync(),
            format_priority=self.config.format_priority,
            source_priority=self.config.source_priority,
            mutation_lock=record_mutation_lock,
        )
        opensubtitles_credentials = store.get_credentials_sync(SubtitleSource.OPENSUBTITLES)
        assrt_credentials = store.get_credentials_sync(SubtitleSource.ASSRT)
        allowed_formats = set(settings.RMT_SUBEXT)
        fingerprints = MediaFingerprintService()
        source_gate = SourceConcurrencyGate(
            tuple(SubtitleSource),
            minimum_intervals={
                SubtitleSource.SHOOTER: 1.0,
                SubtitleSource.THUNDER: 1.0,
            },
        )
        sources: dict[SubtitleSource, SubtitleSourcePort] = {
            SubtitleSource.MOVIEPILOT: MoviePilotSource(
                enabled=self.config.moviepilot_enabled,
                allowed_formats=allowed_formats,
            ),
            SubtitleSource.OPENSUBTITLES: OpenSubtitlesSource(
                enabled=self.config.opensubtitles_enabled,
                credentials=opensubtitles_credentials,
                allowed_formats=allowed_formats,
            ),
            SubtitleSource.ASSRT: AssrtSource(
                enabled=self.config.assrt_enabled,
                credentials=assrt_credentials,
                allowed_formats=allowed_formats,
            ),
            SubtitleSource.SHOOTER: ShooterSource(
                enabled=self.config.shooter_enabled,
                allowed_formats=allowed_formats,
                fingerprints=fingerprints,
            ),
            SubtitleSource.THUNDER: ThunderSource(
                enabled=self.config.thunder_enabled,
                allowed_formats=allowed_formats,
                fingerprints=fingerprints,
            ),
        }
        # AI 接管适配器只持有当前配置读取器，不保存任务结果；每个批次由适配器
        # 再次检查插件开关与 MoviePilot 总开关，避免把初始化时状态固化进任务。
        ai_adapter = AiAttributionAdapter(config=lambda: self.config)
        coordinator = TaskCoordinator(
            store=store,
            filesystem=filesystem,
            archive=ArchiveExtractor(),
            matcher=MoviePilotMatcher(),
            sources=sources,
            config=self.config,
            inventory=inventory,
            ai_adapter=ai_adapter,
            source_gate=source_gate,
        )
        for directory in self.config.custom_media_directories:
            if not Path(directory).is_dir():
                logger.warning(f"字幕下载助手自定义媒体目录不可用：{directory}")
        targets = TargetQueryService(
            custom_media_directories=self.config.custom_media_directories,
            path_mappings=self.config.path_mappings,
            allowed_extensions=set(settings.RMT_MEDIAEXT),
        )
        self.store = store
        self.filesystem = filesystem
        self.inventory = inventory
        self.coordinator = coordinator
        self.targets = targets
        self.manual_search = ManualSearchService(targets=targets, sources=sources, source_gate=source_gate)
        self.retargeting = RetargetService(
            store=store,
            filesystem=filesystem,
            inventory=inventory,
            targets=targets,
            config_provider=lambda: self.config,
            mutation_lock=record_mutation_lock,
        )
        self.record_mutation_lock = record_mutation_lock
        self.api_controller = ApiController(self)
        self._enabled = self.config.enabled
        _PLUGIN_INSTANCES[self.__class__.__name__] = self
        logger.info(f"字幕下载助手初始化完成，当前{'已启用' if self._enabled else '未启用'}")

    def get_state(self) -> bool:
        """返回插件是否启用且数据初始化成功。"""

        return bool(self._enabled and self.coordinator is not None)

    @staticmethod
    def get_command() -> list[dict[str, Any]]:
        """插件不提供远程命令。"""

        return []

    def get_service(self) -> list[dict[str, Any]]:
        """使用宿主调度器按配置间隔巡检自定义媒体目录。"""

        if (
            not self.get_state()
            or not self.config.directory_monitor_enabled
            or not self.config.custom_media_directories
        ):
            return []
        return [
            {
                "id": "SubtitleDownloadAssistantDirectoryMonitor",
                "name": "字幕下载助手目录增量监控",
                "trigger": IntervalTrigger(seconds=self.config.directory_monitor_interval),
                "func": self.run_directory_monitor,
                "kwargs": {},
            }
        ]

    def run_directory_monitor(self) -> None:
        """从宿主调度线程把目录巡检安全转发到 asyncio 事件循环。"""

        coroutine = self.monitor_custom_media_directories()
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        loop = global_vars.loop
        if loop and loop.is_running() and loop is not running_loop:
            asyncio.run_coroutine_threadsafe(coroutine, loop)
        elif running_loop is not None:
            running_loop.create_task(coroutine)
        else:
            asyncio.run(coroutine)

    @staticmethod
    def get_render_mode() -> tuple[str, str]:
        """声明使用 Vue 联邦组件与构建产物目录。"""

        return "vue", "frontend/dist/assets"

    def get_sidebar_nav(self) -> list[dict[str, Any]]:
        """启用时提供整理分组中的完整工作台入口。"""

        if not self.get_state():
            return []
        return [
            {
                "nav_key": "main",
                "title": "字幕下载助手",
                "icon": "mdi-subtitles-outline",
                "section": "organize",
                "permission": "manage",
                "order": 30,
            }
        ]

    def get_api(self) -> list[dict[str, Any]]:
        """返回插件 Bearer API 定义。"""

        return self.api_controller.routes() if self.api_controller else []

    def get_form(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """返回 Vue Config 的非敏感初始模型。"""

        opensubtitles_configured = bool(
            self.store and self.store.credentials_configured_sync(SubtitleSource.OPENSUBTITLES)
        )
        assrt_configured = bool(self.store and self.store.credentials_configured_sync(SubtitleSource.ASSRT))
        return [], self.config.public_payload(
            plugin_id=self.__class__.__name__,
            allowed_formats=settings.RMT_SUBEXT,
            opensubtitles_configured=opensubtitles_configured,
            assrt_configured=assrt_configured,
            host_ai_enabled=bool(getattr(settings, "AI_AGENT_ENABLE", False)),
        )

    def get_page(self) -> None:
        """详情页由完整工作台替代。"""

    @eventmanager.register(EventType.TransferComplete)
    async def on_transfer_complete(self, event: Event) -> None:
        """接收运行期整理完成事件并创建或合并字幕任务。"""

        if not self.get_state() or self.coordinator is None:
            logger.debug("字幕下载助手当前不可用，已忽略媒体整理完成事件")
            return
        data = event.event_data if isinstance(event.event_data, dict) else {}
        transferinfo = data.get("transferinfo")
        target = getattr(transferinfo, "target_item", None)
        if target is None:
            logger.warning("媒体整理完成事件没有目标文件，无法创建自动补齐任务")
            return
        context = build_media_context(target, data.get("meta"), data.get("mediainfo"))
        if context is None:
            logger.warning("媒体整理完成事件缺少可用的媒体上下文，无法创建自动补齐任务")
            return
        original_target_path = context.target_path
        if self.targets is not None:
            context, target = await self.targets.resolve_runtime_target(context, target)
        if context.target_path != original_target_path:
            logger.info(
                f"字幕下载助手已将整理目标“{original_target_path}”"
                f"定位到本地文件“{context.target_path}”"
            )
        if getattr(target, "storage", None) != "local":
            logger.info(
                f"字幕下载助手整理目标“{original_target_path}”尚未定位到自定义本地目录，"
                "不创建网盘字幕任务，等待目录监控发现本地文件"
            )
            return
        logger.info(f"字幕下载助手收到媒体整理完成事件，目标文件为“{context.target_path}”")
        history_id = data.get("transfer_history_id")
        try:
            history_id = int(history_id) if history_id not in (None, "") else None
        except (TypeError, ValueError):
            history_id = None
        await self.coordinator.enqueue(
            TaskWorkItem(
                context=context,
                target=target,
                host_mediainfo=data.get("mediainfo"),
                history_target_path=original_target_path,
                target_history_id=history_id,
            )
        )

    async def scan_custom_media_directories(
        self,
        automatic: bool = False,
        force: bool = False,
    ) -> dict[str, int]:
        """扫描自定义目录；人工全量模式可忽略已有文件签名。"""

        if not self.get_state() or self.targets is None or self.coordinator is None or self.store is None:
            raise RuntimeError("字幕下载助手当前未启用")
        if not self.config.custom_media_directories:
            raise ValueError("请先保存至少一个自定义媒体目录")
        if automatic and force:
            raise ValueError("目录自动巡检不能使用全量重新扫描模式")
        if self._history_scan_lock.locked():
            raise RuntimeError("自定义目录扫描正在进行，请勿重复提交")

        async with self._history_scan_lock:
            snapshot = await self.targets.custom_directory_snapshot()
            previous_index = await self.store.get_scan_index()
            signature_changed_keys = {
                key
                for key, item in snapshot.files.items()
                if (
                    (previous := previous_index.get(key)) is None
                    or previous.get("path") != str(item.path)
                    or previous.get("size") != item.size
                    or previous.get("mtime_ns") != item.mtime_ns
                )
            }
            pending_stability_keys: set[str] = set()
            if force:
                changed_keys = set(snapshot.files)
            elif automatic:
                pending_stability_keys = signature_changed_keys
                changed_keys = {
                    key
                    for key in set(snapshot.files).difference(signature_changed_keys)
                    if previous_index.get(key, {}).get("pending_stability") is True
                }
            else:
                changed_keys = set(signature_changed_keys)
                changed_keys.update(
                    key
                    for key in snapshot.files
                    if previous_index.get(key, {}).get("pending_stability") is True
                )
            retry_count = 0
            if not force:
                for key in set(snapshot.files).difference(changed_keys).difference(signature_changed_keys):
                    task_id = previous_index.get(key, {}).get("last_task_id")
                    if not task_id:
                        continue
                    task = await self.store.get_task(task_id)
                    retryable = (
                        task is not None
                        and (
                            task.status is TaskStatus.INTERRUPTED
                            or (not automatic and task.status is TaskStatus.FAILED)
                        )
                    )
                    if retryable:
                        changed_keys.add(key)
                        retry_count += 1

            if changed_keys:
                scan = await self.targets.scan_custom_directories(logical_keys=changed_keys)
            else:
                scan = None
            targets = scan.targets if scan is not None else []
            if self.manual_search is not None and targets:
                # Enriching targets may issue several TMDB requests per item.
                # Keep custom-directory scans gentle on the configured proxy.
                semaphore = asyncio.Semaphore(1)

                async def enrich(target: Any) -> Any:
                    async with semaphore:
                        return await self.manual_search.enrich_target(target)

                targets = list(await asyncio.gather(*(enrich(target) for target in targets)))

            submitted_count = 0
            accepted_task_ids: dict[str, str] = {}
            for target in targets:
                task_id = await self.coordinator.enqueue(
                    TaskWorkItem(
                        context=target.context,
                        target=target.target_item,
                        host_mediainfo=target.host_mediainfo,
                        trigger=TaskTrigger.CUSTOM_DIRECTORY_SCAN,
                        history_target_path=target.history_target_path,
                        target_history_id=target.history_id,
                    )
                )
                if task_id is not None:
                    submitted_count += 1
                    key = self.targets.logical_media_key(target.context.target_path)
                    accepted_task_ids[key] = task_id

            next_index: dict[str, dict[str, Any]] = {}
            for key, item in snapshot.files.items():
                previous = previous_index.get(key)
                if key in pending_stability_keys:
                    previous_task_id = previous.get("last_task_id") if previous is not None else None
                    last_task_id = previous_task_id if isinstance(previous_task_id, str) else None
                    next_index[key] = item.index_value(last_task_id, pending_stability=True)
                    continue
                if key in changed_keys and key not in accepted_task_ids:
                    if previous is not None:
                        next_index[key] = previous
                    continue
                last_task_id = accepted_task_ids.get(key)
                if last_task_id is None and previous is not None:
                    previous_task_id = previous.get("last_task_id")
                    last_task_id = previous_task_id if isinstance(previous_task_id, str) else None
                next_index[key] = item.index_value(last_task_id)
            if next_index != previous_index:
                await self.store.save_scan_index(next_index)

            history_count = scan.history_count if scan is not None else 0
            history_matched_count = scan.history_matched_count if scan is not None else 0
            recognized_file_count = scan.recognized_file_count if scan is not None else 0
            fallback_file_count = scan.fallback_file_count if scan is not None else 0
            unchanged_count = max(0, len(snapshot.files) - len(changed_keys) - len(pending_stability_keys))
            removed_count = len(set(previous_index).difference(snapshot.files))
            scan_mode = "全量重新扫描" if force else "增量扫描"
            logger.info(
                f"字幕下载助手自定义目录{scan_mode}完成："
                f"索引 {snapshot.indexed_file_count} 个媒体文件，"
                f"跳过 {unchanged_count} 个未变更目标，"
                f"形成 {len(targets)} 个字幕目标，"
                f"其中整理历史匹配 {history_matched_count} 个，"
                f"提交或合并 {submitted_count} 个字幕任务"
            )
            return {
                "history_count": history_count,
                "indexed_file_count": snapshot.indexed_file_count,
                "matched_count": len(targets),
                "submitted_count": submitted_count,
                "history_matched_count": history_matched_count,
                "recognized_file_count": recognized_file_count,
                "fallback_file_count": fallback_file_count,
                "unchanged_count": unchanged_count,
                "changed_count": len(changed_keys),
                "pending_stability_count": len(pending_stability_keys),
                "retry_count": retry_count,
                "removed_count": removed_count,
            }

    async def monitor_custom_media_directories(self) -> None:
        """执行一次后台增量巡检，单次失败不影响后续调度。"""

        if not self.get_state() or not self.config.directory_monitor_enabled:
            return
        try:
            result = await self.scan_custom_media_directories(automatic=True)
        except RuntimeError as exc:
            if self._history_scan_lock.locked():
                logger.debug("字幕下载助手目录巡检与手动扫描重叠，已跳过本轮")
                return
            logger.warning(f"字幕下载助手目录巡检未执行：{exc}")
            return
        except Exception as exc:  # noqa: BLE001 - 调度任务必须隔离单轮错误
            logger.error(f"字幕下载助手目录巡检失败：{type(exc).__name__}")
            return
        if result["submitted_count"]:
            logger.info(
                f"字幕下载助手目录监控发现 {result['changed_count']} 个新增或变更目标，"
                f"已提交 {result['submitted_count']} 个字幕任务"
            )

    async def update_source_credentials(self, source: SubtitleSource, values: dict[str, str]) -> bool:
        """增量保存外部来源凭据并返回配置完整状态。"""

        if self.store is None:
            raise RuntimeError("插件数据尚未初始化")
        configured = await self.store.update_credentials(source, values)
        credentials = await self.store.get_credentials(source)
        enabled = self.config.enabled_sources().get(source, False)
        if self.coordinator and source in self.coordinator.sources:
            adapter = self.coordinator.sources[source]
            adapter.enabled = enabled
            if isinstance(adapter, (OpenSubtitlesSource, AssrtSource)):
                await adapter.replace_credentials(credentials)
        await self.store.save_source_status(
            SourceStatus(
                source=source,
                enabled=enabled,
                configured=configured,
                health=SourceHealth.PENDING if enabled and configured else SourceHealth.DISABLED,
            )
        )
        return configured

    async def clear_source_credentials(self, source: SubtitleSource) -> bool:
        """删除来源凭据、立即停用来源并保存非敏感开关。"""

        if self.store is None:
            raise RuntimeError("插件数据尚未初始化")
        await self.store.clear_credentials(source)
        if source is SubtitleSource.OPENSUBTITLES:
            self.config.opensubtitles_enabled = False
        elif source is SubtitleSource.ASSRT:
            self.config.assrt_enabled = False
        if self.coordinator and source in self.coordinator.sources:
            adapter = self.coordinator.sources[source]
            adapter.enabled = False
            if isinstance(adapter, (OpenSubtitlesSource, AssrtSource)):
                await adapter.replace_credentials({})
        await self.store.save_source_status(
            SourceStatus(
                source=source,
                enabled=False,
                configured=False,
                health=SourceHealth.DISABLED,
            )
        )
        return bool(self.update_config(self.config.saved_payload(), plugin_id=self.__class__.__name__))

    def reset_data_sync(self) -> None:
        """同步等待插件数据目录与分区在宿主删除前清理完成。"""

        if self.coordinator is None:
            return
        coroutine = self.coordinator.reset()
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        loop = global_vars.loop
        if loop and loop.is_running() and loop is not running_loop:
            asyncio.run_coroutine_threadsafe(coroutine, loop).result()
        elif running_loop is None:
            asyncio.run(coroutine)
        else:
            # 宿主当前重置路由在线程中调用；此分支仅作防御性回退。
            running_loop.create_task(coroutine)

    def stop_service(self) -> None:
        """立即中断当前及等待任务并释放运行态资源。"""

        if self._enabled or self.manual_search is not None or self.coordinator is not None:
            logger.info("字幕下载助手正在停止服务")
        self._enabled = False
        if self.manual_search is not None:
            coroutine = self.manual_search.clear_sessions()
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None
            if running_loop is None:
                asyncio.run(coroutine)
            else:
                running_loop.create_task(coroutine)
        if self.coordinator is not None:
            self.coordinator.stop_sync()
