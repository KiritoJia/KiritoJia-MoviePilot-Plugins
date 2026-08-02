"""自定义目录增量扫描状态流转测试。"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import SimpleNamespace


class TaskStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class TaskTrigger(StrEnum):
    TRANSFER_EVENT = "transfer_event"
    CUSTOM_DIRECTORY_SCAN = "custom_directory_scan"


@dataclass
class TaskWorkItem:
    context: object
    target: object
    host_mediainfo: object | None = None
    trigger: TaskTrigger = TaskTrigger.TRANSFER_EVENT
    history_target_path: str | None = None
    target_history_id: int | None = None


class DummyBase:
    def __init__(self) -> None:
        pass


class DummyLogger:
    def __getattr__(self, _name: str):
        return lambda *_args, **_kwargs: None


def _module(name: str, **values: object) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in values.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _load_plugin_class():
    root = Path(__file__).resolve().parents[1]
    package = "subtitledownloadassistant_scan_test"
    app = _module("app")
    app.__path__ = []
    eventmanager = SimpleNamespace(register=lambda _event: lambda value: value)
    _module("app.core").__path__ = []
    _module(
        "app.core.config",
        global_vars=SimpleNamespace(loop=None),
        settings=SimpleNamespace(RMT_SUBEXT=[], RMT_MEDIAEXT=[], AI_AGENT_ENABLE=False),
    )
    _module("app.core.event", Event=object, eventmanager=eventmanager)
    _module("app.log", logger=DummyLogger())
    _module("app.plugins", _PluginBase=DummyBase)
    _module("app.schemas").__path__ = []
    _module(
        "app.schemas.types",
        ChainEventType=SimpleNamespace(PluginDataReset="PluginDataReset"),
        EventType=SimpleNamespace(TransferComplete="TransferComplete"),
    )
    _module("apscheduler").__path__ = []
    _module("apscheduler.triggers").__path__ = []
    _module("apscheduler.triggers.interval", IntervalTrigger=lambda **kwargs: kwargs)

    package_module = _module(package)
    package_module.__path__ = [str(root)]
    stubs = {
        "api.router": {"ApiController": object},
        "application.config": {"PluginConfig": object},
        "application.inventory": {"SubtitleInventory": object},
        "application.ports": {"SubtitleSourcePort": object},
        "application.record_lock": {"ReentrantAsyncLock": object},
        "application.retargeting": {"RetargetService": object},
        "application.searches": {"ManualSearchService": object, "TargetQueryService": object},
        "application.source_gate": {"SourceConcurrencyGate": object},
        "application.tasks": {
            "TaskCoordinator": object,
            "TaskWorkItem": TaskWorkItem,
            "build_media_context": lambda *_args: None,
        },
        "domain.enums": {
            "SourceHealth": object,
            "SubtitleSource": object,
            "TaskStatus": TaskStatus,
            "TaskTrigger": TaskTrigger,
        },
        "domain.models": {"SourceStatus": object},
        "infrastructure.ai_attribution": {"AiAttributionAdapter": object},
        "infrastructure.archive": {"ArchiveExtractor": object},
        "infrastructure.filesystem": {"SubtitleFileSystem": object},
        "infrastructure.matching": {"MoviePilotMatcher": object},
        "infrastructure.store": {"PluginStore": object, "StoreInitializationError": RuntimeError},
        "sources.assrt": {"AssrtSource": object},
        "sources.fingerprint": {"MediaFingerprintService": object},
        "sources.moviepilot": {"MoviePilotSource": object},
        "sources.opensubtitles": {"OpenSubtitlesSource": object},
        "sources.shooter": {"ShooterSource": object},
        "sources.thunder": {"ThunderSource": object},
    }
    for suffix, values in stubs.items():
        parts = suffix.split(".")
        for index in range(1, len(parts)):
            parent = f"{package}." + ".".join(parts[:index])
            if parent not in sys.modules:
                _module(parent).__path__ = []
        _module(f"{package}.{suffix}", **values)

    spec = importlib.util.spec_from_file_location(
        package,
        root / "__init__.py",
        submodule_search_locations=[str(root)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    return module.SubtitleDownloadAssistant


def _load_store_class():
    root = Path(__file__).resolve().parents[1]
    package = "subtitledownloadassistant_store_test"
    package_module = _module(package)
    package_module.__path__ = [str(root)]
    for name, path in (
        (f"{package}.domain", root / "domain"),
        (f"{package}.infrastructure", root / "infrastructure"),
    ):
        module = _module(name)
        module.__path__ = [str(path)]

    for name, path in (
        (f"{package}.domain.enums", root / "domain/enums.py"),
        (f"{package}.domain.models", root / "domain/models.py"),
        (f"{package}.infrastructure.store", root / "infrastructure/store.py"),
    ):
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[f"{package}.infrastructure.store"].PluginStore


def _load_api_schemas_module():
    root = Path(__file__).resolve().parents[1]
    _load_store_class()
    package = "subtitledownloadassistant_store_test"
    api_package = _module(f"{package}.api")
    api_package.__path__ = [str(root / "api")]
    name = f"{package}.api.schemas"
    spec = importlib.util.spec_from_file_location(name, root / "api/schemas.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class FakeFile:
    path: Path
    size: int
    mtime_ns: int

    def index_value(self, last_task_id: str | None = None, *, pending_stability: bool = False):
        return {
            "path": str(self.path),
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "last_task_id": last_task_id,
            "pending_stability": pending_stability,
        }


class FakeStore:
    def __init__(self) -> None:
        self.index: dict[str, dict[str, object]] = {}
        self.tasks: dict[str, object] = {}

    async def get_scan_index(self):
        return {key: dict(value) for key, value in self.index.items()}

    async def save_scan_index(self, value):
        self.index = {key: dict(item) for key, item in value.items()}

    async def get_task(self, task_id):
        return self.tasks.get(task_id)


class FakeTargets:
    def __init__(self, snapshots: list[FakeFile]) -> None:
        self.snapshots = snapshots
        self.position = 0

    async def custom_directory_snapshot(self):
        current = self.snapshots[self.position]
        return SimpleNamespace(files={str(current.path.with_suffix("")): current}, indexed_file_count=1)

    async def scan_custom_directories(self, logical_keys):
        key = next(iter(logical_keys))
        context = SimpleNamespace(target_path=key)
        target = SimpleNamespace(
            context=context,
            target_item=object(),
            host_mediainfo=None,
            history_target_path=None,
            history_id=None,
        )
        return SimpleNamespace(
            targets=[target],
            history_count=0,
            history_matched_count=0,
            recognized_file_count=1,
            fallback_file_count=0,
        )

    @staticmethod
    def logical_media_key(path):
        return str(path)


class FakeCoordinator:
    def __init__(self, store: FakeStore) -> None:
        self.store = store
        self.count = 0

    async def enqueue(self, _item):
        self.count += 1
        task_id = f"task-{self.count}"
        self.store.tasks[task_id] = SimpleNamespace(status=TaskStatus.QUEUED)
        return task_id


def test_incremental_scan_state_flow() -> None:
    plugin_class = _load_plugin_class()
    path = Path("/media/Movie.2026.strm")
    store = FakeStore()
    targets = FakeTargets(
        [
            FakeFile(path, 100, 1),
            FakeFile(path, 100, 1),
            FakeFile(path, 100, 1),
            FakeFile(path, 120, 2),
            FakeFile(path, 120, 2),
            FakeFile(path, 120, 2),
            FakeFile(path, 120, 2),
        ]
    )
    coordinator = FakeCoordinator(store)
    plugin = object.__new__(plugin_class)
    plugin._enabled = True
    plugin._history_scan_lock = asyncio.Lock()
    plugin.config = SimpleNamespace(custom_media_directories=("/media",), directory_monitor_enabled=True)
    plugin.targets = targets
    plugin.store = store
    plugin.coordinator = coordinator
    plugin.manual_search = None
    plugin.get_state = lambda: True

    async def run() -> None:
        first = await plugin.scan_custom_media_directories(automatic=True)
        assert first["submitted_count"] == 0
        assert first["pending_stability_count"] == 1

        targets.position = 1
        second = await plugin.scan_custom_media_directories(automatic=True)
        assert second["submitted_count"] == 1
        assert store.index[str(path.with_suffix(""))]["last_task_id"] == "task-1"

        store.tasks["task-1"].status = TaskStatus.SUCCESS
        targets.position = 2
        third = await plugin.scan_custom_media_directories(automatic=True)
        assert third["submitted_count"] == 0
        assert third["unchanged_count"] == 1

        targets.position = 3
        fourth = await plugin.scan_custom_media_directories(automatic=True)
        assert fourth["pending_stability_count"] == 1
        assert fourth["submitted_count"] == 0

        targets.position = 4
        fifth = await plugin.scan_custom_media_directories(automatic=True)
        assert fifth["submitted_count"] == 1
        store.tasks["task-2"].status = TaskStatus.FAILED

        targets.position = 5
        sixth = await plugin.scan_custom_media_directories(automatic=True)
        assert sixth["submitted_count"] == 0

        targets.position = 6
        seventh = await plugin.scan_custom_media_directories(automatic=False)
        assert seventh["retry_count"] == 1
        assert seventh["submitted_count"] == 1

        store.tasks["task-3"].status = TaskStatus.SUCCESS
        eighth = await plugin.scan_custom_media_directories(force=True)
        assert eighth["changed_count"] == 1
        assert eighth["unchanged_count"] == 0
        assert eighth["retry_count"] == 0
        assert eighth["submitted_count"] == 1

    asyncio.run(run())


def test_transfer_event_only_enqueues_local_target() -> None:
    plugin_class = _load_plugin_class()
    original_path = "/115open/recent/Show.S01E05.mkv"
    original_context = SimpleNamespace(
        target_path=original_path,
        target_storage="CloudDrive",
    )
    cloud_target = SimpleNamespace(path=original_path, storage="CloudDrive")
    local_path = "/media/tv/Show.S01E05.strm"
    local_context = SimpleNamespace(target_path=local_path, target_storage="local")
    local_target = SimpleNamespace(path=local_path, storage="local")

    class Coordinator:
        def __init__(self) -> None:
            self.items: list[TaskWorkItem] = []

        async def enqueue(self, item: TaskWorkItem) -> str:
            self.items.append(item)
            return f"task-{len(self.items)}"

    class Targets:
        def __init__(self) -> None:
            self.result = (original_context, cloud_target)

        async def resolve_runtime_target(self, _context, _target):
            return self.result

    coordinator = Coordinator()
    targets = Targets()
    plugin = object.__new__(plugin_class)
    plugin.coordinator = coordinator
    plugin.targets = targets
    plugin.get_state = lambda: True
    handler_globals = plugin_class.on_transfer_complete.__globals__
    original_builder = handler_globals["build_media_context"]
    handler_globals["build_media_context"] = lambda *_args: original_context
    event = SimpleNamespace(
        event_data={
            "transferinfo": SimpleNamespace(target_item=cloud_target),
            "transfer_history_id": "7378",
            "mediainfo": object(),
        }
    )

    async def run() -> None:
        await plugin.on_transfer_complete(event)
        assert coordinator.items == []

        targets.result = (local_context, local_target)
        await plugin.on_transfer_complete(event)
        assert len(coordinator.items) == 1
        assert coordinator.items[0].context is local_context
        assert coordinator.items[0].target is local_target
        assert coordinator.items[0].history_target_path == original_path
        assert coordinator.items[0].target_history_id == 7378

        local_event = SimpleNamespace(
            event_data={
                "transferinfo": SimpleNamespace(target_item=local_target),
                "transfer_history_id": 7379,
            }
        )
        handler_globals["build_media_context"] = lambda *_args: local_context
        targets.result = (local_context, local_target)
        await plugin.on_transfer_complete(local_event)
        assert len(coordinator.items) == 2
        assert coordinator.items[1].target is local_target
        assert coordinator.items[1].target_history_id == 7379

    try:
        asyncio.run(run())
    finally:
        handler_globals["build_media_context"] = original_builder


def test_store_upgrade_adds_scan_index_without_touching_existing_data() -> None:
    store_class = _load_store_class()

    class FakePlugin:
        def __init__(self) -> None:
            self.data = {
                "tasks": {"version": 2, "items": []},
                "records": {"version": 2, "items": []},
                "source_status": {"version": 2, "items": []},
                "credentials": {"version": 2, "items": {"assrt": {"token": "kept"}}},
            }

        def get_data(self, key):
            return self.data.get(key)

        def save_data(self, key, value):
            self.data[key] = value

    plugin = FakePlugin()
    existing = {key: dict(value) for key, value in plugin.data.items()}
    store = store_class(plugin)
    store.initialize()

    assert plugin.data["scan_index"] == {"version": 2, "items": {}}
    assert {key: plugin.data[key] for key in existing} == existing
    assert store.get_scan_index_sync() == {}
    assert store.get_credentials_sync(
        sys.modules["subtitledownloadassistant_store_test.domain.enums"].SubtitleSource.ASSRT
    ) == {"token": "kept"}


def test_store_clears_only_terminal_tasks() -> None:
    store_class = _load_store_class()
    enums = sys.modules["subtitledownloadassistant_store_test.domain.enums"]
    models = sys.modules["subtitledownloadassistant_store_test.domain.models"]

    class FakePlugin:
        def __init__(self) -> None:
            self.data: dict[str, object] = {}

        def get_data(self, key):
            return self.data.get(key)

        def save_data(self, key, value):
            self.data[key] = value

        async def async_save_data(self, key, value):
            self.data[key] = value

    plugin = FakePlugin()
    store = store_class(plugin)
    store.initialize()
    statuses = [
        enums.TaskStatus.QUEUED,
        enums.TaskStatus.PROCESSING,
        enums.TaskStatus.SUCCESS,
        enums.TaskStatus.SKIPPED,
        enums.TaskStatus.FAILED,
        enums.TaskStatus.INTERRUPTED,
    ]
    for index, status in enumerate(statuses):
        store.save_task_sync(
            models.SubtitleTask(
                id=f"task-{index}",
                media_title=f"媒体 {index}",
                target_file_name=f"media-{index}.strm",
                target_path=f"/media/media-{index}.strm",
                status=status,
            )
        )

    deleted_count = asyncio.run(store.delete_terminal_tasks())

    assert deleted_count == 4
    remaining = store.list_tasks_sync()
    assert {task.status for task in remaining} == {
        enums.TaskStatus.QUEUED,
        enums.TaskStatus.PROCESSING,
    }
    assert len(plugin.data["tasks"]["items"]) == 2


def test_store_deletes_only_selected_terminal_tasks() -> None:
    store_class = _load_store_class()
    enums = sys.modules["subtitledownloadassistant_store_test.domain.enums"]
    models = sys.modules["subtitledownloadassistant_store_test.domain.models"]

    class FakePlugin:
        def __init__(self) -> None:
            self.data: dict[str, object] = {}

        def get_data(self, key):
            return self.data.get(key)

        def save_data(self, key, value):
            self.data[key] = value

        async def async_save_data(self, key, value):
            self.data[key] = value

    plugin = FakePlugin()
    store = store_class(plugin)
    store.initialize()
    for task_id, status in (
        ("queued", enums.TaskStatus.QUEUED),
        ("success", enums.TaskStatus.SUCCESS),
        ("failed", enums.TaskStatus.FAILED),
        ("skipped", enums.TaskStatus.SKIPPED),
    ):
        store.save_task_sync(
            models.SubtitleTask(
                id=task_id,
                media_title=task_id,
                target_file_name=f"{task_id}.strm",
                target_path=f"/media/{task_id}.strm",
                status=status,
            )
        )

    deleted_count = asyncio.run(store.delete_terminal_tasks({"queued", "failed", "missing"}))

    assert deleted_count == 1
    assert {task.id for task in store.list_tasks_sync()} == {"queued", "success", "skipped"}


def test_task_batch_requests_reject_unsafe_status_groups() -> None:
    schemas = _load_api_schemas_module()
    enums = sys.modules["subtitledownloadassistant_store_test.domain.enums"]

    retry = schemas.TaskBatchRetryRequest(
        all_matching=True,
        statuses=[enums.TaskStatus.FAILED, enums.TaskStatus.SKIPPED],
    )
    assert retry.statuses == [enums.TaskStatus.FAILED, enums.TaskStatus.SKIPPED]

    delete = schemas.TaskBatchDeleteRequest(
        all_matching=True,
        statuses=[enums.TaskStatus.SUCCESS, enums.TaskStatus.INTERRUPTED],
    )
    assert delete.statuses == [enums.TaskStatus.SUCCESS, enums.TaskStatus.INTERRUPTED]

    for model, values in (
        (
            schemas.TaskBatchRetryRequest,
            {"all_matching": True, "statuses": [enums.TaskStatus.SUCCESS]},
        ),
        (
            schemas.TaskBatchDeleteRequest,
            {"all_matching": True, "statuses": [enums.TaskStatus.PROCESSING]},
        ),
        (
            schemas.TaskBatchDeleteRequest,
            {"task_ids": ["duplicate", "duplicate"]},
        ),
    ):
        try:
            model(**values)
        except ValueError:
            continue
        raise AssertionError(f"{model.__name__} should reject {values}")


def test_store_preserves_unrecovered_service_interruptions_during_bulk_save() -> None:
    store_class = _load_store_class()
    enums = sys.modules["subtitledownloadassistant_store_test.domain.enums"]
    models = sys.modules["subtitledownloadassistant_store_test.domain.models"]

    class FakePlugin:
        def __init__(self) -> None:
            self.data: dict[str, object] = {}

        def get_data(self, key):
            return self.data.get(key)

        def save_data(self, key, value):
            self.data[key] = value

        async def async_save_data(self, key, value):
            self.data[key] = value

    plugin = FakePlugin()
    store = store_class(plugin)
    store.initialize()
    interrupted = [
        models.SubtitleTask(
            id=f"interrupted-{index}",
            media_title=f"媒体 {index}",
            target_file_name=f"media-{index}.strm",
            target_path=f"/media/media-{index}.strm",
            status=enums.TaskStatus.INTERRUPTED,
            reason_code="service_interrupted",
            reason_message="服务重启前未完成",
        )
        for index in range(600)
    ]

    asyncio.run(store.save_tasks(interrupted))
    resumed = interrupted[0].model_copy(
        deep=True,
        update={
            "status": enums.TaskStatus.QUEUED,
            "reason_code": None,
            "reason_message": None,
        },
    )
    asyncio.run(store.save_tasks([resumed]))

    remaining = store.list_tasks_sync()
    assert len(remaining) == 600
    assert sum(task.status is enums.TaskStatus.INTERRUPTED for task in remaining) == 599
    assert sum(task.status is enums.TaskStatus.QUEUED for task in remaining) == 1
