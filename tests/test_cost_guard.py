"""Tests for ``piilot_pack_sap.cost_guard``."""

from __future__ import annotations

import asyncio
from importlib import reload

import pytest

from piilot_pack_sap import cost_guard
from piilot_pack_sap.cost_guard import (
    DEFAULT_SESSION_TOOL_BUDGET,
    SessionCostTracker,
)


def test_default_budget_is_positive() -> None:
    assert DEFAULT_SESSION_TOOL_BUDGET > 0


def test_budget_validation_rejects_zero_or_negative() -> None:
    with pytest.raises(ValueError, match="budget must be at least 1"):
        SessionCostTracker(budget=0)
    with pytest.raises(ValueError, match="budget must be at least 1"):
        SessionCostTracker(budget=-5)


@pytest.mark.asyncio
async def test_check_and_increment_under_budget() -> None:
    tracker = SessionCostTracker(budget=3)
    for i in range(1, 4):
        allowed, count = await tracker.check_and_increment("sess-1")
        assert allowed is True
        assert count == i


@pytest.mark.asyncio
async def test_check_and_increment_rejects_above_budget() -> None:
    tracker = SessionCostTracker(budget=2)
    await tracker.check_and_increment("sess-1")
    await tracker.check_and_increment("sess-1")
    allowed, count = await tracker.check_and_increment("sess-1")
    assert allowed is False
    assert count == 2


@pytest.mark.asyncio
async def test_sessions_are_isolated() -> None:
    tracker = SessionCostTracker(budget=2)
    await tracker.check_and_increment("sess-A")
    await tracker.check_and_increment("sess-A")
    # session B keeps its full budget
    allowed, _ = await tracker.check_and_increment("sess-B")
    assert allowed is True


@pytest.mark.asyncio
async def test_anonymous_session_is_bucketed_separately() -> None:
    tracker = SessionCostTracker(budget=2)
    allowed1, _ = await tracker.check_and_increment(None)
    allowed2, _ = await tracker.check_and_increment("")
    allowed3, _ = await tracker.check_and_increment(None)
    # Anonymous calls share a bucket
    assert (allowed1, allowed2, allowed3) == (True, True, False)


@pytest.mark.asyncio
async def test_reset_wipes_all_sessions() -> None:
    tracker = SessionCostTracker(budget=1)
    await tracker.check_and_increment("sess-1")
    await tracker.check_and_increment("sess-2")
    tracker.reset()
    # Both can fire again after reset.
    a, _ = await tracker.check_and_increment("sess-1")
    b, _ = await tracker.check_and_increment("sess-2")
    assert a is True
    assert b is True


@pytest.mark.asyncio
async def test_get_returns_zero_for_unknown_session() -> None:
    tracker = SessionCostTracker()
    assert tracker.get("never-called") == 0


@pytest.mark.asyncio
async def test_get_returns_current_count() -> None:
    tracker = SessionCostTracker(budget=10)
    await tracker.check_and_increment("sess-1")
    await tracker.check_and_increment("sess-1")
    assert tracker.get("sess-1") == 2


@pytest.mark.asyncio
async def test_lock_serializes_concurrent_increments() -> None:
    """Many concurrent calls must produce a monotonic sequence with no
    over-counting (no two coroutines should observe the same count)."""
    tracker = SessionCostTracker(budget=100)
    results = await asyncio.gather(
        *(tracker.check_and_increment("sess-1") for _ in range(50))
    )
    counts = sorted(r[1] for r in results)
    assert counts == list(range(1, 51))
    # All allowed (under budget).
    assert all(r[0] is True for r in results)


def test_budget_env_var_overrides_default(monkeypatch) -> None:
    monkeypatch.setenv("SAP_TOOL_BUDGET_PER_SESSION", "5")
    reload(cost_guard)
    try:
        assert cost_guard.DEFAULT_SESSION_TOOL_BUDGET == 5
    finally:
        monkeypatch.delenv("SAP_TOOL_BUDGET_PER_SESSION")
        reload(cost_guard)


def test_invalid_budget_env_var_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv("SAP_TOOL_BUDGET_PER_SESSION", "not-a-number")
    reload(cost_guard)
    try:
        assert cost_guard.DEFAULT_SESSION_TOOL_BUDGET == 30
    finally:
        monkeypatch.delenv("SAP_TOOL_BUDGET_PER_SESSION")
        reload(cost_guard)


def test_negative_budget_env_var_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv("SAP_TOOL_BUDGET_PER_SESSION", "-1")
    reload(cost_guard)
    try:
        assert cost_guard.DEFAULT_SESSION_TOOL_BUDGET == 30
    finally:
        monkeypatch.delenv("SAP_TOOL_BUDGET_PER_SESSION")
        reload(cost_guard)
