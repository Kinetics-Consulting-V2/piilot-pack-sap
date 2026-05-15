"""Agent tools for the SAP connector — 9 LangChain ``StructuredTool`` exports.

Every tool follows the same pattern:

1. Public async function ``sap_<name>_fn`` taking the LLM-facing parameters
   plus ``session_id: str = ""`` (stripped from the schema by
   :func:`piilot.sdk.tools.bind_session`).
2. Build an :class:`~piilot_pack_sap.query_builder.ODataQuery` (or compose a
   raw path for navigation / function imports).
3. Delegate to :mod:`piilot_pack_sap.tool_executor` which resolves the SAP
   connection, executes the OData call, appends an audit row, and returns
   a structured :class:`ToolResult`.
4. The function returns ``ToolResult.to_dict()`` (JSON-serializable).
5. ``StructuredTool.from_function(coroutine=bind_session(fn), name=...)``
   is wired into ``piilot.sdk.tools.register_tool`` by :func:`wire_tools`.

Admin gates (``sap_lookup``, ``sap_invoke_function``) check the role
field on the session's ``user_infos`` dict — see the SDK session API. They
fail closed when the role is missing or non-admin.

Read-only invariant: every tool issues a GET. ``sap_invoke_function``
accepts only OData function imports (GET semantics); function imports
that the SAP service exposes as POST (mutations) are out of scope for v1.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from piilot.sdk.db import run_in_thread
from piilot.sdk.session import get as get_session
from piilot.sdk.tools import bind_session, register_tool

from piilot_pack_sap import repository
from piilot_pack_sap.connection_resolver import (
    ConnectionResolver,
    ResolutionError,
)
from piilot_pack_sap.odata_validator import (
    DEFAULT_MAX_TOP,
    ValidationError,
)
from piilot_pack_sap.query_builder import ODataQuery
from piilot_pack_sap.tool_executor import (
    SessionUnknownError,
    ToolResult,
    execute_odata_call,
    execute_raw_call,
    resolve_company_id,
)

# Hard cap on $top across every tool, on top of the validator's DEFAULT_MAX_TOP.
DEFAULT_PAGE_SIZE = 50
SAFE_IDENT_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_ABCDEFGHIJKLMNOPQRSTUVWXYZ")


# ---------------------------------------------------------------------------
# Local validation helpers (defensive — the executor's validator already
# enforces simple identifiers, but for sap_navigate / sap_invoke_function
# we build raw paths so we re-check at the tool boundary).
# ---------------------------------------------------------------------------


def _is_simple_identifier(value: str) -> bool:
    if not value:
        return False
    if value[0].isdigit():
        return False
    return all(ch in SAFE_IDENT_CHARS for ch in value)


def _split_csv(raw: str) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _parse_order_by(raw: str) -> tuple[tuple[str, str], ...]:
    """Parse ``"FirstName asc, LastName desc"`` into the ODataQuery tuple shape."""
    pairs: list[tuple[str, str]] = []
    for item in _split_csv(raw):
        parts = item.split()
        prop = parts[0]
        direction = parts[1].lower() if len(parts) > 1 else "asc"
        if direction not in ("asc", "desc"):
            raise ValidationError(
                code="invalid_orderby_direction",
                message=f"$orderby direction must be 'asc' or 'desc', got {direction!r}",
            )
        pairs.append((prop, direction))
    return tuple(pairs)


def _quote_key(key: str) -> str:
    """Quote a single OData key for embedding in a raw path.

    OData v2/v4 accepts ``KeySet('value')`` for strings. Numeric keys are
    written without quotes; we keep things simple in v1 and always quote,
    escaping single quotes by doubling them per the OData spec.
    """
    escaped = key.replace("'", "''")
    return f"'{escaped}'"


def _require_admin_session(session_id: str) -> str | None:
    """Return None if the caller is an admin; otherwise a refusal message."""
    if not session_id:
        return "this tool requires an active session"
    state = get_session(session_id)
    if state is None:
        return "session is unknown or expired"
    user_infos = getattr(state, "user_infos", None) or {}
    role = user_infos.get("role")
    if role == "admin":
        return None
    role_id = user_infos.get("role_id")
    if role_id == 1:
        return None
    return "this tool requires the admin role"


# ---------------------------------------------------------------------------
# Tool 1 — sap_describe_entity
# ---------------------------------------------------------------------------


async def sap_describe_entity_fn(
    entity_set: str,
    session_id: str = "",
) -> dict[str, Any]:
    """Return the cached ``$metadata`` description of one EntitySet.

    Reads ``integrations_sap.schema_snapshot`` — no live OData call. Use
    this before calling ``sap_select`` or ``sap_aggregate`` so the agent
    knows which properties exist and which are filterable / sortable.
    """
    try:
        company_id = resolve_company_id(session_id)
    except SessionUnknownError as exc:
        return ToolResult(status="session_unknown", error=str(exc)).to_dict()

    if not _is_simple_identifier(entity_set):
        return ToolResult(
            status="validator_rejected",
            error=f"entity_set {entity_set!r} is not a simple identifier",
        ).to_dict()

    try:
        resolver = ConnectionResolver()
        resolved = await resolver.resolve(
            company_id=company_id, session_id=session_id
        )
    except ResolutionError as exc:
        return ToolResult(status="resolution_error", error=str(exc)).to_dict()

    row = await run_in_thread(
        repository.get_snapshot_entry,
        connection_id=resolved.connection_id,
        entity_set_name=entity_set,
    )
    if row is None:
        return ToolResult(
            status="not_found",
            error=(
                f"EntitySet {entity_set!r} is not in the cached snapshot. "
                "Run a re-sync from the Settings page or call "
                "sap_search_entity to discover available entity sets."
            ),
            connection_label=resolved.label,
        ).to_dict()
    return ToolResult(
        status="ok",
        data={
            "entity_set_name": row["entity_set_name"],
            "service_path": row["service_path"],
            "label": row.get("label"),
            "description": row.get("description"),
            "payload": row.get("payload"),
            "last_synced_at": str(row["last_synced_at"]),
        },
        connection_label=resolved.label,
    ).to_dict()


sap_describe_entity = StructuredTool.from_function(
    coroutine=bind_session(sap_describe_entity_fn),
    name="sap_describe_entity",
    description=(
        "Return the cached metadata of one SAP EntitySet (properties, types, "
        "navigations). Always call this BEFORE sap_select / sap_aggregate so "
        "you know which fields exist and which are filterable."
    ),
)


# ---------------------------------------------------------------------------
# Tool 2 — sap_search_entity
# ---------------------------------------------------------------------------


async def sap_search_entity_fn(
    query: str,
    limit: int = 10,
    session_id: str = "",
) -> dict[str, Any]:
    """Substring-search the cached EntitySet catalogue.

    Looks for ``query`` (case-insensitive) inside ``entity_set_name`` and
    ``description``. Returns the top ``limit`` matches. For semantic search
    over the same data, use the host's ``query_knowledge`` tool on the
    plugin-owned KB "SAP Metadata — <connection_label>".
    """
    try:
        company_id = resolve_company_id(session_id)
    except SessionUnknownError as exc:
        return ToolResult(status="session_unknown", error=str(exc)).to_dict()

    needle = (query or "").strip().lower()
    if not needle:
        return ToolResult(
            status="validator_rejected",
            error="query must not be empty",
        ).to_dict()
    if limit < 1 or limit > 100:
        return ToolResult(
            status="validator_rejected",
            error="limit must be between 1 and 100",
        ).to_dict()

    try:
        resolved = await ConnectionResolver().resolve(
            company_id=company_id, session_id=session_id
        )
    except ResolutionError as exc:
        return ToolResult(status="resolution_error", error=str(exc)).to_dict()

    rows = await run_in_thread(
        repository.list_schema_snapshot,
        connection_id=resolved.connection_id,
        limit=10_000,
    )

    matches: list[dict[str, Any]] = []
    for row in rows:
        haystack = " ".join(
            filter(
                None,
                [
                    (row.get("entity_set_name") or "").lower(),
                    (row.get("description") or "").lower(),
                    (row.get("label") or "").lower(),
                ],
            )
        )
        if needle in haystack:
            matches.append(
                {
                    "entity_set_name": row["entity_set_name"],
                    "label": row.get("label"),
                    "description": row.get("description"),
                }
            )
            if len(matches) >= limit:
                break

    return ToolResult(
        status="ok",
        data={"query": query, "matches": matches},
        connection_label=resolved.label,
    ).to_dict()


sap_search_entity = StructuredTool.from_function(
    coroutine=bind_session(sap_search_entity_fn),
    name="sap_search_entity",
    description=(
        "Search the cached SAP EntitySet catalogue by name or description "
        "(case-insensitive substring match). Returns up to `limit` matches "
        "(default 10). Use this when you don't know the exact EntitySet "
        "name — e.g. 'invoice' -> 'A_BillingDocument'."
    ),
)


# ---------------------------------------------------------------------------
# Tool 3 — sap_select
# ---------------------------------------------------------------------------


async def sap_select_fn(
    entity_set: str,
    filter: str = "",
    select: str = "",
    order_by: str = "",
    top: int = DEFAULT_PAGE_SIZE,
    session_id: str = "",
) -> dict[str, Any]:
    """Run a filtered + projected OData GET on an EntitySet.

    Parameters mirror OData query options:
    * ``filter`` — ``$filter`` expression (strict whitelist applies).
    * ``select`` — CSV list of property names to project.
    * ``order_by`` — ``"prop asc, prop desc"`` style ordering.
    * ``top`` — page size (1..1000).
    """
    try:
        query = ODataQuery(
            entity_set=entity_set,
            filter=filter or None,
            select=tuple(_split_csv(select)),
            order_by=_parse_order_by(order_by),
            top=max(1, min(top, DEFAULT_MAX_TOP)),
        )
    except ValidationError as exc:
        return ToolResult(
            status="validator_rejected", error=exc.message
        ).to_dict()
    result = await execute_odata_call(
        query=query, session_id=session_id, tool_id="sap.select"
    )
    return result.to_dict()


sap_select = StructuredTool.from_function(
    coroutine=bind_session(sap_select_fn),
    name="sap_select",
    description=(
        "Run a SAP OData GET with $filter / $select / $orderby / $top. "
        "ALWAYS call sap_describe_entity first so you know the property "
        "names. Refuses any $filter containing function calls "
        "(contains/startswith/length/...) or navigation paths."
    ),
)


# ---------------------------------------------------------------------------
# Tool 4 — sap_count
# ---------------------------------------------------------------------------


async def sap_count_fn(
    entity_set: str,
    filter: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    """Return the row count of an EntitySet (optionally filtered)."""
    try:
        query = ODataQuery(
            entity_set=entity_set,
            filter=filter or None,
            count=True,
        )
    except ValidationError as exc:
        return ToolResult(
            status="validator_rejected", error=exc.message
        ).to_dict()
    result = await execute_odata_call(
        query=query, session_id=session_id, tool_id="sap.count"
    )
    return result.to_dict()


sap_count = StructuredTool.from_function(
    coroutine=bind_session(sap_count_fn),
    name="sap_count",
    description=(
        "Return the number of rows in a SAP EntitySet, with an optional "
        "$filter expression. Cheap call — use this for 'how many ...?' "
        "questions before fetching the rows."
    ),
)


# ---------------------------------------------------------------------------
# Tool 5 — sap_top_n
# ---------------------------------------------------------------------------


async def sap_top_n_fn(
    entity_set: str,
    n: int = 10,
    order_by: str = "",
    filter: str = "",
    select: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    """Return the top N rows of an EntitySet ordered by ``order_by``.

    Thin wrapper around ``$top`` + ``$orderby``. ``order_by`` defaults to
    ``""`` which means "no explicit order" — SAP returns rows in whatever
    order its index serves. For deterministic results, always pass
    ``order_by``.
    """
    n = max(1, min(n, DEFAULT_MAX_TOP))
    try:
        query = ODataQuery(
            entity_set=entity_set,
            filter=filter or None,
            select=tuple(_split_csv(select)),
            order_by=_parse_order_by(order_by),
            top=n,
        )
    except ValidationError as exc:
        return ToolResult(
            status="validator_rejected", error=exc.message
        ).to_dict()
    result = await execute_odata_call(
        query=query, session_id=session_id, tool_id="sap.top_n"
    )
    return result.to_dict()


sap_top_n = StructuredTool.from_function(
    coroutine=bind_session(sap_top_n_fn),
    name="sap_top_n",
    description=(
        "Return the top N rows of a SAP EntitySet ordered by `order_by` "
        "(e.g. 'Amount desc'). Useful for 'top X most ...' questions. "
        "Optional `filter` and `select` apply standard OData semantics."
    ),
)


# ---------------------------------------------------------------------------
# Tool 6 — sap_aggregate
# ---------------------------------------------------------------------------


async def sap_aggregate_fn(
    entity_set: str,
    aggregation: str,
    filter: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    """Run an OData ``$apply=aggregate(...)`` call.

    ``aggregation`` is the raw expression *inside* the ``aggregate(...)``
    call — e.g. ``"Amount with sum as Total, Amount with avg as Mean"``.
    Allowed ops: ``sum``, ``avg``, ``min``, ``max``, ``count``,
    ``countdistinct``. ``groupby`` is NOT supported in v1.
    """
    if not aggregation:
        return ToolResult(
            status="validator_rejected",
            error="aggregation expression must not be empty",
        ).to_dict()
    try:
        query = ODataQuery(
            entity_set=entity_set,
            filter=filter or None,
            apply=f"aggregate({aggregation})",
        )
    except ValidationError as exc:
        return ToolResult(
            status="validator_rejected", error=exc.message
        ).to_dict()
    result = await execute_odata_call(
        query=query, session_id=session_id, tool_id="sap.aggregate"
    )
    return result.to_dict()


sap_aggregate = StructuredTool.from_function(
    coroutine=bind_session(sap_aggregate_fn),
    name="sap_aggregate",
    description=(
        "Compute aggregates (sum / avg / min / max / count / countdistinct) "
        "over a SAP EntitySet. `aggregation` is the inside of `aggregate(...)` "
        "e.g. 'Amount with sum as Total, Amount with avg as Mean'. "
        "Optional `filter` applies before aggregation."
    ),
)


# ---------------------------------------------------------------------------
# Tool 7 — sap_navigate
# ---------------------------------------------------------------------------


async def sap_navigate_fn(
    entity_set: str,
    key: str,
    navigation_property: str,
    top: int = 20,
    session_id: str = "",
) -> dict[str, Any]:
    """Follow a Navigation Property from a single record.

    Issues ``GET /<entity_set>('<key>')/<navigation_property>?$top=<top>``.
    The three components are validated as simple identifiers; ``key`` is
    quoted and OData-escaped before being embedded in the path.
    """
    if not _is_simple_identifier(entity_set):
        return ToolResult(
            status="validator_rejected",
            error=f"entity_set {entity_set!r} is not a simple identifier",
        ).to_dict()
    if not _is_simple_identifier(navigation_property):
        return ToolResult(
            status="validator_rejected",
            error=(
                f"navigation_property {navigation_property!r} is not a simple identifier"
            ),
        ).to_dict()
    if not key:
        return ToolResult(
            status="validator_rejected", error="key must not be empty"
        ).to_dict()
    top = max(1, min(top, DEFAULT_MAX_TOP))

    path = f"/{entity_set}({_quote_key(key)})/{navigation_property}"
    result = await execute_raw_call(
        path_after_base=path,
        session_id=session_id,
        tool_id="sap.navigate",
        entity_set=entity_set,
        params={"$top": str(top)},
    )
    return result.to_dict()


sap_navigate = StructuredTool.from_function(
    coroutine=bind_session(sap_navigate_fn),
    name="sap_navigate",
    description=(
        "Follow a Navigation Property from a single SAP record. E.g. given "
        "BusinessPartner='11' and navigation 'to_BusinessPartnerAddress', "
        "fetch all addresses for that partner. Inspect sap_describe_entity "
        "first to see which navigations exist."
    ),
)


# ---------------------------------------------------------------------------
# Tool 8 — sap_lookup (admin only)
# ---------------------------------------------------------------------------


async def sap_lookup_fn(
    entity_set: str,
    key: str,
    select: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    """Admin-only: fetch a single record by primary key, including
    technical fields that ``sap_select`` would not typically project."""
    refusal = _require_admin_session(session_id)
    if refusal is not None:
        return ToolResult(status="forbidden", error=refusal).to_dict()

    if not _is_simple_identifier(entity_set):
        return ToolResult(
            status="validator_rejected",
            error=f"entity_set {entity_set!r} is not a simple identifier",
        ).to_dict()
    if not key:
        return ToolResult(
            status="validator_rejected", error="key must not be empty"
        ).to_dict()

    path = f"/{entity_set}({_quote_key(key)})"
    params: dict[str, str] = {}
    if select:
        # Per-segment validation is light here (admins only). The host
        # validator runs on the live URL via _send_get -> we trust admin
        # input but still strip whitespace.
        params["$select"] = ",".join(_split_csv(select))
    result = await execute_raw_call(
        path_after_base=path,
        session_id=session_id,
        tool_id="sap.lookup",
        entity_set=entity_set,
        params=params or None,
    )
    return result.to_dict()


sap_lookup = StructuredTool.from_function(
    coroutine=bind_session(sap_lookup_fn),
    name="sap_lookup",
    description=(
        "ADMIN ONLY: fetch a single SAP record by primary key, including "
        "technical fields not normally projected by sap_select. Refuses "
        "for non-admin users."
    ),
)


# ---------------------------------------------------------------------------
# Tool 9 — sap_invoke_function (admin only, read-only function imports)
# ---------------------------------------------------------------------------


async def sap_invoke_function_fn(
    function_name: str,
    params: dict[str, Any] | None = None,
    session_id: str = "",
) -> dict[str, Any]:
    """Admin-only: invoke a SAP OData function import (read-only GET).

    Parameters are inlined into the path per OData spec:
    ``/FunctionName(Param1='X',Param2=42)``. Strings are quoted; numbers
    and booleans are inlined verbatim. Mutating function imports (POST-only
    on the SAP side) are out of scope for v1 — the call will fail at the
    SAP gateway with a method-not-allowed.
    """
    refusal = _require_admin_session(session_id)
    if refusal is not None:
        return ToolResult(status="forbidden", error=refusal).to_dict()

    if not _is_simple_identifier(function_name):
        return ToolResult(
            status="validator_rejected",
            error=f"function_name {function_name!r} is not a simple identifier",
        ).to_dict()

    rendered_params = _render_function_params(params or {})
    if isinstance(rendered_params, ToolResult):
        return rendered_params.to_dict()

    path = f"/{function_name}({rendered_params})"
    result = await execute_raw_call(
        path_after_base=path,
        session_id=session_id,
        tool_id="sap.invoke_function",
    )
    return result.to_dict()


def _render_function_params(params: dict[str, Any]) -> Any:
    """Render ``{name: value}`` into the OData ``(Name='X', N=42)`` syntax.

    Returns a string on success, or a :class:`ToolResult` carrying a
    validation refusal on failure.
    """
    chunks: list[str] = []
    for name, value in params.items():
        if not _is_simple_identifier(name):
            return ToolResult(
                status="validator_rejected",
                error=f"parameter name {name!r} is not a simple identifier",
            )
        if isinstance(value, bool):
            chunks.append(f"{name}={'true' if value else 'false'}")
        elif isinstance(value, (int, float)):
            chunks.append(f"{name}={value}")
        elif isinstance(value, str):
            chunks.append(f"{name}={_quote_key(value)}")
        else:
            return ToolResult(
                status="validator_rejected",
                error=(
                    f"parameter {name!r} has unsupported type "
                    f"{type(value).__name__}"
                ),
            )
    return ",".join(chunks)


sap_invoke_function = StructuredTool.from_function(
    coroutine=bind_session(sap_invoke_function_fn),
    name="sap_invoke_function",
    description=(
        "ADMIN ONLY: invoke a SAP OData function import (read-only GET). "
        "Pass parameters as a dict: {'CompanyCode': '1000', 'Year': 2026}. "
        "Strings are quoted automatically. Refuses for non-admin users."
    ),
)


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "id": "sap.describe_entity",
        "tool": sap_describe_entity,
        "label_key": "sap.tools.describe_entity.label",
        "description_key": "sap.tools.describe_entity.description",
    },
    {
        "id": "sap.search_entity",
        "tool": sap_search_entity,
        "label_key": "sap.tools.search_entity.label",
        "description_key": "sap.tools.search_entity.description",
    },
    {
        "id": "sap.select",
        "tool": sap_select,
        "label_key": "sap.tools.select.label",
        "description_key": "sap.tools.select.description",
    },
    {
        "id": "sap.count",
        "tool": sap_count,
        "label_key": "sap.tools.count.label",
        "description_key": "sap.tools.count.description",
    },
    {
        "id": "sap.top_n",
        "tool": sap_top_n,
        "label_key": "sap.tools.top_n.label",
        "description_key": "sap.tools.top_n.description",
    },
    {
        "id": "sap.aggregate",
        "tool": sap_aggregate,
        "label_key": "sap.tools.aggregate.label",
        "description_key": "sap.tools.aggregate.description",
    },
    {
        "id": "sap.navigate",
        "tool": sap_navigate,
        "label_key": "sap.tools.navigate.label",
        "description_key": "sap.tools.navigate.description",
    },
    {
        "id": "sap.lookup",
        "tool": sap_lookup,
        "label_key": "sap.tools.lookup.label",
        "description_key": "sap.tools.lookup.description",
    },
    {
        "id": "sap.invoke_function",
        "tool": sap_invoke_function,
        "label_key": "sap.tools.invoke_function.label",
        "description_key": "sap.tools.invoke_function.description",
    },
]


def wire_tools() -> None:
    """Register all SAP agent tools with the host's tool registry.

    Idempotent: a re-import (e.g. plugin hot reload in dev) replaces the
    existing registrations via ``on_duplicate='replace'``.
    """
    for spec in _TOOL_SPECS:
        register_tool({**spec, "requires": "connectors.sap.s4hana_cloud"}, on_duplicate="replace")


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "sap_aggregate",
    "sap_aggregate_fn",
    "sap_count",
    "sap_count_fn",
    "sap_describe_entity",
    "sap_describe_entity_fn",
    "sap_invoke_function",
    "sap_invoke_function_fn",
    "sap_lookup",
    "sap_lookup_fn",
    "sap_navigate",
    "sap_navigate_fn",
    "sap_search_entity",
    "sap_search_entity_fn",
    "sap_select",
    "sap_select_fn",
    "sap_top_n",
    "sap_top_n_fn",
    "wire_tools",
]
