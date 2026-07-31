"""可选目标查询与人工字幕搜索会话服务。"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.chain.media import MediaChain
from app.core.cache import AsyncMemoryBackend
from app.core.context import MediaInfo as HostMediaInfo
from app.core.metainfo import MetaInfoPath
from app.db.transferhistory_oper import TransferHistoryOper
from app.log import logger
from app.schemas import FileItem
from app.schemas.types import MediaType as HostMediaType

from ..domain.enums import MediaType, SubtitleSource
from ..domain.language import candidate_chinese_priority
from ..domain.models import MediaContext, SubtitleCandidate, new_id
from .path_mapping import PathMapping, resolve_path
from .ports import CandidateHandle, ManualSourceSearchResult, SubtitleSourcePort
from .source_gate import SourceConcurrencyGate

SEARCH_SESSION_REGION = "subtitledownloadassistant_manual_search"
SEARCH_SESSION_TTL_SECONDS = 30 * 60

SOURCE_NAMES = {
    SubtitleSource.MOVIEPILOT: "MoviePilot 站点字幕源",
    SubtitleSource.OPENSUBTITLES: "OpenSubtitles",
    SubtitleSource.ASSRT: "ASSRT",
    SubtitleSource.SHOOTER: "射手网",
    SubtitleSource.THUNDER: "迅雷影音",
}

QUERY_TYPE_NAMES = {
    "media_id": "媒体 ID",
    "english_title": "英文标题",
    "custom": "自定义关键词",
    "keyword": "英文标题关键词",
    "filename": "文件名",
    "content_fingerprint": "内容指纹",
}


@dataclass(slots=True)
class SearchTarget:
    """从 MoviePilot 成功整理历史还原的可选目标视频。"""

    history_id: int | None
    context: MediaContext
    transferred_at: datetime
    target_item: Any
    host_mediainfo: Any | None = None
    history_target_path: str | None = None


@dataclass(slots=True)
class SearchTargetPage:
    """可选目标视频分页结果。"""

    items: list[SearchTarget]
    total: int
    page: int
    page_size: int


@dataclass(slots=True)
class CustomDirectoryScan:
    """自定义目录文件与成功整理历史的关联结果。"""

    targets: list[SearchTarget]
    history_count: int
    indexed_file_count: int
    history_matched_count: int
    recognized_file_count: int
    fallback_file_count: int


@dataclass(frozen=True, slots=True)
class CustomDirectoryFile:
    """自定义目录中一个逻辑媒体目标的持久化签名。"""

    key: str
    path: Path
    size: int
    mtime_ns: int

    def index_value(
        self,
        last_task_id: str | None = None,
        *,
        pending_stability: bool = False,
    ) -> dict[str, Any]:
        """返回可保存到 PluginData 的 JSON 安全索引项。"""

        return {
            "path": str(self.path),
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "last_task_id": last_task_id,
            "pending_stability": pending_stability,
        }


@dataclass(frozen=True, slots=True)
class CustomDirectorySnapshot:
    """一次轻量目录遍历的文件签名快照。"""

    files: dict[str, CustomDirectoryFile]
    indexed_file_count: int


@dataclass(slots=True)
class ManualSourceView:
    """不包含下载句柄的人工来源搜索响应。"""

    source: SubtitleSource
    status: str
    candidates: list[SubtitleCandidate] = field(default_factory=list)
    default_queries: list[str] = field(default_factory=list)
    executed_queries: list[str] = field(default_factory=list)
    matched_query: str | None = None
    duration_ms: int | None = None
    error_summary: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ManualSearchResult:
    """一次人工字幕搜索的安全汇总。"""

    session_id: str | None
    target: SearchTarget
    sources: list[ManualSourceView]


@dataclass(slots=True)
class SessionCandidate:
    """搜索会话内可提交到下载队列的完整候选。"""

    session_id: str
    target: SearchTarget
    handle: CandidateHandle
    actual_query: str | None = None


@dataclass(slots=True)
class ManualSearchSession:
    """只存在于当前进程内存缓存的人工搜索会话。"""

    session_id: str
    target: SearchTarget
    candidates: dict[str, SessionCandidate]


def _parse_number(value: Any) -> int | None:
    """从整理历史季集字段中提取首个整数。"""

    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else None


def _parse_history_time(value: Any) -> datetime:
    """把 MoviePilot 本地时间字符串转换为 UTC 时间。"""

    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return datetime.now(UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed.astimezone(UTC)


class TargetQueryService:
    """通过整理历史查询目标，并可将其定位到自定义本地媒体目录。"""

    def __init__(
        self,
        history_oper: Any | None = None,
        batch_size: int = 100,
        custom_media_directories: tuple[str, ...] = (),
        path_mappings: tuple[PathMapping, ...] = (),
        allowed_extensions: set[str] | None = None,
    ) -> None:
        """创建目标查询服务并允许测试替换整理历史操作器。"""

        self._history_oper = history_oper or TransferHistoryOper()
        self._batch_size = batch_size
        self._custom_media_directories = tuple(Path(item) for item in custom_media_directories)
        self._path_mappings = path_mappings
        self._allowed_extensions = {
            f".{str(item).strip().lstrip('.').casefold()}"
            for item in (allowed_extensions or set())
            if str(item).strip()
        }
        self._allowed_extensions.add(".strm")
        self._custom_index: dict[str, list[Path]] = {}
        self._custom_index_expires_at = 0.0
        self._custom_index_lock = asyncio.Lock()

    def _scan_custom_directories_sync(self) -> dict[str, list[Path]]:
        """递归建立按文件主名分组的本地媒体索引。"""

        result: dict[str, list[Path]] = {}
        for root in self._custom_media_directories:
            if not root.is_dir():
                continue
            for current, directories, files in os.walk(root, followlinks=False):
                directories[:] = [
                    item for item in directories if not (Path(current) / item).is_symlink()
                ]
                for name in files:
                    path = Path(current) / name
                    if path.suffix.casefold() not in self._allowed_extensions:
                        continue
                    result.setdefault(path.stem.casefold(), []).append(path)
        return result

    async def _custom_files(self, force_refresh: bool = False) -> dict[str, list[Path]]:
        """返回最多复用 30 秒的自定义目录索引。"""

        if not self._custom_media_directories:
            return {}
        now = time.monotonic()
        if not force_refresh and now < self._custom_index_expires_at:
            return self._custom_index
        async with self._custom_index_lock:
            now = time.monotonic()
            if not force_refresh and now < self._custom_index_expires_at:
                return self._custom_index
            self._custom_index = await asyncio.to_thread(self._scan_custom_directories_sync)
            self._custom_index_expires_at = now + 30
            return self._custom_index

    @classmethod
    def _custom_snapshot_sync(cls, index: dict[str, list[Path]]) -> CustomDirectorySnapshot:
        """对媒体索引做 stat，并按同目录同主名合并字幕目标。"""

        grouped: dict[str, list[Path]] = {}
        indexed_file_count = 0
        for paths in index.values():
            for path in paths:
                indexed_file_count += 1
                grouped.setdefault(cls._logical_media_key(path), []).append(path)
        result: dict[str, CustomDirectoryFile] = {}
        for key, paths in grouped.items():
            ordered = sorted(
                paths,
                key=lambda item: (item.suffix.casefold() != ".strm", str(item).casefold()),
            )
            for path in ordered:
                try:
                    stat = path.stat()
                except OSError:
                    continue
                result[key] = CustomDirectoryFile(
                    key=key,
                    path=path,
                    size=max(0, int(stat.st_size)),
                    mtime_ns=max(0, int(stat.st_mtime_ns)),
                )
                break
        return CustomDirectorySnapshot(files=result, indexed_file_count=indexed_file_count)

    async def custom_directory_snapshot(self) -> CustomDirectorySnapshot:
        """返回当前自定义目录的轻量文件签名快照。"""

        if not self._custom_media_directories:
            raise ValueError("尚未配置自定义媒体目录")
        unavailable = await asyncio.to_thread(
            lambda: [str(root) for root in self._custom_media_directories if not root.is_dir()]
        )
        if unavailable:
            raise RuntimeError(f"自定义媒体目录不可用：{'、'.join(unavailable)}")
        index = await self._custom_files(force_refresh=True)
        return await asyncio.to_thread(self._custom_snapshot_sync, index)

    @staticmethod
    def _shared_parent_suffix(left: Path, right: Path) -> int:
        """计算两个父目录共享的尾部路径段数。"""

        count = 0
        for left_part, right_part in zip(
            reversed(left.parent.parts),
            reversed(right.parent.parts),
            strict=False,
        ):
            if left_part.casefold() != right_part.casefold():
                break
            count += 1
        return count

    def _select_custom_file(self, original: Path, index: dict[str, list[Path]]) -> Path | None:
        """以文件主名匹配媒体，同名时用尾部目录结构消除歧义。"""

        candidates = index.get(original.stem.casefold(), [])
        if not candidates:
            return None
        ranked = sorted(
            (
                (
                    (
                        int(candidate.name.casefold() == original.name.casefold()),
                        self._shared_parent_suffix(original, candidate),
                        int(candidate.suffix.casefold() == ".strm"),
                    ),
                    candidate,
                )
                for candidate in candidates
            ),
            key=lambda item: (item[0], str(item[1]).casefold()),
            reverse=True,
        )
        best_score, best_path = ranked[0]
        if len(ranked) > 1 and ranked[1][0] == best_score:
            logger.warning(
                f"自定义媒体目录中存在多个无法区分的同名文件“{original.stem}”，"
                "已保留整理历史原路径"
            )
            return None
        return best_path

    @staticmethod
    def _local_file_item(source: Any, path: Path) -> Any:
        """以原目标为模板构造 MoviePilot 兼容的本地文件项。"""

        values: dict[str, Any] = {}
        if hasattr(source, "model_dump"):
            try:
                values = source.model_dump()
            except Exception:  # noqa: BLE001 - 宿主对象版本差异时使用轻量回退
                values = {}
        values.update(
            {
                "path": str(path),
                "name": path.name,
                "extension": path.suffix.lstrip("."),
                "storage": "local",
                "type": "file",
            }
        )
        try:
            return FileItem.model_validate(values)
        except Exception:  # noqa: BLE001 - worker 只依赖这些稳定属性
            return SimpleNamespace(**values)

    async def _resolve_target(
        self,
        target: SearchTarget,
        custom_index: dict[str, list[Path]] | None = None,
    ) -> SearchTarget:
        """按路径映射和自定义目录解析一个整理历史目标。"""

        original = Path(target.history_target_path or target.context.target_path)
        try:
            resolution = resolve_path(original, self._path_mappings)
            mapped = Path(resolution.resolved_path)
        except ValueError:
            mapped = original
        direct_candidates = [mapped]
        if mapped.suffix.casefold() != ".strm":
            direct_candidates.append(mapped.with_suffix(".strm"))
        selected: Path | None = None
        for candidate in direct_candidates:
            if await asyncio.to_thread(candidate.is_file):
                selected = candidate
                break
        if selected is None:
            index = custom_index if custom_index is not None else await self._custom_files()
            selected = self._select_custom_file(original, index)
        if selected is None:
            return target
        context = target.context.model_copy(
            update={
                "target_path": str(selected),
                "target_file_name": selected.name,
                "target_storage": "local",
            }
        )
        return replace(
            target,
            context=context,
            target_item=self._local_file_item(target.target_item, selected),
            history_target_path=str(original),
        )

    async def resolve_runtime_target(self, context: MediaContext, target_item: Any) -> tuple[MediaContext, Any]:
        """把新整理事件目标定位到本地自定义目录。"""

        target = SearchTarget(
            history_id=-1,
            context=context,
            transferred_at=datetime.now(UTC),
            target_item=target_item,
            history_target_path=context.target_path,
        )
        resolved = await self._resolve_target(target)
        return resolved.context, resolved.target_item

    def retry_target(self, task: Any) -> SearchTarget:
        """使用终态任务快照重建可重新入队的本地媒体目标。"""

        path = Path(str(task.target_path))
        context = MediaContext(
            title=str(task.media_title),
            year=task.year,
            media_type=task.media_type,
            season=task.season,
            episode=task.episode,
            tmdb_id=task.tmdb_id,
            imdb_id=task.imdb_id,
            target_path=str(path),
            target_file_name=path.name,
            target_storage=task.target_storage or "local",
        )
        host_type = HostMediaType.TV if context.media_type is MediaType.TV else HostMediaType.MOVIE
        host_fields: dict[str, Any] = {"type": host_type, "title": context.title}
        if context.year is not None:
            host_fields["year"] = str(context.year)
        if context.season is not None:
            host_fields["season"] = context.season
        if context.tmdb_id is not None:
            host_fields["tmdb_id"] = context.tmdb_id
        if context.imdb_id is not None:
            host_fields["imdb_id"] = context.imdb_id
        return SearchTarget(
            history_id=task.target_history_id,
            context=context,
            transferred_at=task.finished_at or task.created_at,
            target_item=self._local_file_item(SimpleNamespace(), path),
            host_mediainfo=HostMediaInfo(**host_fields),
            history_target_path=task.history_target_path,
        )

    async def _histories(self) -> list[Any]:
        """分页读取全部成功整理历史。"""

        result: list[Any] = []
        page = 1
        while True:
            batch = await self._history_oper.async_list_by_page(
                page=page,
                count=self._batch_size,
                status=True,
            )
            if not batch:
                break
            result.extend(batch)
            if len(batch) < self._batch_size:
                break
            page += 1
        return result

    async def _to_target(self, history: Any) -> SearchTarget | None:
        """校验整理历史并还原安全目标上下文。

        整理历史是人工搜索的元数据来源，目标视频即使已经被移走也不影响
        搜索。因此这里刻意不调用文件系统存在性检查；实际字幕路径由下载
        worker 或改配服务在执行时再解析。
        """

        path_value = getattr(history, "dest", None)
        file_data = getattr(history, "dest_fileitem", None)
        if (
            getattr(history, "status", False) is not True
            or (
                getattr(history, "dest_storage", None) != "local"
                and not self._custom_media_directories
            )
            or not isinstance(path_value, str)
            or not path_value.strip()
            or not isinstance(file_data, dict)
            or file_data.get("type") != "file"
        ):
            return None
        raw_type = str(getattr(history, "type", "") or "")
        if raw_type in {HostMediaType.TV.value, "tv", "TV"}:
            media_type = MediaType.TV
            host_type = HostMediaType.TV
        elif raw_type in {HostMediaType.MOVIE.value, "movie", "MOVIE"}:
            media_type = MediaType.MOVIE
            host_type = HostMediaType.MOVIE
        else:
            media_type = MediaType.UNKNOWN
            host_type = HostMediaType.UNKNOWN
        raw_year = getattr(history, "year", None)
        if raw_year is not None:
            try:
                year = int(raw_year)
            except (TypeError, ValueError):
                year = None
        else:
            year = None
        raw_tmdb_id = getattr(history, "tmdbid", None)
        if raw_tmdb_id is not None:
            try:
                tmdb_id = int(raw_tmdb_id)
            except (TypeError, ValueError):
                tmdb_id = None
        else:
            tmdb_id = None
        item_data = dict(file_data)
        item_data.update({"path": path_value, "storage": "local"})
        target_item = FileItem.model_validate(item_data)
        context = MediaContext(
            title=str(getattr(history, "title", "") or Path(path_value).stem),
            year=year,
            media_type=media_type,
            season=_parse_number(getattr(history, "seasons", None)),
            episode=_parse_number(getattr(history, "episodes", None)),
            tmdb_id=tmdb_id,
            imdb_id=getattr(history, "imdbid", None),
            target_path=path_value,
            target_file_name=str(file_data.get("name") or Path(path_value).name),
            target_storage="local",
        )
        host_fields: dict[str, Any] = {
            "type": host_type,
            "title": context.title,
        }
        if year is not None:
            host_fields["year"] = str(year)
        if context.season is not None:
            host_fields["season"] = context.season
        if context.tmdb_id is not None:
            host_fields["tmdb_id"] = context.tmdb_id
        if context.imdb_id is not None:
            host_fields["imdb_id"] = context.imdb_id
        host_mediainfo = HostMediaInfo(**host_fields)
        return SearchTarget(
            history_id=int(history.id),
            context=context,
            transferred_at=_parse_history_time(getattr(history, "date", None)),
            target_item=target_item,
            host_mediainfo=host_mediainfo,
            history_target_path=path_value,
        )

    @staticmethod
    def _target_path_key(path: str | Path) -> str:
        """返回用于目录扫描关联与去重的规范路径键。"""

        return os.path.normcase(os.path.abspath(os.fspath(path)))

    @staticmethod
    def _logical_media_key(path: str | Path) -> str:
        """按同目录同主文件名合并共享同一字幕目标的媒体文件。"""

        value = Path(path)
        return os.path.normcase(os.path.abspath(value.parent / value.stem))

    @classmethod
    def logical_media_key(cls, path: str | Path) -> str:
        """返回供增量扫描索引使用的稳定逻辑媒体键。"""

        return cls._logical_media_key(path)

    @staticmethod
    def _single_meta_number(meta: Any, field: str) -> int | None:
        """只在路径元数据给出唯一数值时返回季或集。"""

        values = getattr(meta, field, None) or []
        numbers: set[int] = set()
        for value in values:
            try:
                numbers.add(int(value))
            except (TypeError, ValueError):
                continue
        return next(iter(numbers)) if len(numbers) == 1 else None

    @staticmethod
    def _media_type(value: Any, season: int | None, episode: int | None) -> tuple[MediaType, HostMediaType]:
        """把宿主媒体类型转换为插件类型，并用季集信息安全回退。"""

        raw = getattr(value, "value", value)
        normalized = str(raw or "").strip().casefold()
        if normalized in {"电视剧", "tv"} or season is not None or episode is not None:
            return MediaType.TV, HostMediaType.TV
        return MediaType.MOVIE, HostMediaType.MOVIE

    async def _local_file_target(self, path: Path) -> tuple[SearchTarget, bool]:
        """从本地文件路径构建目标，并尽力调用 MoviePilot 媒体识别。"""

        meta: Any | None = None
        mediainfo: Any | None = None
        try:
            meta = MetaInfoPath(path)
        except (AttributeError, TypeError, ValueError):
            logger.warning(
                f"自定义目录文件路径解析失败，将使用文件名继续提交字幕任务：{path}"
            )
        if meta is not None:
            try:
                mediainfo = await MediaChain().async_recognize_by_meta(meta)
            except Exception as exc:  # noqa: BLE001 - 单文件识别失败不能中断整个目录扫描
                logger.warning(
                    f"自定义目录文件媒体识别失败，将使用路径解析结果："
                    f"{path}（{type(exc).__name__}）"
                )

        season = self._single_meta_number(meta, "season_list") if meta is not None else None
        episode = self._single_meta_number(meta, "episode_list") if meta is not None else None
        media_type, host_type = self._media_type(
            getattr(mediainfo, "type", None) or getattr(meta, "type", None),
            season,
            episode,
        )

        def number(value: Any) -> int | None:
            try:
                return int(value) if value not in (None, "") else None
            except (TypeError, ValueError):
                return None

        title = str(
            getattr(mediainfo, "title", None)
            or getattr(meta, "cn_name", None)
            or getattr(meta, "name", None)
            or path.stem
        ).strip()
        year = number(getattr(mediainfo, "year", None) or getattr(meta, "year", None))
        tmdb_id = number(getattr(mediainfo, "tmdb_id", None))
        imdb_value = getattr(mediainfo, "imdb_id", None)
        imdb_id = str(imdb_value).strip() if imdb_value else None
        was_recognized = mediainfo is not None
        context = MediaContext(
            title=title,
            original_title=getattr(mediainfo, "original_title", None),
            english_title=getattr(mediainfo, "en_title", None) or getattr(meta, "en_name", None),
            year=year,
            media_type=media_type,
            season=season,
            episode=episode,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
            target_path=str(path),
            target_file_name=path.name,
            target_storage="local",
        )
        if mediainfo is None:
            host_fields: dict[str, Any] = {"type": host_type, "title": title}
            if year is not None:
                host_fields["year"] = str(year)
            if season is not None:
                host_fields["season"] = season
            mediainfo = HostMediaInfo(**host_fields)
        try:
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        except OSError:
            modified_at = datetime.now(UTC)
        return (
            SearchTarget(
                history_id=None,
                context=context,
                transferred_at=modified_at,
                target_item=self._local_file_item(SimpleNamespace(), path),
                host_mediainfo=mediainfo,
                history_target_path=None,
            ),
            was_recognized,
        )

    async def _valid_targets(
        self,
        histories: list[Any] | None = None,
        custom_index: dict[str, list[Path]] | None = None,
    ) -> list[SearchTarget]:
        """过滤并按规范目标路径保留最新整理历史。"""

        source_histories = histories if histories is not None else await self._histories()
        targets = [await self._to_target(item) for item in source_histories]
        if custom_index is None:
            custom_index = await self._custom_files()
        targets = [
            await self._resolve_target(item, custom_index)
            for item in targets
            if item is not None
        ]
        valid = sorted(
            targets,
            key=lambda item: item.transferred_at,
            reverse=True,
        )
        unique: dict[str, SearchTarget] = {}
        for item in valid:
            key = self._target_path_key(item.context.target_path)
            unique.setdefault(key, item)
        return list(unique.values())

    async def scan_custom_directories(
        self,
        logical_keys: set[str] | None = None,
    ) -> CustomDirectoryScan:
        """只为指定逻辑文件构建目标，整理历史优先，其余使用宿主识别。"""

        if not self._custom_media_directories:
            raise ValueError("尚未配置自定义媒体目录")
        # 调用方已先建立签名快照；复用 30 秒索引避免同一轮遍历两次。
        custom_index = await self._custom_files(force_refresh=False)
        indexed_paths = {
            self._target_path_key(path): path
            for paths in custom_index.values()
            for path in paths
        }
        selected_keys = set(logical_keys) if logical_keys is not None else {
            self._logical_media_key(path) for path in indexed_paths.values()
        }
        histories = await self._histories()
        valid = await self._valid_targets(histories=histories, custom_index=custom_index)
        history_targets = [
            target
            for target in valid
            if self._target_path_key(target.context.target_path) in indexed_paths
            and self._logical_media_key(target.context.target_path) in selected_keys
        ]
        targets_by_media: dict[str, SearchTarget] = {}
        for target in history_targets:
            targets_by_media.setdefault(self._logical_media_key(target.context.target_path), target)
        remaining_by_media: dict[str, Path] = {}
        ordered_paths = sorted(
            indexed_paths.values(),
            key=lambda item: (item.suffix.casefold() != ".strm", str(item).casefold()),
        )
        for path in ordered_paths:
            key = self._logical_media_key(path)
            if key in selected_keys and key not in targets_by_media:
                remaining_by_media.setdefault(key, path)

        # MoviePilot 识别一个本地媒体可能连续查询 TMDB 电影/剧集详情。
        # 自定义目录扫描不应与字幕下载任务一样并发，否则容易一次性打满代理连接。
        semaphore = asyncio.Semaphore(1)

        async def recognize(path: Path) -> tuple[SearchTarget, bool]:
            async with semaphore:
                return await self._local_file_target(path)

        recognized = list(await asyncio.gather(*(recognize(path) for path in remaining_by_media.values())))
        for target, _recognized in recognized:
            targets_by_media[self._logical_media_key(target.context.target_path)] = target
        recognized_file_count = sum(1 for _target, was_recognized in recognized if was_recognized)
        return CustomDirectoryScan(
            targets=list(targets_by_media.values()),
            history_count=len(histories),
            indexed_file_count=len(indexed_paths),
            history_matched_count=len({self._logical_media_key(item.context.target_path) for item in history_targets}),
            recognized_file_count=recognized_file_count,
            fallback_file_count=len(recognized) - recognized_file_count,
        )

    async def list_targets(
        self,
        page: int = 1,
        page_size: int = 25,
        search: str | None = None,
    ) -> SearchTargetPage:
        """分页返回按标题、文件名或完整路径筛选的目标。"""

        targets = await self._valid_targets()
        term = (search or "").strip().casefold()
        if term:
            targets = [
                item
                for item in targets
                if term in item.context.title.casefold()
                or term in item.context.target_file_name.casefold()
                or term in item.context.target_path.casefold()
            ]
        start = (page - 1) * page_size
        return SearchTargetPage(
            items=targets[start : start + page_size],
            total=len(targets),
            page=page,
            page_size=page_size,
        )

    async def list_all_targets(self) -> list[SearchTarget]:
        """返回用于批量改配精确建议的全部有效整理历史目标。"""

        return await self._valid_targets()

    async def get_target(self, history_id: int) -> SearchTarget | None:
        """按整理历史 ID 返回成功的本地单文件历史目标。

        这里返回的是历史快照，不保证历史目标文件当前仍存在；调用方在
        真正执行文件操作前负责检查解析后的目标目录。
        """

        if hasattr(self._history_oper, "async_get"):
            history = await self._history_oper.async_get(history_id)
        else:
            history = next(
                (item for item in await self._histories() if int(getattr(item, "id", -1)) == history_id),
                None,
            )
        target = await self._to_target(history) if history is not None else None
        return await self._resolve_target(target) if target is not None else None


async def _default_media_resolver(context: MediaContext) -> Any | None:
    """使用 MoviePilot 公共媒体能力按 TMDB ID 补充媒体信息。"""

    if context.tmdb_id is None:
        return None
    host_type = HostMediaType.TV if context.media_type is MediaType.TV else HostMediaType.MOVIE
    return await MediaChain().async_recognize_media(
        mtype=host_type,
        tmdbid=context.tmdb_id,
        cache=True,
    )


class ManualSearchService:
    """并发执行全部来源的人工搜索并管理进程内短期会话。"""

    def __init__(
        self,
        targets: TargetQueryService,
        sources: dict[SubtitleSource, SubtitleSourcePort],
        cache: Any | None = None,
        media_resolver: Callable[[MediaContext], Awaitable[Any | None]] | None = None,
        source_gate: SourceConcurrencyGate | None = None,
    ) -> None:
        """创建人工搜索服务。"""

        self._targets = targets
        self._sources = sources
        self._cache = cache or AsyncMemoryBackend(
            cache_type="ttl",
            maxsize=256,
            ttl=SEARCH_SESSION_TTL_SECONDS,
        )
        self._media_resolver = media_resolver or _default_media_resolver
        self._source_gate = source_gate or SourceConcurrencyGate(tuple(sources))

    @staticmethod
    def _session_key(session_id: str) -> str:
        """构造独立区域内的结构化搜索会话键。"""

        return json.dumps({"session_id": session_id}, sort_keys=True, separators=(",", ":"))

    async def _enrich_target(self, target: SearchTarget) -> SearchTarget:
        """在英文标题缺失时尽力通过宿主媒体能力补充。"""

        if target.context.english_title or not (target.context.tmdb_id or target.context.imdb_id):
            return target
        try:
            mediainfo = await self._media_resolver(target.context)
        except Exception:  # noqa: BLE001 - 宿主媒体补充失败时必须降级查询
            logger.warning(f"人工字幕搜索无法为整理历史 {target.history_id} 补充英文标题，将跳过依赖英文标题的查询")
            return target
        english_title = str(getattr(mediainfo, "en_title", "") or "").strip()
        if not english_title:
            return target
        target.context = target.context.model_copy(
            update={
                "english_title": english_title,
                "original_title": getattr(mediainfo, "original_title", None),
            }
        )
        target.host_mediainfo = mediainfo
        return target

    async def enrich_target(self, target: SearchTarget) -> SearchTarget:
        """为历史扫描任务补充英文标题及宿主媒体信息。"""

        return await self._enrich_target(target)

    @staticmethod
    def _source_context(run: ManualSourceSearchResult) -> str:
        """把人工来源的缓存、分页和查询信息转换为中文。"""

        details = dict(getattr(run, "details", {}) or {})
        parts: list[str] = []
        if details.get("cache_hit") is True:
            cached_at = details.get("cache_stored_at")
            parts.append(f"复用了缓存{f'（写入时间 {cached_at}）' if cached_at else ''}")
        elif details.get("cache_hit") is False:
            parts.append("本次实际请求了字幕站")
        page_count = details.get("page_count")
        if isinstance(page_count, int) and page_count > 0:
            parts.append(f"读取 {page_count} 页")
            if details.get("pagination_complete") is False:
                parts.append("分页未完整读取")
        query = str(details.get("query") or run.matched_query or "").strip()
        query_type = str(details.get("query_type") or "").strip()
        if query:
            parts.append(f"使用{QUERY_TYPE_NAMES.get(query_type, '查询词')}“{query}”")
        return "，".join(parts)

    @classmethod
    def _log_source_result(cls, history_id: int, run: ManualSourceSearchResult) -> None:
        """为一次人工来源搜索记录唯一的中文业务结论。"""

        name = SOURCE_NAMES[run.source]
        context = cls._source_context(run)
        suffix = f"；{context}" if context else ""
        raw_count = max(len(run.candidates), int(getattr(run, "raw_count", 0)))
        if run.status == "disabled":
            logger.info(f"人工字幕搜索未查询 {name}：该来源未启用")
            return
        if run.status == "unconfigured":
            reason = "没有启用且支持字幕搜索的站点" if run.skip_reason == "no_subtitle_sites" else "该来源配置不完整"
            logger.info(f"人工字幕搜索未查询 {name}：{reason}")
            return
        if run.status == "limited":
            logger.warning(f"人工字幕搜索查询 {name} 受限：{run.error_summary or '字幕源暂时限制请求'}{suffix}")
            return
        if run.status == "error":
            logger.warning(f"人工字幕搜索查询 {name} 失败：{run.error_summary or '字幕源请求异常'}{suffix}")
            return
        conclusion = "字幕站没有返回候选" if raw_count == 0 else f"字幕站返回 {raw_count} 个候选，全部保留供用户选择"
        duration = f"；耗时 {run.duration_ms} 毫秒" if run.duration_ms is not None else ""
        log = logger.warning if run.details.get("pagination_complete") is False else logger.info
        log(f"整理历史 {history_id} 的人工字幕搜索已完成 {name} 查询：{conclusion}{suffix}{duration}")

    async def search(
        self,
        history_id: int,
        custom_queries: dict[SubtitleSource | str, str | None] | None = None,
    ) -> ManualSearchResult:
        """并发搜索全部来源，有候选时创建三十分钟内存会话。"""

        target = await self._targets.get_target(history_id)
        if target is None:
            raise LookupError("目标整理历史不存在或已不可用")
        target = await self._enrich_target(target)
        values = custom_queries or {}
        coroutines = []
        ordered_sources = list(SubtitleSource)
        for source in ordered_sources:
            adapter = self._sources[source]
            custom = values.get(source, values.get(source.value))
            coroutines.append(
                self._source_gate.run(
                    source,
                    lambda adapter=adapter, custom=custom: adapter.manual_search(target.context, custom),
                )
            )
        raw_results = await asyncio.gather(*coroutines, return_exceptions=True)
        runs: list[ManualSourceSearchResult] = []
        for source, result in zip(ordered_sources, raw_results, strict=True):
            if isinstance(result, BaseException):
                runs.append(
                    ManualSourceSearchResult(
                        source=source,
                        status="error",
                        error_summary=f"{SOURCE_NAMES[source]} 人工搜索失败",
                    )
                )
            else:
                result.candidates.sort(key=lambda handle: candidate_chinese_priority(handle.candidate))
                runs.append(result)
        for run in runs:
            self._log_source_result(history_id, run)
        session_id = new_id() if any(run.candidates for run in runs) else None
        if session_id:
            candidates: dict[str, SessionCandidate] = {}
            for run in runs:
                for handle in run.candidates:
                    candidates.setdefault(
                        handle.candidate.stable_key,
                        SessionCandidate(
                            session_id=session_id,
                            target=target,
                            handle=handle,
                            actual_query=run.matched_query,
                        ),
                    )
            session = ManualSearchSession(
                session_id=session_id,
                target=target,
                candidates=candidates,
            )
            await self._cache.set(
                self._session_key(session_id),
                session,
                ttl=SEARCH_SESSION_TTL_SECONDS,
                region=SEARCH_SESSION_REGION,
            )
        views = [
            ManualSourceView(
                source=run.source,
                status=run.status,
                candidates=[item.candidate for item in run.candidates],
                default_queries=run.default_queries,
                executed_queries=run.executed_queries,
                matched_query=run.matched_query,
                duration_ms=run.duration_ms,
                error_summary=run.error_summary,
                details=dict(run.details),
            )
            for run in runs
        ]
        candidate_count = sum(len(item.candidates) for item in runs)
        if session_id:
            logger.info(
                f"整理历史 {history_id} 的人工字幕搜索完成，共返回 {candidate_count} 个候选，搜索会话为 {session_id}"
            )
        else:
            logger.warning(f"整理历史 {history_id} 的人工字幕搜索完成，但全部来源都没有返回可下载候选")
        return ManualSearchResult(session_id=session_id, target=target, sources=views)

    async def get_candidate(
        self,
        session_id: str,
        candidate_key: str,
    ) -> SessionCandidate | None:
        """从有效会话读取完整不透明候选句柄。"""

        session = await self._cache.get(
            self._session_key(session_id),
            region=SEARCH_SESSION_REGION,
        )
        if not isinstance(session, ManualSearchSession):
            return None
        return session.candidates.get(candidate_key)

    async def clear_sessions(self) -> None:
        """在插件重载或停止时清除全部人工搜索会话。"""

        await self._cache.clear(region=SEARCH_SESSION_REGION)
