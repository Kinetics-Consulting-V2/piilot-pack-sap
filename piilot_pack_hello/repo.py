"""Example use of ``piilot.sdk.db`` — a minimal repository that tracks
how many times each company has triggered the ``hello`` module.

Demonstrates:

* :func:`piilot.sdk.db.cursor` — sync context manager yielding a
  ``RealDictCursor`` with auto commit/rollback.
* :func:`piilot.sdk.db.run_in_thread` — async wrapper that preserves
  the RLS user context (critical — do NOT use ``asyncio.to_thread``
  instead, it bypasses the RLS propagation and your queries can return
  empty or cross-tenant data depending on policies).
* :func:`piilot.sdk.db.Json` — wrap dicts / lists before inserting into
  a JSONB column.

Replace this with your real domain model when you fork the template.
"""

from __future__ import annotations

from typing import Any

from piilot.sdk.db import Json, cursor, run_in_thread


def _get_counter_sync(company_id: str) -> int:
    """Return the current greet count for ``company_id`` (0 if absent)."""
    with cursor() as cur:
        cur.execute(
            "SELECT count FROM hello.greet_counter WHERE company_id = %s",
            (company_id,),
        )
        row = cur.fetchone()
        return int(row["count"]) if row else 0


def _increment_counter_sync(company_id: str, metadata: dict[str, Any]) -> int:
    """Insert or increment the counter. Returns the new count.

    The ``metadata`` dict is stored in a JSONB column — useful for
    recording the greeter's name, user_id, etc. for audit purposes.
    """
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO hello.greet_counter (company_id, count, last_metadata)
            VALUES (%s, 1, %s)
            ON CONFLICT (company_id) DO UPDATE
                SET count = hello.greet_counter.count + 1,
                    last_metadata = EXCLUDED.last_metadata,
                    updated_at = now()
            RETURNING count
            """,
            (company_id, Json(metadata)),
        )
        row = cur.fetchone()
        return int(row["count"])


# ---------------------------------------------------------------------------
# Async wrappers — the async parts of a plugin (routes, webhooks, scheduler
# handlers) MUST wrap sync DB calls with ``run_in_thread`` to preserve the
# RLS user context across threads.
# ---------------------------------------------------------------------------


async def get_counter(company_id: str) -> int:
    return await run_in_thread(_get_counter_sync, company_id)


async def increment_counter(company_id: str, metadata: dict[str, Any]) -> int:
    return await run_in_thread(_increment_counter_sync, company_id, metadata)
