"""Per-session cost guard for SAP agent tools.

Each tool call increments a counter keyed by ``session_id``. When the
counter reaches :data:`DEFAULT_SESSION_TOOL_BUDGET`, subsequent calls
return early with ``status="cost_limit_exceeded"`` so the agent stops
hammering the SAP instance.

The counter is in-memory by default (process-local). Sessions are
short-lived (≤ 30 min by host policy), so the counter resets naturally
when the session expires. Tests can call :meth:`SessionCostTracker.reset`
to wipe state between cases.

The budget is configurable per-instance via the ``SAP_TOOL_BUDGET_PER_SESSION``
environment variable, read once at module import. Set it generously —
hitting the cap is intended for runaway-loop protection, not for
day-to-day quota enforcement.
"""

from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from typing import Optional


def _read_budget_env(default: int = 30) -> int:
    raw = os.environ.get("SAP_TOOL_BUDGET_PER_SESSION", "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


DEFAULT_SESSION_TOOL_BUDGET = _read_budget_env()


class SessionCostTracker:
    """In-memory counter of SAP tool invocations per session.

    All methods are async-safe (single :class:`asyncio.Lock` shared
    across operations). Anonymous calls (``session_id`` falsy) are
    bucketed under a sentinel — they share a counter but don't crash.
    """

    _ANONYMOUS_KEY = "<anonymous>"

    def __init__(self, *, budget: int = DEFAULT_SESSION_TOOL_BUDGET) -> None:
        if budget < 1:
            raise ValueError("budget must be at least 1")
        self._budget = budget
        self._counts: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    @property
    def budget(self) -> int:
        return self._budget

    def reset(self) -> None:
        """Clear every counter — primarily for tests."""
        self._counts.clear()

    def get(self, session_id: Optional[str]) -> int:
        return self._counts.get(self._key(session_id), 0)

    async def check_and_increment(
        self, session_id: Optional[str]
    ) -> tuple[bool, int]:
        """Atomically check the budget and increment on success.

        Returns ``(allowed, current_count)``. ``current_count`` is the
        count AFTER the increment when ``allowed`` is True, the count
        AT REFUSAL when ``allowed`` is False (so the caller can show
        ``"45/30"`` style messages).
        """
        key = self._key(session_id)
        async with self._lock:
            current = self._counts[key]
            if current >= self._budget:
                return False, current
            new_count = current + 1
            self._counts[key] = new_count
            return True, new_count

    def _key(self, session_id: Optional[str]) -> str:
        if not session_id:
            return self._ANONYMOUS_KEY
        return session_id


tracker = SessionCostTracker()


__all__ = [
    "DEFAULT_SESSION_TOOL_BUDGET",
    "SessionCostTracker",
    "tracker",
]
