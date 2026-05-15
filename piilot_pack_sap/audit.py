"""Audit trail for OData calls performed by the plugin.

Every agent tool (Phase 2) and HTTP route (Phase 3) will route through
:func:`record_call` after executing a SAP request. The audit log is the
single source of truth for "who called what when" and is the first surface
the support team queries when an agent misbehaves.

Status taxonomy (kept in sync with the ``status`` CHECK constraint comments
in ``001_init_sap.sql``):

* ``ok`` — request executed, server returned 2xx, payload usable.
* ``validator_rejected`` — request never reached the network; the OData
  validator refused it.
* ``auth_error`` — IdP refused the token (OAuth) or 401 came back.
* ``http_error`` — server returned 4xx/5xx after retries were exhausted.
* ``parse_error`` — server responded but the body wasn't usable
  (non-JSON for a typed call, non-int for a ``$count``, etc.).
* ``rate_limited`` — 429 not absorbed by the retry budget.
* ``timeout`` — connection timed out / unreachable.
"""

from __future__ import annotations

from piilot_pack_sap import repository

AuditStatus = str  # see module docstring for the allowed values.


def record_call(
    *,
    company_id: str,
    tool_id: str,
    odata_url: str,
    status: AuditStatus,
    connection_id: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    entity_set: str | None = None,
    http_method: str = "GET",
    http_status: int | None = None,
    latency_ms: int | None = None,
    error: str | None = None,
    result_count: int | None = None,
) -> str:
    """Append a row to ``integrations_sap.audit_log`` and return its id.

    Caller is responsible for measuring ``latency_ms`` and for truncating
    ``error`` to a reasonable length (the column is TEXT but storing the
    full response body would bloat the table and risk leaking customer data;
    keep it to a sentence or two).
    """
    if not company_id:
        raise ValueError("company_id is required")
    if not tool_id:
        raise ValueError("tool_id is required")
    if not odata_url:
        raise ValueError("odata_url is required")
    if not status:
        raise ValueError("status is required")

    entry: repository.AuditEntry = {
        "company_id": company_id,
        "tool_id": tool_id,
        "odata_url": odata_url,
        "status": status,
        "http_method": http_method,
        "connection_id": connection_id,
        "user_id": user_id,
        "session_id": session_id,
        "entity_set": entity_set,
        "http_status": http_status,
        "latency_ms": latency_ms,
        "error": _truncate_error(error),
        "result_count": result_count,
    }
    return repository.insert_audit_log(entry)


def _truncate_error(error: str | None, *, max_len: int = 2000) -> str | None:
    """Trim long error payloads. ``2000`` chars is plenty for diagnosis and
    keeps individual audit rows small even under sustained failures."""
    if error is None:
        return None
    if len(error) <= max_len:
        return error
    return error[:max_len] + "...[truncated]"


__all__ = ["AuditStatus", "record_call"]
