"""Per-company sliding-window rate limiter for SAP plugin HTTP routes.

In-memory implementation — no external dependency. Suitable for a v1:

* Single-worker deployments share the bucket.
* Multi-worker deployments will under-count (each worker has its own
  bucket) but never over-count, so a 60/min limit becomes "≤60/min per
  worker" which is still a hard cap. Move to Redis-backed buckets in
  Phase 5 if the discrepancy matters.

Limits are differentiated by request shape:

* ``read``    GET endpoints (list / get / browse / audit).         60/min
* ``write``   POST / PATCH connection CRUD.                        10/min
* ``heavy``   POST /test and /sync (one $metadata fetch each).      5/min

Limits are configurable per-instance via the ``Limits`` dataclass at
factory time. The ``RateLimiter`` exposes FastAPI ``Depends`` callables
that look up the caller's ``company_id`` from the auth tuple injected
by ``piilot.sdk.http.require_user``.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from time import monotonic
from typing import Annotated

from fastapi import Depends, HTTPException
from piilot.sdk.http import require_user


@dataclass(frozen=True)
class Limits:
    """Per-bucket rate limits (calls per ``window_seconds``)."""

    read: int = 60
    write: int = 10
    heavy: int = 5
    window_seconds: int = 60


DEFAULT_LIMITS = Limits()


class RateLimiter:
    """Per-(company_id, bucket) sliding-window rate limiter.

    Thread-safe across concurrent coroutines via ``asyncio.Lock``. The
    bucket store is process-local; reset on plugin reload.
    """

    def __init__(self, limits: Limits | None = None) -> None:
        self._limits = limits or DEFAULT_LIMITS
        self._lock = asyncio.Lock()
        self._buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
        self._clock = monotonic

    def reset(self) -> None:
        """Clear every bucket — primarily for tests."""
        self._buckets.clear()

    @property
    def limits(self) -> Limits:
        return self._limits

    async def check(self, *, company_id: str, bucket: str) -> None:
        """Raise HTTP 429 if the caller exceeded the bucket limit."""
        limit = self._limit_for(bucket)
        window = self._limits.window_seconds
        now = self._clock()
        cutoff = now - window
        key = (company_id, bucket)

        async with self._lock:
            timestamps = self._buckets[key]
            # In-place filter keeps the list reference stable for the
            # caller's worker thread.
            timestamps[:] = [t for t in timestamps if t > cutoff]
            if len(timestamps) >= limit:
                retry_after = max(1, int(timestamps[0] + window - now) + 1)
                raise HTTPException(
                    status_code=429,
                    detail=(f"rate limit exceeded ({limit}/{window}s) for " f"bucket {bucket!r}"),
                    headers={"Retry-After": str(retry_after)},
                )
            timestamps.append(now)

    def _limit_for(self, bucket: str) -> int:
        if bucket == "read":
            return self._limits.read
        if bucket == "write":
            return self._limits.write
        if bucket == "heavy":
            return self._limits.heavy
        raise ValueError(f"unknown rate-limit bucket {bucket!r}")

    def depends_read(self):
        return self._build_dependency("read")

    def depends_write(self):
        return self._build_dependency("write")

    def depends_heavy(self):
        return self._build_dependency("heavy")

    def _build_dependency(self, bucket: str):
        """Return a FastAPI dependency callable for the given bucket.

        The closure binds ``bucket`` and ``self`` lexically so each call
        site (``depends_read`` / ``depends_write`` / ``depends_heavy``)
        produces a distinct ``Depends(...)`` that FastAPI memoizes by
        identity.
        """
        limiter = self

        async def _enforce(
            auth: Annotated[tuple, Depends(require_user)],
        ) -> None:
            _, _, company_id = auth
            await limiter.check(company_id=company_id, bucket=bucket)

        return _enforce


# Module-level singleton used by the routes. Tests can rebind via
# ``rate_limit.limiter = RateLimiter(Limits(...))`` or call
# ``limiter.reset()`` between cases.
limiter = RateLimiter()


__all__ = ["DEFAULT_LIMITS", "Limits", "RateLimiter", "limiter"]
