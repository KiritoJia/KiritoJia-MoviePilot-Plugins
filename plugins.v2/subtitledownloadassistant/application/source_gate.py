"""字幕源共享并发门控。"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Hashable
from typing import TypeVar

T = TypeVar("T")


class SourceConcurrencyGate:
    """让自动任务、人工搜索和状态刷新共享每来源锁与请求间隔。"""

    def __init__(
        self,
        sources: list[Hashable] | tuple[Hashable, ...] | set[Hashable],
        minimum_intervals: dict[Hashable, float] | None = None,
    ) -> None:
        """为已注册的来源创建独立锁。"""

        self._locks = {source: asyncio.Lock() for source in sources}
        self._minimum_intervals = {
            source: max(0.0, float(interval)) for source, interval in (minimum_intervals or {}).items()
        }
        self._last_started: dict[Hashable, float] = {}

    async def run(self, source: Hashable, operation: Callable[[], Awaitable[T]]) -> T:
        """等待该来源空闲后执行一次外部调用。"""

        lock = self._locks.setdefault(source, asyncio.Lock())
        async with lock:
            interval = self._minimum_intervals.get(source, 0.0)
            previous = self._last_started.get(source)
            if previous is not None and interval > 0:
                delay = previous + interval - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
            self._last_started[source] = time.monotonic()
            return await operation()
