"""基于 MoviePilot PluginData 的分区持久化。"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from threading import RLock
from typing import Any

from pydantic import ValidationError

from ..domain.enums import RecordStatus, SourceHealth, SubtitleSource, TaskStatus
from ..domain.models import MatchRecord, SourceStatus, SubtitleTask


class StoreInitializationError(RuntimeError):
    """插件数据分区无法安全初始化时抛出的错误。"""


class PluginStore:
    """封装五个版本化 PluginData 分区并提供异步业务访问。"""

    VERSION = 2
    TASKS_KEY = "tasks"
    RECORDS_KEY = "records"
    SOURCE_STATUS_KEY = "source_status"
    CREDENTIALS_KEY = "credentials"
    SCAN_INDEX_KEY = "scan_index"
    _PARTITION_KEYS = (TASKS_KEY, RECORDS_KEY, SOURCE_STATUS_KEY, CREDENTIALS_KEY, SCAN_INDEX_KEY)

    def __init__(self, plugin: Any) -> None:
        """创建绑定到插件实例的存储。"""

        self._plugin = plugin
        self._lock = RLock()
        self._async_mutation_lock = asyncio.Lock()
        self._tasks: dict[str, SubtitleTask] = {}
        self._records: dict[str, MatchRecord] = {}
        self._source_status: dict[str, SourceStatus] = {}
        self._credentials: dict[str, dict[str, str]] = {}
        self._scan_index: dict[str, dict[str, Any]] = {}

    def initialize(self) -> None:
        """在同步宿主启动边界读取五个分区，缺失分区初始化为空。"""

        try:
            raw = {key: self._plugin.get_data(key) for key in self._PARTITION_KEYS}
        except Exception as exc:
            raise StoreInitializationError("插件数据分区读取失败") from exc
        tasks, records, statuses, credentials, scan_index, missing = self._decode_partitions(raw)
        try:
            for key in missing:
                self._persist_partition_sync(
                    key,
                    self._partition_items(key, tasks, records, statuses, credentials, scan_index),
                )
        except Exception as exc:
            raise StoreInitializationError("插件数据缺失分区初始化失败") from exc
        self._publish_snapshots(tasks, records, statuses, credentials, scan_index)

    async def reload(self) -> None:
        """显式异步重新装载全部分区，并在完整成功后发布新快照。"""

        async with self._async_mutation_lock:
            try:
                raw: dict[str, Any] = {}
                for key in self._PARTITION_KEYS:
                    raw[key] = await self._plugin.async_get_data(key)
            except Exception as exc:
                raise StoreInitializationError("插件数据分区异步读取失败") from exc
            tasks, records, statuses, credentials, scan_index, missing = self._decode_partitions(raw)
            try:
                for key in missing:
                    await self._persist_partition(
                        key,
                        self._partition_items(key, tasks, records, statuses, credentials, scan_index),
                    )
            except Exception as exc:
                raise StoreInitializationError("插件数据缺失分区异步初始化失败") from exc
            self._publish_snapshots(tasks, records, statuses, credentials, scan_index)

    def _decode_partitions(
        self,
        raw: dict[str, Any],
    ) -> tuple[
        dict[str, SubtitleTask],
        dict[str, MatchRecord],
        dict[str, SourceStatus],
        dict[str, dict[str, str]],
        dict[str, dict[str, Any]],
        list[str],
    ]:
        """校验原始分区并构造尚未发布的完整内存快照。"""

        missing: list[str] = []
        tasks_raw = self._unwrap_partition(self.TASKS_KEY, raw.get(self.TASKS_KEY), [], missing)
        records_raw = self._unwrap_partition(self.RECORDS_KEY, raw.get(self.RECORDS_KEY), [], missing)
        statuses_raw = self._unwrap_partition(self.SOURCE_STATUS_KEY, raw.get(self.SOURCE_STATUS_KEY), [], missing)
        credentials_raw = self._unwrap_partition(self.CREDENTIALS_KEY, raw.get(self.CREDENTIALS_KEY), {}, missing)
        scan_index_raw = self._unwrap_partition(self.SCAN_INDEX_KEY, raw.get(self.SCAN_INDEX_KEY), {}, missing)
        try:
            if not isinstance(tasks_raw, list):
                raise TypeError("tasks 分区必须是数组")
            if not isinstance(records_raw, list):
                raise TypeError("records 分区必须是数组")
            if not isinstance(statuses_raw, list):
                raise TypeError("source_status 分区必须是数组")
            if not isinstance(credentials_raw, dict):
                raise TypeError("credentials 分区必须是对象")
            if not isinstance(scan_index_raw, dict):
                raise TypeError("scan_index 分区必须是对象")
            tasks = {item.id: item for item in (SubtitleTask.model_validate(value) for value in tasks_raw)}
            records = {item.id: item for item in (MatchRecord.model_validate(value) for value in records_raw)}
            statuses = {
                item.source.value: item for item in (SourceStatus.model_validate(value) for value in statuses_raw)
            }
            credentials = self._validate_credentials(credentials_raw)
            scan_index = self._validate_scan_index(scan_index_raw)
        except (ValidationError, TypeError, ValueError) as exc:
            raise StoreInitializationError(f"插件数据结构校验失败：{exc}") from exc
        return tasks, records, statuses, credentials, scan_index, missing

    def _unwrap_partition(self, key: str, raw: Any, default: Any, missing: list[str]) -> Any:
        """解开单个版本化分区，并记录需要初始化的缺失分区。"""

        if raw is None:
            missing.append(key)
            return deepcopy(default)
        if not isinstance(raw, dict) or "version" not in raw or "items" not in raw:
            raise StoreInitializationError(f"插件数据分区 {key} 结构损坏")
        version = raw.get("version")
        if version != self.VERSION:
            raise StoreInitializationError(f"插件数据分区 {key} 版本不受支持：{version}")
        return deepcopy(raw["items"])

    def _publish_snapshots(
        self,
        tasks: dict[str, SubtitleTask],
        records: dict[str, MatchRecord],
        statuses: dict[str, SourceStatus],
        credentials: dict[str, dict[str, str]],
        scan_index: dict[str, dict[str, Any]],
    ) -> None:
        """在同步临界区一次发布五个已经验证的快照。"""

        with self._lock:
            self._tasks = tasks
            self._records = records
            self._source_status = statuses
            self._credentials = credentials
            self._scan_index = scan_index

    def _partition_items(
        self,
        key: str,
        tasks: dict[str, SubtitleTask],
        records: dict[str, MatchRecord],
        statuses: dict[str, SourceStatus],
        credentials: dict[str, dict[str, str]],
        scan_index: dict[str, dict[str, Any]],
    ) -> Any:
        """把指定候选快照转换为 PluginData 的 JSON 安全 items。"""

        if key == self.TASKS_KEY:
            return self._task_values(tasks)
        if key == self.RECORDS_KEY:
            return self._record_values(records)
        if key == self.SOURCE_STATUS_KEY:
            return self._status_values(statuses)
        if key == self.CREDENTIALS_KEY:
            return deepcopy(credentials)
        if key == self.SCAN_INDEX_KEY:
            return deepcopy(scan_index)
        raise ValueError(f"未知插件数据分区：{key}")

    def _persist_partition_sync(self, key: str, items: Any) -> None:
        """只在同步宿主生命周期边界保存一个版本化分区。"""

        self._plugin.save_data(key, {"version": self.VERSION, "items": items})

    async def _persist_partition(self, key: str, items: Any) -> None:
        """直接调用宿主异步接口保存一个版本化分区。"""

        await self._plugin.async_save_data(key, {"version": self.VERSION, "items": items})

    @staticmethod
    def _validate_credentials(raw: dict[str, Any]) -> dict[str, dict[str, str]]:
        """校验凭据分区的字段类型而不记录秘密。"""

        result: dict[str, dict[str, str]] = {}
        for source, values in raw.items():
            if not isinstance(source, str) or not isinstance(values, dict):
                raise TypeError("credentials 字段类型错误")
            result[source] = {}
            for name, value in values.items():
                if not isinstance(name, str) or not isinstance(value, str):
                    raise TypeError("credentials 字段值必须是字符串")
                if value.strip():
                    result[source][name] = value
        return result

    @staticmethod
    def _validate_scan_index(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """校验自定义目录签名索引，防止损坏数据导致误跳过。"""

        result: dict[str, dict[str, Any]] = {}
        for key, value in raw.items():
            if not isinstance(key, str) or not key or not isinstance(value, dict):
                raise TypeError("scan_index 索引项类型错误")
            path = value.get("path")
            size = value.get("size")
            mtime_ns = value.get("mtime_ns")
            last_task_id = value.get("last_task_id")
            pending_stability = value.get("pending_stability", False)
            if not isinstance(path, str) or not path:
                raise TypeError("scan_index.path 必须是非空字符串")
            if not isinstance(size, int) or size < 0:
                raise TypeError("scan_index.size 必须是非负整数")
            if not isinstance(mtime_ns, int) or mtime_ns < 0:
                raise TypeError("scan_index.mtime_ns 必须是非负整数")
            if last_task_id is not None and not isinstance(last_task_id, str):
                raise TypeError("scan_index.last_task_id 必须是字符串或空值")
            if not isinstance(pending_stability, bool):
                raise TypeError("scan_index.pending_stability 必须是布尔值")
            result[key] = {
                "path": path,
                "size": size,
                "mtime_ns": mtime_ns,
                "last_task_id": last_task_id,
                "pending_stability": pending_stability,
            }
        return result

    @staticmethod
    def _task_values(tasks: dict[str, SubtitleTask]) -> list[dict[str, Any]]:
        """返回任务候选快照的 JSON 安全值。"""

        return [item.model_dump(mode="json") for item in tasks.values()]

    @staticmethod
    def _record_values(records: dict[str, MatchRecord]) -> list[dict[str, Any]]:
        """返回记录候选快照的 JSON 安全值。"""

        return [item.model_dump(mode="json") for item in records.values()]

    @staticmethod
    def _status_values(statuses: dict[str, SourceStatus]) -> list[dict[str, Any]]:
        """返回来源状态候选快照的 JSON 安全值。"""

        return [item.model_dump(mode="json") for item in statuses.values()]

    @staticmethod
    def _pruned_tasks(tasks: dict[str, SubtitleTask]) -> dict[str, SubtitleTask]:
        """返回保留待恢复中断项及最近 500 条普通终态任务的快照。"""

        terminal = [
            item
            for item in tasks.values()
            if item.is_terminal
            and not (
                item.status is TaskStatus.INTERRUPTED
                and item.reason_code == "service_interrupted"
            )
        ]
        if len(terminal) <= 500:
            return tasks
        terminal.sort(key=lambda item: item.finished_at or item.created_at, reverse=True)
        keep = {item.id for item in terminal[:500]}
        return {
            key: value
            for key, value in tasks.items()
            if not value.is_terminal
            or (
                value.status is TaskStatus.INTERRUPTED
                and value.reason_code == "service_interrupted"
            )
            or key in keep
        }

    @staticmethod
    def _pruned_records(records: dict[str, MatchRecord]) -> dict[str, MatchRecord]:
        """返回只保留最近 1000 条已匹配记录的候选快照。"""

        matched = [item for item in records.values() if item.status is RecordStatus.MATCHED]
        if len(matched) <= 1000:
            return records
        matched.sort(key=lambda item: item.created_at, reverse=True)
        keep = {item.id for item in matched[:1000]}
        return {key: value for key, value in records.items() if value.status is not RecordStatus.MATCHED or key in keep}

    def save_task_sync(self, task: SubtitleTask) -> None:
        """在同步宿主生命周期保存任务并应用历史保留规则。"""

        with self._lock:
            candidate = dict(self._tasks)
            candidate[task.id] = task.model_copy(deep=True)
            candidate = self._pruned_tasks(candidate)
            self._persist_partition_sync(self.TASKS_KEY, self._task_values(candidate))
            self._tasks = candidate

    async def save_task(self, task: SubtitleTask) -> None:
        """异步保存任务，并在持久化成功后发布候选快照。"""

        await self.save_tasks([task])

    async def save_tasks(self, tasks: list[SubtitleTask]) -> None:
        """一次持久化一批任务，供大批中断任务恢复使用。"""

        if not tasks:
            return
        async with self._async_mutation_lock:
            with self._lock:
                candidate = dict(self._tasks)
                for task in tasks:
                    candidate[task.id] = task.model_copy(deep=True)
                candidate = self._pruned_tasks(candidate)
                items = self._task_values(candidate)
            await self._persist_partition(self.TASKS_KEY, items)
            with self._lock:
                self._tasks = candidate

    def get_task_sync(self, task_id: str) -> SubtitleTask | None:
        """同步读取单个任务内存快照。"""

        with self._lock:
            task = self._tasks.get(task_id)
            return task.model_copy(deep=True) if task else None

    async def get_task(self, task_id: str) -> SubtitleTask | None:
        """从当前运行代次的内存快照读取单个任务。"""

        return self.get_task_sync(task_id)

    def list_tasks_sync(self) -> list[SubtitleTask]:
        """同步复制全部任务内存快照。"""

        with self._lock:
            return [item.model_copy(deep=True) for item in self._tasks.values()]

    async def list_tasks(self) -> list[SubtitleTask]:
        """从当前运行代次的内存快照复制全部任务。"""

        return self.list_tasks_sync()

    def delete_task_sync(self, task_id: str) -> bool:
        """在同步宿主生命周期删除任务历史。"""

        with self._lock:
            if task_id not in self._tasks:
                return False
            candidate = dict(self._tasks)
            del candidate[task_id]
            self._persist_partition_sync(self.TASKS_KEY, self._task_values(candidate))
            self._tasks = candidate
            return True

    async def delete_task(self, task_id: str) -> bool:
        """异步删除任务历史，并在持久化成功后发布候选快照。"""

        async with self._async_mutation_lock:
            with self._lock:
                if task_id not in self._tasks:
                    return False
                candidate = dict(self._tasks)
                del candidate[task_id]
                items = self._task_values(candidate)
            await self._persist_partition(self.TASKS_KEY, items)
            with self._lock:
                self._tasks = candidate
            return True

    async def delete_terminal_tasks(self, task_ids: set[str] | None = None) -> int:
        """一次持久化删除全部或指定终态任务，保留等待中和处理中的任务。"""

        async with self._async_mutation_lock:
            with self._lock:
                deleted_ids = {
                    task_id
                    for task_id, task in self._tasks.items()
                    if task.is_terminal and (task_ids is None or task_id in task_ids)
                }
                deleted_count = len(deleted_ids)
                if deleted_count == 0:
                    return 0
                candidate = {
                    task_id: task
                    for task_id, task in self._tasks.items()
                    if task_id not in deleted_ids
                }
                items = self._task_values(candidate)
            await self._persist_partition(self.TASKS_KEY, items)
            with self._lock:
                self._tasks = candidate
            return deleted_count

    def save_record_sync(self, record: MatchRecord) -> None:
        """在同步宿主生命周期保存记录并应用保留规则。"""

        with self._lock:
            candidate = dict(self._records)
            candidate[record.id] = record.model_copy(deep=True)
            candidate = self._pruned_records(candidate)
            self._persist_partition_sync(self.RECORDS_KEY, self._record_values(candidate))
            self._records = candidate

    async def save_record(self, record: MatchRecord) -> None:
        """异步保存记录，并在持久化成功后发布候选快照。"""

        async with self._async_mutation_lock:
            with self._lock:
                candidate = dict(self._records)
                candidate[record.id] = record.model_copy(deep=True)
                candidate = self._pruned_records(candidate)
                items = self._record_values(candidate)
            await self._persist_partition(self.RECORDS_KEY, items)
            with self._lock:
                self._records = candidate

    def get_record_sync(self, record_id: str) -> MatchRecord | None:
        """同步读取单个匹配记录内存快照。"""

        with self._lock:
            record = self._records.get(record_id)
            return record.model_copy(deep=True) if record else None

    async def get_record(self, record_id: str) -> MatchRecord | None:
        """从当前运行代次的内存快照读取单个匹配记录。"""

        return self.get_record_sync(record_id)

    def list_records_sync(self) -> list[MatchRecord]:
        """同步复制全部匹配记录内存快照。"""

        with self._lock:
            return [item.model_copy(deep=True) for item in self._records.values()]

    async def list_records(self) -> list[MatchRecord]:
        """从当前运行代次的内存快照复制全部匹配记录。"""

        return self.list_records_sync()

    def delete_record_sync(self, record_id: str) -> bool:
        """在同步宿主生命周期删除匹配记录元数据。"""

        with self._lock:
            if record_id not in self._records:
                return False
            candidate = dict(self._records)
            del candidate[record_id]
            self._persist_partition_sync(self.RECORDS_KEY, self._record_values(candidate))
            self._records = candidate
            return True

    @staticmethod
    def _record_version_matches(current: MatchRecord, expected: MatchRecord) -> bool:
        """比较删除确认所依赖的状态、位置、路径和更新时间。"""

        def normalized(value: datetime) -> datetime:
            """把持久化时间统一到可比较的 UTC 时区。"""

            if value.tzinfo is None:
                return value.replace(tzinfo=UTC)
            return value.astimezone(UTC)

        return (
            current.id == expected.id
            and current.status is expected.status
            and current.location is expected.location
            and current.path == expected.path
            and normalized(current.updated_at) == normalized(expected.updated_at)
        )

    def delete_record_if_match_sync(self, expected: MatchRecord) -> bool:
        """在同步宿主生命周期校验记录版本并删除。"""

        with self._lock:
            current = self._records.get(expected.id)
            if current is None or not self._record_version_matches(current, expected):
                return False
            candidate = dict(self._records)
            del candidate[expected.id]
            self._persist_partition_sync(self.RECORDS_KEY, self._record_values(candidate))
            self._records = candidate
            return True

    async def delete_record(self, record_id: str) -> bool:
        """异步删除匹配记录，并在持久化成功后发布候选快照。"""

        async with self._async_mutation_lock:
            with self._lock:
                if record_id not in self._records:
                    return False
                candidate = dict(self._records)
                del candidate[record_id]
                items = self._record_values(candidate)
            await self._persist_partition(self.RECORDS_KEY, items)
            with self._lock:
                self._records = candidate
            return True

    async def delete_record_if_match(self, expected: MatchRecord) -> bool:
        """异步校验记录版本并在持久化成功后发布删除结果。"""

        async with self._async_mutation_lock:
            with self._lock:
                current = self._records.get(expected.id)
                if current is None or not self._record_version_matches(current, expected):
                    return False
                candidate = dict(self._records)
                del candidate[expected.id]
                items = self._record_values(candidate)
            await self._persist_partition(self.RECORDS_KEY, items)
            with self._lock:
                self._records = candidate
            return True

    def save_source_status_sync(self, status: SourceStatus) -> None:
        """在同步宿主生命周期保存来源状态。"""

        with self._lock:
            candidate = dict(self._source_status)
            candidate[status.source.value] = status.model_copy(deep=True)
            self._persist_partition_sync(self.SOURCE_STATUS_KEY, self._status_values(candidate))
            self._source_status = candidate

    async def save_source_status(self, status: SourceStatus) -> None:
        """异步保存来源状态，并在持久化成功后发布候选快照。"""

        async with self._async_mutation_lock:
            with self._lock:
                candidate = dict(self._source_status)
                candidate[status.source.value] = status.model_copy(deep=True)
                items = self._status_values(candidate)
            await self._persist_partition(self.SOURCE_STATUS_KEY, items)
            with self._lock:
                self._source_status = candidate

    def list_source_statuses_sync(self) -> list[SourceStatus]:
        """同步复制全部来源状态内存快照。"""

        with self._lock:
            return [item.model_copy(deep=True) for item in self._source_status.values()]

    async def list_source_statuses(self) -> list[SourceStatus]:
        """从当前运行代次的内存快照复制全部来源状态。"""

        return self.list_source_statuses_sync()

    def get_credentials_sync(self, source: SubtitleSource) -> dict[str, str]:
        """同步读取来源长期凭据内存快照。"""

        with self._lock:
            return dict(self._credentials.get(source.value, {}))

    async def get_credentials(self, source: SubtitleSource) -> dict[str, str]:
        """从当前运行代次的内存快照读取来源长期凭据。"""

        return self.get_credentials_sync(source)

    @staticmethod
    def _credentials_configured(
        source: SubtitleSource,
        credentials: dict[str, dict[str, str]],
    ) -> bool:
        """根据给定凭据快照判断来源是否完整配置。"""

        values = credentials.get(source.value, {})
        required = {
            SubtitleSource.OPENSUBTITLES: ("api_key", "username", "password"),
            SubtitleSource.ASSRT: ("token",),
        }.get(source, ())
        return bool(required) and all(values.get(key, "").strip() for key in required)

    def update_credentials_sync(self, source: SubtitleSource, values: dict[str, str]) -> bool:
        """在同步宿主生命周期增量写入来源凭据。"""

        with self._lock:
            candidate = deepcopy(self._credentials)
            current = candidate.setdefault(source.value, {})
            for key, value in values.items():
                clean = str(value).strip()
                if clean:
                    current[key] = clean
            self._persist_partition_sync(self.CREDENTIALS_KEY, deepcopy(candidate))
            self._credentials = candidate
            return self._credentials_configured(source, candidate)

    def credentials_configured_sync(self, source: SubtitleSource) -> bool:
        """同步判断当前内存快照中的来源凭据是否完整。"""

        with self._lock:
            return self._credentials_configured(source, self._credentials)

    async def update_credentials(self, source: SubtitleSource, values: dict[str, str]) -> bool:
        """异步增量写入来源凭据，并在持久化成功后发布候选快照。"""

        async with self._async_mutation_lock:
            with self._lock:
                candidate = deepcopy(self._credentials)
                current = candidate.setdefault(source.value, {})
                for key, value in values.items():
                    clean = str(value).strip()
                    if clean:
                        current[key] = clean
                items = deepcopy(candidate)
            await self._persist_partition(self.CREDENTIALS_KEY, items)
            with self._lock:
                self._credentials = candidate
            return self._credentials_configured(source, candidate)

    def clear_credentials_sync(self, source: SubtitleSource) -> None:
        """在同步宿主生命周期删除来源全部长期凭据。"""

        with self._lock:
            candidate = deepcopy(self._credentials)
            candidate.pop(source.value, None)
            self._persist_partition_sync(self.CREDENTIALS_KEY, deepcopy(candidate))
            self._credentials = candidate

    async def clear_credentials(self, source: SubtitleSource) -> None:
        """异步删除来源凭据，并在持久化成功后发布候选快照。"""

        async with self._async_mutation_lock:
            with self._lock:
                candidate = deepcopy(self._credentials)
                candidate.pop(source.value, None)
                items = deepcopy(candidate)
            await self._persist_partition(self.CREDENTIALS_KEY, items)
            with self._lock:
                self._credentials = candidate

    def mark_nonterminal_interrupted_sync(self, message: str) -> list[str]:
        """在同步宿主生命周期把全部非终态任务标记为已中断。"""

        changed: list[str] = []
        with self._lock:
            candidate = dict(self._tasks)
            now = datetime.now(UTC)
            for task_id, task in self._tasks.items():
                if task.status not in {TaskStatus.QUEUED, TaskStatus.PROCESSING}:
                    continue
                updated = task.model_copy(deep=True)
                updated.status = TaskStatus.INTERRUPTED
                updated.stage = None
                updated.reason_code = "service_interrupted"
                updated.reason_message = message
                updated.finished_at = now
                updated.duration_ms = max(
                    0,
                    int(((updated.finished_at - (updated.started_at or updated.created_at)).total_seconds()) * 1000),
                )
                candidate[task_id] = updated
                changed.append(task_id)
            if changed:
                self._persist_partition_sync(self.TASKS_KEY, self._task_values(candidate))
                self._tasks = candidate
        return changed

    def get_scan_index_sync(self) -> dict[str, dict[str, Any]]:
        """同步返回目录增量扫描索引的独立快照。"""

        with self._lock:
            return deepcopy(self._scan_index)

    async def get_scan_index(self) -> dict[str, dict[str, Any]]:
        """异步返回当前目录增量扫描索引。"""

        return self.get_scan_index_sync()

    async def save_scan_index(self, items: dict[str, dict[str, Any]]) -> None:
        """原子保存完整目录签名快照，成功后再发布到内存。"""

        candidate = self._validate_scan_index(deepcopy(items))
        async with self._async_mutation_lock:
            await self._persist_partition(self.SCAN_INDEX_KEY, deepcopy(candidate))
            with self._lock:
                self._scan_index = candidate

    def reset_sync(self) -> None:
        """在同步宿主数据重置边界清空五个分区。"""

        with self._lock:
            self._persist_partition_sync(self.TASKS_KEY, [])
            self._persist_partition_sync(self.RECORDS_KEY, [])
            self._persist_partition_sync(self.SOURCE_STATUS_KEY, [])
            self._persist_partition_sync(self.CREDENTIALS_KEY, {})
            self._persist_partition_sync(self.SCAN_INDEX_KEY, {})
            self._tasks = {}
            self._records = {}
            self._source_status = {}
            self._credentials = {}
            self._scan_index = {}

    async def reset(self) -> None:
        """异步清空五个分区，并在全部保存成功后发布空快照。"""

        async with self._async_mutation_lock:
            await self._persist_partition(self.TASKS_KEY, [])
            await self._persist_partition(self.RECORDS_KEY, [])
            await self._persist_partition(self.SOURCE_STATUS_KEY, [])
            await self._persist_partition(self.CREDENTIALS_KEY, {})
            await self._persist_partition(self.SCAN_INDEX_KEY, {})
            self._publish_snapshots({}, {}, {}, {}, {})

    def ensure_source_statuses_sync(self, enabled: dict[SubtitleSource, bool]) -> None:
        """在同步宿主启动边界补齐全部来源状态并应用启用配置。"""

        with self._lock:
            candidate = dict(self._source_status)
            for source in SubtitleSource:
                current = candidate.get(source.value)
                configured = self._credentials_configured(source, self._credentials)
                if source in {
                    SubtitleSource.MOVIEPILOT,
                    SubtitleSource.SHOOTER,
                    SubtitleSource.THUNDER,
                }:
                    configured = True
                updated = current.model_copy(deep=True) if current is not None else SourceStatus(source=source)
                updated.enabled = bool(enabled.get(source, False))
                updated.configured = configured
                updated.health = SourceHealth.PENDING if updated.enabled and configured else SourceHealth.DISABLED
                candidate[source.value] = updated
            self._persist_partition_sync(self.SOURCE_STATUS_KEY, self._status_values(candidate))
            self._source_status = candidate
