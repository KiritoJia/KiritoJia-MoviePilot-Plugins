"""字幕源并发门控测试。"""

from __future__ import annotations

import asyncio
import importlib.util
import time
from pathlib import Path


def _load_gate():
    path = Path(__file__).resolve().parents[1] / "application/source_gate.py"
    spec = importlib.util.spec_from_file_location("subtitle_source_gate_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SourceConcurrencyGate


def test_same_source_is_serialized_but_different_sources_overlap() -> None:
    SourceConcurrencyGate = _load_gate()
    active: dict[str, int] = {"assrt": 0, "shooter": 0}
    maximum: dict[str, int] = {"assrt": 0, "shooter": 0}
    total_active = 0
    total_maximum = 0

    async def operation(source: str) -> str:
        nonlocal total_active, total_maximum
        active[source] += 1
        total_active += 1
        maximum[source] = max(maximum[source], active[source])
        total_maximum = max(total_maximum, total_active)
        await asyncio.sleep(0.01)
        active[source] -= 1
        total_active -= 1
        return source

    async def run() -> list[str]:
        gate = SourceConcurrencyGate(("assrt", "shooter"))
        return await asyncio.gather(
            gate.run("assrt", lambda: operation("assrt")),
            gate.run("assrt", lambda: operation("assrt")),
            gate.run("shooter", lambda: operation("shooter")),
        )

    assert sorted(asyncio.run(run())) == ["assrt", "assrt", "shooter"]
    assert maximum == {"assrt": 1, "shooter": 1}
    assert total_maximum == 2


def test_configured_source_calls_start_at_least_one_interval_apart() -> None:
    SourceConcurrencyGate = _load_gate()
    started: list[float] = []

    async def operation() -> None:
        started.append(time.monotonic())

    async def run() -> None:
        gate = SourceConcurrencyGate(("shooter",), minimum_intervals={"shooter": 0.03})
        await asyncio.gather(
            gate.run("shooter", operation),
            gate.run("shooter", operation),
        )

    asyncio.run(run())
    assert len(started) == 2
    assert started[1] - started[0] >= 0.025
