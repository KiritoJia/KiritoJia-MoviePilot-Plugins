"""字幕下载助手 Bearer API 控制器。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import Body, Depends, HTTPException, Query
from pydantic import ValidationError

from app.db.models.user import User
from app.db.user_oper import (
    get_current_active_manage_user_async,
    get_current_active_superuser_async,
)
from app.schemas import Response

from ..application.record_deletion import (
    BatchDeleteRecordConfirmation,
    DeleteRecordConfirmation,
    RecordDeletionService,
)
from ..application.retargeting import RetargetMapping
from ..application.tasks import TaskWorkItem
from ..domain.enums import FileLocation, RecordStatus, SubtitleSource, TaskStatus, TaskTrigger
from ..domain.models import MatchRecord, SubtitleTask
from ..domain.query import assrt_title_queries
from .schemas import (
    BatchRecordDeletePreflightItem,
    BatchRecordDeleteRequest,
    BatchRecordDeleteResponse,
    BatchRecordDeleteResultItem,
    BatchRetargetPreviewItem,
    BatchRetargetPreviewRequest,
    BatchRetargetPreviewResponse,
    BatchRetargetResponse,
    BatchRetargetResultItem,
    BatchRetargetSubmitRequest,
    CredentialUpdate,
    CustomDirectoryScanResponse,
    ManualCandidateItem,
    ManualDownloadRequest,
    ManualDownloadResponse,
    ManualSearchRequest,
    ManualSearchResponse,
    ManualSourceResult,
    PageSize,
    RecordDeleteRequest,
    RecordDetail,
    RecordListItem,
    RecordPage,
    RetargetPreviewResponse,
    RetargetRequest,
    SourceStatusItem,
    TargetListItem,
    TargetPage,
    TaskBatchDeleteRequest,
    TaskBatchDeleteResponse,
    TaskBatchRetryRequest,
    TaskBatchRetryResponse,
    TaskDetail,
    TaskClearResponse,
    TaskListItem,
    TaskPage,
)

CredentialSource = Literal["opensubtitles", "assrt", "subhd"]


class ApiController:
    """把应用服务结果转换为固定插件 API 契约。"""

    def __init__(self, plugin: Any) -> None:
        """创建绑定到当前插件实例的 API 控制器。"""

        self._plugin = plugin
        self._record_deletion: RecordDeletionService | None = None

    def _get_record_deletion_service(self) -> RecordDeletionService:
        """按当前插件运行态懒加载匹配记录删除服务。"""

        if self._record_deletion is None:
            self._record_deletion = RecordDeletionService(
                store=self._plugin.store,
                filesystem=self._plugin.filesystem,
                inventory=self._plugin.inventory,
                mutation_lock=getattr(self._plugin, "record_mutation_lock", None),
            )
        return self._record_deletion

    async def _current_record_file_path(self, record: MatchRecord) -> str:
        """返回记录当前字幕文件的完整服务端路径。"""

        if record.location is FileLocation.MEDIA_DIRECTORY:
            return record.path
        resolver = getattr(self._plugin.filesystem, "plugin_file_path", None)
        if not callable(resolver):
            return record.path
        try:
            return str(await resolver(record.path))
        except (OSError, ValueError):
            # 历史损坏记录仍应能列出并由后端安全拒绝文件操作；此时保留原值
            # 供用户定位数据问题，不尝试自行拼接未经校验的路径。
            return record.path

    async def _record_list_item(self, record: MatchRecord) -> RecordListItem:
        """把记录转换为包含完整当前文件路径的列表模型。"""

        item = RecordListItem.model_validate(record)
        return item.model_copy(update={"current_file_path": await self._current_record_file_path(record)})

    async def _record_detail(self, record: MatchRecord) -> RecordDetail:
        """把记录转换为包含完整当前文件路径的详情模型。"""

        detail = RecordDetail.model_validate(record)
        return detail.model_copy(update={"current_file_path": await self._current_record_file_path(record)})

    @staticmethod
    def _timestamp(value: datetime | None) -> float:
        """返回可排序的 UTC 时间戳。"""

        return (value or datetime.min.replace(tzinfo=UTC)).timestamp()

    @staticmethod
    def _task_search_text(task: SubtitleTask) -> str:
        """拼接任务固定全文搜索字段。"""

        season_episode = ""
        if task.season is not None:
            season_episode += f"S{task.season:02d}"
        if task.episode is not None:
            season_episode += f"E{task.episode:02d}"
        return " ".join(
            str(value or "")
            for value in (
                task.media_title,
                task.year,
                season_episode,
                task.target_file_name,
                task.target_path,
                task.reason_code,
                task.reason_message,
            )
        ).casefold()

    @classmethod
    def _task_sort_key(cls, task: SubtitleTask) -> tuple[int, float]:
        """返回处理中、等待中、终态三组固定排序键。"""

        if task.status is TaskStatus.PROCESSING:
            return 0, cls._timestamp(task.started_at or task.created_at)
        if task.status is TaskStatus.QUEUED:
            return 1, cls._timestamp(task.created_at)
        return 2, -cls._timestamp(task.finished_at or task.created_at)

    @staticmethod
    def _record_search_text(
        record: MatchRecord,
        current_file_path: str | None = None,
    ) -> str:
        """拼接匹配记录固定全文搜索字段。"""

        season_episode = ""
        if record.season is not None:
            season_episode += f"S{record.season:02d}"
        if record.episode is not None:
            season_episode += f"E{record.episode:02d}"
        return " ".join(
            str(value or "")
            for value in (
                record.subtitle_file_name,
                record.media_title,
                record.year,
                season_episode,
                record.source.value,
                record.path,
                current_file_path,
            )
        ).casefold()

    async def list_tasks(
        self,
        page: int = Query(default=1, ge=1),
        page_size: PageSize = Query(default=PageSize.ITEMS_25),  # noqa: B008 - FastAPI 查询参数注入
        search: str | None = Query(default=None),
        status: TaskStatus | None = Query(default=None),  # noqa: B008 - FastAPI 查询参数注入
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> TaskPage:
        """分页查询字幕任务安全摘要。"""

        tasks = await self._plugin.store.list_tasks()
        query = (search or "").strip().casefold()
        if query:
            tasks = [task for task in tasks if query in self._task_search_text(task)]
        status_counts = {
            item_status: sum(1 for task in tasks if task.status is item_status)
            for item_status in TaskStatus
        }
        if status is not None:
            tasks = [task for task in tasks if task.status is status]
        tasks.sort(key=self._task_sort_key)
        total = len(tasks)
        start = (page - 1) * page_size
        items = [TaskListItem.model_validate(task) for task in tasks[start : start + page_size]]
        return TaskPage(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            status_counts=status_counts,
        )

    async def get_task(
        self,
        task_id: str,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> TaskDetail:
        """查询单个字幕任务详情。"""

        task = await self._plugin.store.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return TaskDetail.model_validate(task)

    async def delete_task(
        self,
        task_id: str,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> Response:
        """删除一个终态任务历史。"""

        task = await self._plugin.store.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if not task.is_terminal:
            raise HTTPException(status_code=409, detail="运行中的任务不能删除")
        await self._plugin.store.delete_task(task_id)
        return Response(success=True, message="任务记录已删除")

    async def clear_terminal_tasks(
        self,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> TaskClearResponse:
        """一次清理全部终态任务，不影响当前运行队列。"""

        deleted_count = await self._plugin.store.delete_terminal_tasks()
        remaining = await self._plugin.store.list_tasks()
        active_count = sum(1 for task in remaining if not task.is_terminal)
        message = (
            f"已清理 {deleted_count} 条已结束任务"
            if deleted_count
            else "没有需要清理的已结束任务"
        )
        return TaskClearResponse(
            message=message,
            deleted_count=deleted_count,
            active_count=active_count,
        )

    async def scan_custom_directories(
        self,
        full: bool = Query(default=False),  # noqa: B008 - FastAPI 查询参数注入
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> CustomDirectoryScanResponse:
        """扫描已保存目录；可显式忽略索引并重新处理全部媒体。"""

        try:
            result = await self._plugin.scan_custom_media_directories(force=full)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        matched_count = int(result["matched_count"])
        submitted_count = int(result["submitted_count"])
        if submitted_count:
            message = (
                f"全量重新扫描已提交或合并 {submitted_count} 个字幕任务"
                if full
                else f"已从自定义目录提交或合并 {submitted_count} 个字幕任务"
            )
        elif matched_count:
            message = (
                "全量重新扫描目标均已在处理队列中"
                if full
                else "新增或变更的媒体任务均已在处理队列中"
            )
        elif full and result["indexed_file_count"]:
            message = "全量重新扫描未生成可处理的媒体目标"
        elif result["indexed_file_count"]:
            message = "没有发现新增或变更的媒体文件"
        else:
            message = "自定义目录中没有找到支持的视频或 STRM 文件"
        return CustomDirectoryScanResponse(message=message, **result)

    async def retry_task(
        self,
        task_id: str,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> Response:
        """从终态任务快照创建一条新的自动字幕任务。"""

        task = await self._plugin.store.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.status not in {TaskStatus.SKIPPED, TaskStatus.FAILED, TaskStatus.INTERRUPTED}:
            raise HTTPException(status_code=409, detail="只有已跳过、失败或已中断的任务可以重新运行")
        if self._plugin.targets is None or self._plugin.coordinator is None:
            raise HTTPException(status_code=409, detail="字幕下载助手当前未启用")

        target = self._plugin.targets.retry_target(task)
        if self._plugin.manual_search is not None:
            target = await self._plugin.manual_search.enrich_target(target)
        new_task_id = await self._plugin.coordinator.enqueue(
            TaskWorkItem(
                context=target.context,
                target=target.target_item,
                host_mediainfo=target.host_mediainfo,
                trigger=TaskTrigger.RETRY,
                history_target_path=target.history_target_path,
                target_history_id=target.history_id,
            )
        )
        if new_task_id is None:
            raise HTTPException(status_code=409, detail="插件正在停止，暂时不能重新运行任务")
        return Response(
            success=True,
            message="已重新提交任务；同路径已有运行任务时将自动合并",
            data={"task_id": new_task_id, "original_task_id": task.id},
        )

    async def retry_tasks_batch(
        self,
        payload: TaskBatchRetryRequest = Body(...),  # noqa: B008 - FastAPI 请求体注入
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> TaskBatchRetryResponse:
        """原地重置选中或符合当前搜索分组的可重试任务。"""

        if self._plugin.targets is None or self._plugin.coordinator is None:
            raise HTTPException(status_code=409, detail="字幕下载助手当前未启用")

        tasks = await self._plugin.store.list_tasks()
        missing_count = 0
        if payload.all_matching:
            query = (payload.search or "").strip().casefold()
            requested_statuses = set(payload.statuses)
            matched = [
                task
                for task in tasks
                if task.status in requested_statuses
                and (not query or query in self._task_search_text(task))
            ]
            matched.sort(
                key=lambda task: self._timestamp(task.finished_at or task.created_at),
                reverse=True,
            )
            requested_count = len(matched)
        else:
            tasks_by_id = {task.id: task for task in tasks}
            matched = [tasks_by_id[task_id] for task_id in payload.task_ids if task_id in tasks_by_id]
            missing_count = len(payload.task_ids) - len(matched)
            requested_count = len(payload.task_ids)

        retryable = {TaskStatus.SKIPPED, TaskStatus.FAILED, TaskStatus.INTERRUPTED}
        eligible = [task for task in matched if task.status in retryable]
        skipped_count = len(matched) - len(eligible)
        entries: list[tuple[SubtitleTask, TaskWorkItem]] = []
        error_count = 0
        for task in eligible:
            try:
                target = self._plugin.targets.retry_target(task)
                entries.append(
                    (
                        task,
                        TaskWorkItem(
                            context=target.context,
                            target=target.target_item,
                            host_mediainfo=target.host_mediainfo,
                            trigger=TaskTrigger.RETRY,
                            history_target_path=target.history_target_path,
                            target_history_id=target.history_id,
                        ),
                    )
                )
            except (OSError, TypeError, ValueError, ValidationError):
                error_count += 1

        result = await self._plugin.coordinator.resume_interrupted(entries)
        if entries and not result.accepting:
            raise HTTPException(status_code=409, detail="插件正在停止，暂时不能恢复任务")

        submitted_count = len(result.resumed_task_ids)
        parts: list[str] = []
        if submitted_count:
            parts.append(f"已重新运行 {submitted_count} 条任务并加入受限队列")
        else:
            parts.append("没有新的可重试任务需要加入队列")
        if result.merged_count:
            parts.append(f"同路径运行任务合并 {result.merged_count} 条")
        if skipped_count:
            parts.append(f"状态已变化跳过 {skipped_count} 条")
        if missing_count:
            parts.append(f"任务不存在 {missing_count} 条")
        if error_count:
            parts.append(f"目标重建失败 {error_count} 条")

        return TaskBatchRetryResponse(
            message="；".join(parts),
            requested_count=requested_count,
            matched_count=len(matched),
            eligible_count=len(eligible),
            submitted_count=submitted_count,
            merged_count=result.merged_count,
            skipped_count=skipped_count,
            missing_count=missing_count,
            error_count=error_count,
        )

    async def delete_tasks_batch(
        self,
        payload: TaskBatchDeleteRequest = Body(...),  # noqa: B008 - FastAPI 请求体注入
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> TaskBatchDeleteResponse:
        """一次删除选中或符合当前搜索分组的终态任务。"""

        tasks = await self._plugin.store.list_tasks()
        missing_count = 0
        if payload.all_matching:
            query = (payload.search or "").strip().casefold()
            requested_statuses = set(payload.statuses)
            matched = [
                task
                for task in tasks
                if task.status in requested_statuses
                and (not query or query in self._task_search_text(task))
            ]
            requested_count = len(matched)
        else:
            tasks_by_id = {task.id: task for task in tasks}
            matched = [tasks_by_id[task_id] for task_id in payload.task_ids if task_id in tasks_by_id]
            missing_count = len(payload.task_ids) - len(matched)
            requested_count = len(payload.task_ids)

        eligible = [task for task in matched if task.is_terminal]
        deleted_count = await self._plugin.store.delete_terminal_tasks({task.id for task in eligible})
        skipped_count = len(matched) - deleted_count
        remaining = await self._plugin.store.list_tasks()
        active_count = sum(1 for task in remaining if not task.is_terminal)
        parts = [
            f"已删除 {deleted_count} 条任务记录"
            if deleted_count
            else "没有可删除的终态任务"
        ]
        if skipped_count:
            parts.append(f"状态已变化跳过 {skipped_count} 条")
        if missing_count:
            parts.append(f"任务不存在 {missing_count} 条")
        return TaskBatchDeleteResponse(
            message="；".join(parts),
            requested_count=requested_count,
            matched_count=len(matched),
            deleted_count=deleted_count,
            skipped_count=skipped_count,
            missing_count=missing_count,
            active_count=active_count,
        )

    async def list_records(
        self,
        page: int = Query(default=1, ge=1),
        page_size: PageSize = Query(default=PageSize.ITEMS_25),  # noqa: B008 - FastAPI 查询参数注入
        search: str | None = Query(default=None),
        status: RecordStatus | None = Query(default=None),  # noqa: B008 - FastAPI 查询参数注入
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> RecordPage:
        """分页查询字幕匹配记录。"""

        records = await self._plugin.store.list_records()
        if status is not None:
            records = [record for record in records if record.status is status]
        query = (search or "").strip().casefold()
        if query:
            matched_records: list[MatchRecord] = []
            for record in records:
                current_file_path = await self._current_record_file_path(record)
                if query in self._record_search_text(record, current_file_path):
                    matched_records.append(record)
            records = matched_records
        records.sort(key=lambda record: record.updated_at, reverse=True)
        total = len(records)
        start = (page - 1) * page_size
        items = [await self._record_list_item(record) for record in records[start : start + page_size]]
        return RecordPage(items=items, total=total, page=page, page_size=page_size)

    async def get_record(
        self,
        record_id: str,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> RecordDetail:
        """查询单个字幕匹配记录详情。"""

        record = await self._plugin.store.get_record(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="匹配记录不存在")
        return await self._record_detail(record)

    async def delete_record(
        self,
        record_id: str,
        payload: RecordDeleteRequest = Body(...),  # noqa: B008 - FastAPI 请求体注入
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> Response:
        """按用户确认版本删除匹配记录及可选字幕文件。"""

        if not isinstance(payload, RecordDeleteRequest):
            try:
                payload = RecordDeleteRequest.model_validate(payload)
            except ValidationError as exc:
                raise HTTPException(status_code=422, detail=exc.errors()) from exc
        try:
            result = await self._get_record_deletion_service().delete(
                record_id,
                DeleteRecordConfirmation(
                    delete_mode=payload.delete_mode,
                    expected_status=payload.expected_status,
                    expected_location=payload.expected_location,
                    expected_path=payload.expected_path,
                    expected_updated_at=payload.expected_updated_at,
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail="匹配记录删除失败") from exc

        if result.error_code == "record_not_found":
            raise HTTPException(status_code=404, detail=result.message or "匹配记录不存在")
        if result.error_code in {"record_version_conflict", "delete_mode_not_allowed"}:
            raise HTTPException(
                status_code=409,
                detail={"code": result.error_code, "message": result.message or "当前记录不能删除"},
            )
        if not result.success:
            raise HTTPException(
                status_code=500,
                detail={
                    "code": result.error_code or "record_delete_failed",
                    "message": result.message or "匹配记录删除失败",
                    "consistency_risk": result.consistency_risk,
                },
            )
        message = (
            "匹配记录已删除，字幕文件已保留" if payload.delete_mode == "record_only" else "匹配记录及当前字幕文件已删除"
        )
        return Response(success=True, message=message)

    async def delete_records_batch(
        self,
        payload: BatchRecordDeleteRequest,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> BatchRecordDeleteResponse:
        """整批预检后按请求顺序删除多条匹配记录。"""

        try:
            result = await self._get_record_deletion_service().delete_batch(
                [
                    BatchDeleteRecordConfirmation(
                        record_id=item.record_id,
                        confirmation=DeleteRecordConfirmation(
                            delete_mode=payload.delete_mode,
                            expected_status=item.expected_status,
                            expected_location=item.expected_location,
                            expected_path=item.expected_path,
                            expected_updated_at=item.expected_updated_at,
                        ),
                    )
                    for item in payload.items
                ],
                payload.delete_mode,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail="批量删除匹配记录失败") from exc

        if not result.started:
            preflight_items = [
                BatchRecordDeletePreflightItem(
                    record_id=item.record_id,
                    executable=item.executable,
                    error_code=item.error_code,
                    message=item.message,
                )
                for item in result.preflight.items
            ]
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "batch_preflight_failed",
                    "message": "批量删除预检未通过",
                    "items": [item.model_dump(mode="json") for item in preflight_items],
                },
            )
        return BatchRecordDeleteResponse(
            success_count=result.success_count,
            failure_count=result.failure_count,
            not_executed_count=result.not_executed_count,
            items=[
                BatchRecordDeleteResultItem(
                    record_id=item.record_id,
                    status=item.status,
                    error_code=item.error_code,
                    message=item.message,
                    consistency_risk=item.consistency_risk,
                )
                for item in result.items
            ],
        )

    @staticmethod
    def _target_item(target: Any) -> TargetListItem:
        """把整理历史目标转换为前端安全模型。"""

        context = target.context
        assrt_first, assrt_second = assrt_title_queries(context)
        media_id = context.imdb_id or (str(context.tmdb_id) if context.tmdb_id else None)
        plans = {
            "moviepilot": [
                {
                    "kind": "title",
                    "label": "英文标题关键词（搜索时生成）",
                    "query": None,
                    "editable": False,
                }
            ],
            "opensubtitles": [
                {"kind": "id", "label": "媒体 ID", "query": media_id, "editable": False},
                {
                    "kind": "title",
                    "label": "英文标题" if context.english_title else "英文标题（搜索时补充）",
                    "query": context.english_title,
                    "editable": bool(context.english_title),
                },
            ],
            "assrt": [
                {"kind": "title", "label": "主标题", "query": assrt_first, "editable": True},
                {"kind": "fallback", "label": "英文名/原名", "query": assrt_second, "editable": True},
            ],
        }
        return TargetListItem(
            history_id=target.history_id,
            media_title=context.title,
            year=context.year,
            media_type=context.media_type,
            season=context.season,
            episode=context.episode,
            tmdb_id=context.tmdb_id,
            imdb_id=context.imdb_id,
            target_file_name=context.target_file_name,
            target_path=context.target_path,
            organized_at=target.transferred_at,
            search_plans=plans,
        )

    @staticmethod
    def _manual_default_plans(source: SubtitleSource, queries: list[str]) -> list[dict[str, Any]]:
        """把来源实际默认查询转换为前端可编辑方案。"""

        plans: list[dict[str, Any]] = []
        for index, query in enumerate(queries):
            if source is SubtitleSource.MOVIEPILOT:
                kind, label, editable = "title", f"英文关键词 {index + 1}", True
            elif source is SubtitleSource.OPENSUBTITLES and query.startswith(("IMDb ID:", "TMDB ID:")):
                kind, label, editable = "id", "媒体 ID", False
            elif source is SubtitleSource.OPENSUBTITLES:
                kind, label, editable = "title", "英文标题", True
            elif source is SubtitleSource.SHOOTER:
                kind, label, editable = "fingerprint", "视频内容指纹", True
            elif source in {SubtitleSource.THUNDER, SubtitleSource.SUBHD}:
                kind, label, editable = "filename", "媒体文件名", True
            elif index == 0:
                kind, label, editable = "title", "中文标题", True
            else:
                kind, label, editable = "fallback", "英文标题/原名", True
            plans.append(
                {
                    "kind": kind,
                    "label": label,
                    "query": query,
                    "editable": editable,
                }
            )
        return plans

    @staticmethod
    def _candidate_item(candidate: Any, query: str | None) -> ManualCandidateItem:
        """把领域候选转换为不含下载定位的人工搜索 DTO。"""

        allowed = {
            SubtitleSource.MOVIEPILOT: {"site_name", "description"},
            SubtitleSource.OPENSUBTITLES: {"release", "media_id"},
            SubtitleSource.ASSRT: {"videoname", "native_name"},
            SubtitleSource.SHOOTER: {"native_name", "content_hash_match"},
            SubtitleSource.THUNDER: {"native_name", "content_hash_match"},
            SubtitleSource.SUBHD: {"release", "description"},
        }[candidate.source]
        details = {key: value for key, value in candidate.metadata.items() if key in allowed}
        if candidate.source is SubtitleSource.MOVIEPILOT:
            details["site_priority"] = candidate.site_priority
        elif candidate.source is SubtitleSource.OPENSUBTITLES:
            details["trusted"] = candidate.trusted
        elif candidate.source is SubtitleSource.ASSRT:
            details["revision"] = candidate.revision
        elif candidate.source in {SubtitleSource.SHOOTER, SubtitleSource.THUNDER}:
            details["hash_match"] = bool(candidate.metadata.get("content_hash_match"))
        return ManualCandidateItem(
            candidate_key=candidate.stable_key,
            source=candidate.source,
            name=candidate.name,
            file_name=candidate.file_name,
            language=candidate.language or None,
            format=candidate.format or None,
            package_scope=candidate.package_scope,
            season=candidate.season,
            episode=candidate.episode,
            seasons=list(candidate.seasons),
            episodes=list(candidate.episodes),
            translation_type=candidate.translation_type,
            hearing_impaired=candidate.hearing_impaired,
            rating=candidate.score,
            votes=candidate.votes,
            downloads=candidate.download_count,
            uploaded_at=candidate.uploaded_at,
            query=query,
            source_details=details,
        )

    async def list_targets(
        self,
        page: int = Query(default=1, ge=1),
        page_size: PageSize = Query(default=PageSize.ITEMS_25),  # noqa: B008 - FastAPI 查询参数注入
        search: str | None = Query(default=None),
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> TargetPage:
        """分页查询可供人工搜索和改配的整理目标。"""

        result = await self._plugin.targets.list_targets(page=page, page_size=int(page_size), search=search)
        return TargetPage(
            items=[self._target_item(item) for item in result.items],
            total=result.total,
            page=result.page,
            page_size=page_size,
        )

    async def search_subtitles(
        self,
        payload: ManualSearchRequest,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> ManualSearchResponse:
        """并发执行全部来源的人工字幕搜索。"""

        try:
            result = await self._plugin.manual_search.search(
                int(payload.target_history_id),
                {
                    SubtitleSource.MOVIEPILOT: payload.moviepilot_keyword,
                    SubtitleSource.OPENSUBTITLES: payload.opensubtitles_keyword,
                    SubtitleSource.ASSRT: payload.assrt_keyword,
                    SubtitleSource.SHOOTER: payload.shooter_keyword,
                    SubtitleSource.THUNDER: payload.thunder_keyword,
                    SubtitleSource.SUBHD: payload.subhd_keyword,
                },
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        target = self._target_item(result.target)
        sources = [
            ManualSourceResult(
                source=run.source,
                status=run.status,
                default_plans=self._manual_default_plans(run.source, run.default_queries),
                executed_queries=run.executed_queries,
                matched_query=run.matched_query,
                candidate_count=len(run.candidates),
                duration_ms=run.duration_ms,
                error_summary=run.error_summary,
                details=dict(run.details),
                candidates=[self._candidate_item(item, run.matched_query) for item in run.candidates],
            )
            for run in result.sources
        ]
        return ManualSearchResponse(session_id=result.session_id, target=target, sources=sources)

    async def download_search_candidate(
        self,
        session_id: str,
        payload: ManualDownloadRequest,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> ManualDownloadResponse:
        """把人工选定候选提交到现有 worker 池。"""

        candidate = await self._plugin.manual_search.get_candidate(session_id, payload.candidate_key)
        if candidate is None:
            raise HTTPException(status_code=404, detail="搜索会话已过期或候选不存在")
        task_id, reused = await self._plugin.coordinator.enqueue_manual(
            TaskWorkItem(
                context=candidate.target.context,
                target=candidate.target.target_item,
                host_mediainfo=candidate.target.host_mediainfo,
                history_target_path=candidate.target.history_target_path,
                manual_handle=candidate.handle,
                manual_session_id=session_id,
                actual_search_query=candidate.actual_query,
                target_history_id=candidate.target.history_id,
            )
        )
        if task_id is None:
            raise HTTPException(status_code=409, detail="插件当前不接受新任务")
        task = await self._plugin.store.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=500, detail="人工字幕任务创建失败")
        return ManualDownloadResponse(task_id=task_id, reused=reused, task=TaskListItem.model_validate(task))

    async def preview_retarget_record(
        self,
        record_id: str,
        payload: RetargetRequest,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> RetargetPreviewResponse:
        """按当前路径映射预览改配结果。"""

        result = await self._plugin.retargeting.preview(record_id, int(payload.target_history_id))
        if result.success and result.preview is not None:
            return RetargetPreviewResponse.model_validate(result.preview)
        status = 404 if result.error_code in {"record_not_found", "target_not_found"} else 409
        raise HTTPException(
            status_code=status,
            detail={
                "code": result.error_code or "retarget_preview_failed",
                "message": result.message or "改配预览失败",
            },
        )

    async def retarget_record(
        self,
        record_id: str,
        payload: RetargetRequest,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> RecordDetail:
        """把现有匹配记录改配到新的整理目标。"""

        result = await self._plugin.retargeting.retarget(record_id, int(payload.target_history_id))
        if result.success and result.record is not None:
            return await self._record_detail(result.record)
        status = 404 if result.error_code in {"record_not_found", "target_not_found"} else 409
        if result.error_code == "file_operation_failed":
            status = 500
        error_code = result.error_code or "retarget_failed"
        message = result.message or "改配目标失败"
        if result.consistency_risk:
            status = 500
            error_code = "retarget_consistency_risk"
            message = "改配失败且回滚未完整完成，文件与记录可能不一致，请检查后重试"
        raise HTTPException(
            status_code=status,
            detail={
                "code": error_code,
                "message": message,
                "consistency_risk": result.consistency_risk,
            },
        )

    def _batch_preview_response(self, result: Any) -> BatchRetargetPreviewResponse:
        """把领域批量预检结果转换为前端安全响应。"""

        return BatchRetargetPreviewResponse(
            executable=result.executable,
            items=[
                BatchRetargetPreviewItem(
                    record_id=item.record_id,
                    current_subtitle_path=item.current_subtitle_path,
                    target_history_id=item.target_history_id,
                    target=self._target_item(item.target) if item.target is not None else None,
                    preview=RetargetPreviewResponse.model_validate(item.preview) if item.preview is not None else None,
                    executable=item.executable,
                    error_code=item.error_code,
                    message=item.message,
                )
                for item in result.items
            ],
        )

    async def preview_batch_retarget_records(
        self,
        payload: BatchRetargetPreviewRequest,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> BatchRetargetPreviewResponse:
        """自动建议目标并预检一批匹配记录改配。"""

        result = await self._plugin.retargeting.preview_batch(
            [
                RetargetMapping(
                    record_id=item.record_id,
                    target_history_id=item.target_history_id,
                )
                for item in payload.items
            ]
        )
        return self._batch_preview_response(result)

    async def retarget_batch_records(
        self,
        payload: BatchRetargetSubmitRequest,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> BatchRetargetResponse:
        """整体预检后逐条独立执行一批匹配记录改配。"""

        result = await self._plugin.retargeting.retarget_batch(
            [
                RetargetMapping(
                    record_id=item.record_id,
                    target_history_id=item.target_history_id,
                )
                for item in payload.items
            ]
        )
        if not result.started:
            preview = self._batch_preview_response(result.preflight)
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "batch_preflight_failed",
                    "message": "批量改配预检未通过",
                    **preview.model_dump(mode="json"),
                },
            )
        response_items: list[BatchRetargetResultItem] = []
        for item in result.items:
            consistency_risk = item.result.consistency_risk
            response_items.append(
                BatchRetargetResultItem(
                    record_id=item.record_id,
                    target_history_id=item.target_history_id,
                    success=item.result.success,
                    error_code=("retarget_consistency_risk" if consistency_risk else item.result.error_code),
                    message=(
                        "改配失败且回滚未完整完成，文件与记录可能不一致，请检查后重试"
                        if consistency_risk
                        else item.result.message
                    ),
                    consistency_risk=consistency_risk,
                    record=(await self._record_detail(item.result.record) if item.result.record is not None else None),
                )
            )
        return BatchRetargetResponse(
            success_count=result.success_count,
            failure_count=result.failure_count,
            items=response_items,
        )

    async def source_statuses(
        self,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> list[SourceStatusItem]:
        """读取全部字幕源的最近状态，不主动发起请求。"""

        statuses = {item.source: item for item in await self._plugin.store.list_source_statuses()}
        return [SourceStatusItem.model_validate(statuses[source]) for source in SubtitleSource if source in statuses]

    async def refresh_sources(
        self,
        _: User = Depends(get_current_active_manage_user_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> Response:
        """并发刷新全部字幕源状态。"""

        try:
            await self._plugin.coordinator.refresh_sources(manual=True)
        except asyncio.CancelledError:
            return Response(success=False, message="字幕源状态刷新已中断")
        except Exception:  # noqa: BLE001 - 来源刷新必须收敛运行时失败
            return Response(success=False, message="字幕源状态刷新失败")
        return Response(success=True, message="字幕源状态已刷新")

    async def update_credentials(
        self,
        source: CredentialSource,
        payload: CredentialUpdate,
        _: User = Depends(get_current_active_superuser_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> Response:
        """增量写入外部字幕源长期凭据且不回显秘密。"""

        values = payload.cleaned()
        allowed_fields = {
            "opensubtitles": {"api_key", "username", "password"},
            "assrt": {"token"},
            "subhd": {"email", "password"},
        }[source]
        if set(values) - allowed_fields:
            raise HTTPException(status_code=422, detail="请求包含不属于该字幕源的凭据字段")
        configured = await self._plugin.update_source_credentials(SubtitleSource(source), values)
        return Response(success=True, message="凭据已更新", data={"configured": configured})

    async def clear_credentials(
        self,
        source: CredentialSource,
        _: User = Depends(get_current_active_superuser_async),  # noqa: B008 - FastAPI 依赖注入
    ) -> Response:
        """删除外部字幕源凭据并立即关闭对应来源。"""

        success = await self._plugin.clear_source_credentials(SubtitleSource(source))
        if not success:
            return Response(success=False, message="凭据已删除，但来源开关保存失败")
        return Response(success=True, message="字幕源凭据已清除", data={"configured": False})

    def routes(self) -> list[dict[str, Any]]:
        """每次返回全新的 Bearer 路由定义。"""

        definitions = [
            ("/tasks", self.list_tasks, ["GET"], TaskPage, "查询字幕任务"),
            (
                "/tasks/terminal",
                self.clear_terminal_tasks,
                ["DELETE"],
                TaskClearResponse,
                "清理全部已结束任务",
            ),
            (
                "/tasks/scan-custom-directories",
                self.scan_custom_directories,
                ["POST"],
                CustomDirectoryScanResponse,
                "扫描或全量重新扫描自定义媒体目录",
            ),
            (
                "/tasks/retry-batch",
                self.retry_tasks_batch,
                ["POST"],
                TaskBatchRetryResponse,
                "批量重新运行终态字幕任务",
            ),
            (
                "/tasks/delete-batch",
                self.delete_tasks_batch,
                ["POST"],
                TaskBatchDeleteResponse,
                "批量删除终态字幕任务",
            ),
            ("/tasks/{task_id}/retry", self.retry_task, ["POST"], Response, "重新运行终态字幕任务"),
            ("/tasks/{task_id}", self.get_task, ["GET"], TaskDetail, "查询字幕任务详情"),
            ("/tasks/{task_id}", self.delete_task, ["DELETE"], Response, "删除字幕任务记录"),
            ("/records", self.list_records, ["GET"], RecordPage, "查询字幕匹配记录"),
            (
                "/records/batch-delete",
                self.delete_records_batch,
                ["POST"],
                BatchRecordDeleteResponse,
                "批量删除字幕匹配记录",
            ),
            ("/records/{record_id}", self.get_record, ["GET"], RecordDetail, "查询字幕匹配记录详情"),
            ("/records/{record_id}", self.delete_record, ["DELETE"], Response, "删除字幕匹配记录"),
            ("/targets", self.list_targets, ["GET"], TargetPage, "查询可选整理目标"),
            ("/searches", self.search_subtitles, ["POST"], ManualSearchResponse, "人工搜索字幕"),
            (
                "/searches/{session_id}/downloads",
                self.download_search_candidate,
                ["POST"],
                ManualDownloadResponse,
                "提交人工字幕下载",
            ),
            (
                "/records/batch-retarget-preview",
                self.preview_batch_retarget_records,
                ["POST"],
                BatchRetargetPreviewResponse,
                "预览批量字幕改配目标",
            ),
            (
                "/records/batch-retarget",
                self.retarget_batch_records,
                ["POST"],
                BatchRetargetResponse,
                "批量改配字幕目标",
            ),
            (
                "/records/{record_id}/retarget-preview",
                self.preview_retarget_record,
                ["POST"],
                RetargetPreviewResponse,
                "预览字幕改配目标",
            ),
            ("/records/{record_id}/retarget", self.retarget_record, ["POST"], RecordDetail, "改配字幕目标"),
            ("/sources/status", self.source_statuses, ["GET"], list[SourceStatusItem], "查询字幕源状态"),
            ("/sources/refresh", self.refresh_sources, ["POST"], Response, "刷新字幕源状态"),
            ("/credentials/{source}", self.update_credentials, ["PUT"], Response, "更新字幕源凭据"),
            ("/credentials/{source}", self.clear_credentials, ["DELETE"], Response, "清除字幕源凭据"),
        ]
        return [
            {
                "path": path,
                "endpoint": endpoint,
                "methods": methods,
                "auth": "bear",
                "response_model": response_model,
                "summary": summary,
            }
            for path, endpoint, methods, response_model, summary in definitions
        ]
