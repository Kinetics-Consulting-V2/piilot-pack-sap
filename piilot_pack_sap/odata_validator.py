"""Strict OData v2/v4 query validator (read-only whitelist grammar).

Refuses everything that is not on the whitelist by design. The intent is to
expose SAP S/4HANA data to LLM agents through a narrow, auditable surface,
not to be a full OData parser.

Whitelist (v1):

* HTTP method ``GET`` only.
* Query options: ``$filter``, ``$select``, ``$top``, ``$skip``, ``$orderby``,
  ``$count`` (v4 inline form), ``$apply`` (``aggregate`` shape only),
  ``$format`` (``json`` only).
* ``$filter`` operators: ``eq ne gt lt ge le and or not`` + parens.
* ``$filter`` operands: simple property names, string literals
  (``'...'`` with ``''`` escape), numbers, ``datetime'...'`` /
  ``datetimeoffset'...'`` (v2), ISO 8601 (v4), ``null``, ``true``, ``false``.
* No function calls in ``$filter``, no lambda operators, no navigation paths
  (slash-separated identifiers), no casts.
* ``$apply`` accepts only ``aggregate(<prop> with <op> as <alias>[, ...])``
  with ``op`` in ``sum avg min max count countdistinct``.

Anything else raises :class:`ValidationError` with a machine-readable code and
a human-readable message. Validation is fail-closed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

ODataVersion = Literal["v2", "v4"]

ALLOWED_QUERY_OPTIONS: frozenset[str] = frozenset(
    {
        "$filter",
        "$select",
        "$top",
        "$skip",
        "$orderby",
        "$count",
        "$apply",
        "$format",
    }
)

EXPLICITLY_FORBIDDEN_QUERY_OPTIONS: frozenset[str] = frozenset(
    {
        "$expand",
        "$batch",
        "$inlinecount",
        "$links",
        "$value",
        "$ref",
        "$search",
        "$compute",
        "$schemaversion",
    }
)

COMPARISON_OPS: frozenset[str] = frozenset({"eq", "ne", "gt", "lt", "ge", "le"})
LOGICAL_OPS: frozenset[str] = frozenset({"and", "or"})
UNARY_OPS: frozenset[str] = frozenset({"not"})
LITERAL_KEYWORDS: frozenset[str] = frozenset({"null", "true", "false"})

AGGREGATE_OPS: frozenset[str] = frozenset({"sum", "avg", "min", "max", "count", "countdistinct"})

DEFAULT_MAX_TOP = 1000

IDENT_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\Z")


class ValidationError(Exception):
    """Raised when an OData request fails the whitelist.

    Plain ``Exception`` subclass (not a frozen dataclass) so the runtime can
    attach ``__traceback__`` / ``__cause__`` during propagation.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"[{self.code}] {self.message}"


def validate_request(
    method: str,
    query_params: dict[str, str],
    *,
    version: ODataVersion = "v2",
    max_top: int = DEFAULT_MAX_TOP,
    allowed_properties: Iterable[str] | None = None,
) -> None:
    """Validate an OData GET request. Raises :class:`ValidationError` on first failure.

    ``allowed_properties`` — optional set of property identifiers that the
    request may reference. If provided, every identifier appearing in
    ``$select``, ``$orderby``, ``$apply``, and ``$filter`` must be a member.
    If ``None``, the validator enforces only the grammar.
    """
    if method.upper() != "GET":
        raise ValidationError(
            code="method_not_allowed",
            message=f"only GET is allowed, got {method!r}",
        )

    allowed_set: frozenset[str] | None = (
        frozenset(allowed_properties) if allowed_properties is not None else None
    )

    for key in query_params:
        lower = key.lower()
        if lower in EXPLICITLY_FORBIDDEN_QUERY_OPTIONS:
            raise ValidationError(
                code="forbidden_query_option",
                message=f"query option {key!r} is forbidden in v1",
            )
        if key.startswith("$") and lower not in ALLOWED_QUERY_OPTIONS:
            raise ValidationError(
                code="unknown_query_option",
                message=f"query option {key!r} is not on the whitelist",
            )

    if "$top" in query_params:
        _validate_top(query_params["$top"], max_top=max_top)
    if "$skip" in query_params:
        _validate_skip(query_params["$skip"])
    if "$format" in query_params:
        _validate_format(query_params["$format"])
    if "$count" in query_params:
        _validate_count(query_params["$count"], version=version)
    if "$select" in query_params:
        _validate_select(query_params["$select"], allowed=allowed_set)
    if "$orderby" in query_params:
        _validate_orderby(query_params["$orderby"], allowed=allowed_set)
    if "$apply" in query_params:
        _validate_apply(query_params["$apply"], allowed=allowed_set)
    if "$filter" in query_params:
        _validate_filter(query_params["$filter"], version=version, allowed=allowed_set)


def _validate_top(raw: str, *, max_top: int) -> None:
    if not raw.isdigit():
        raise ValidationError(
            code="invalid_top",
            message=f"$top must be a non-negative integer, got {raw!r}",
        )
    value = int(raw)
    if value < 1:
        raise ValidationError(
            code="invalid_top",
            message="$top must be at least 1",
        )
    if value > max_top:
        raise ValidationError(
            code="top_exceeds_max",
            message=f"$top={value} exceeds the configured max of {max_top}",
        )


def _validate_skip(raw: str) -> None:
    if not raw.isdigit():
        raise ValidationError(
            code="invalid_skip",
            message=f"$skip must be a non-negative integer, got {raw!r}",
        )


def _validate_format(raw: str) -> None:
    if raw.strip().lower() != "json":
        raise ValidationError(
            code="invalid_format",
            message=f"$format must be 'json', got {raw!r}",
        )


def _validate_count(raw: str, *, version: ODataVersion) -> None:
    if version == "v2":
        raise ValidationError(
            code="count_inline_v2_unsupported",
            message=(
                "inline $count query option is OData v4 only; "
                "use the /$count path segment for v2"
            ),
        )
    if raw.strip().lower() not in {"true", "false"}:
        raise ValidationError(
            code="invalid_count",
            message=f"$count must be 'true' or 'false', got {raw!r}",
        )


def _validate_select(raw: str, *, allowed: frozenset[str] | None) -> None:
    if not raw.strip():
        raise ValidationError(
            code="empty_select",
            message="$select must not be empty",
        )
    for item in raw.split(","):
        prop = item.strip()
        _ensure_simple_identifier(prop, where="$select")
        _ensure_in_allowed(prop, allowed=allowed, where="$select")


def _validate_orderby(raw: str, *, allowed: frozenset[str] | None) -> None:
    if not raw.strip():
        raise ValidationError(
            code="empty_orderby",
            message="$orderby must not be empty",
        )
    for item in raw.split(","):
        parts = item.strip().split()
        if len(parts) == 0 or len(parts) > 2:
            raise ValidationError(
                code="invalid_orderby",
                message=f"$orderby item {item!r} must be '<prop> [asc|desc]'",
            )
        prop = parts[0]
        _ensure_simple_identifier(prop, where="$orderby")
        _ensure_in_allowed(prop, allowed=allowed, where="$orderby")
        if len(parts) == 2 and parts[1].lower() not in {"asc", "desc"}:
            raise ValidationError(
                code="invalid_orderby_direction",
                message=f"$orderby direction must be 'asc' or 'desc', got {parts[1]!r}",
            )


_APPLY_RE = re.compile(r"\A\s*aggregate\s*\((.*)\)\s*\Z", re.DOTALL)
_APPLY_AGG_ITEM_RE = re.compile(
    r"\A\s*(?P<prop>[A-Za-z_][A-Za-z0-9_]*)?\s*"
    r"(?:with\s+(?P<op>[A-Za-z]+))\s+"
    r"as\s+(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\s*\Z"
)


def _validate_apply(raw: str, *, allowed: frozenset[str] | None) -> None:
    """Allow only ``aggregate(<prop> with <op> as <alias>[, ...])``.

    Special case: ``aggregate($count as Alias)`` is rejected — use the
    dedicated ``$count`` query option instead. This keeps the grammar
    aggressively small and avoids parsing OData's special ``$count`` literal
    inside ``$apply``.
    """
    match = _APPLY_RE.match(raw)
    if match is None:
        raise ValidationError(
            code="invalid_apply",
            message=("$apply only supports a single aggregate(...) call in v1; " f"got {raw!r}"),
        )
    body = match.group(1)
    items = _split_top_level_commas(body)
    if not items:
        raise ValidationError(
            code="empty_apply",
            message="$apply aggregate(...) must contain at least one aggregation",
        )
    for item in items:
        m = _APPLY_AGG_ITEM_RE.match(item)
        if m is None:
            raise ValidationError(
                code="invalid_apply_item",
                message=(f"$apply aggregation {item!r} must be " "'<prop> with <op> as <alias>'"),
            )
        prop = m.group("prop") or ""
        op = (m.group("op") or "").lower()
        if op not in AGGREGATE_OPS:
            raise ValidationError(
                code="invalid_aggregate_op",
                message=(
                    f"aggregate op {op!r} not allowed; " f"choose from {sorted(AGGREGATE_OPS)}"
                ),
            )
        # For non-count ops we need a property; for count/countdistinct it may
        # legitimately be empty (count(*) shape) but OData spec actually wants
        # an explicit prop or $count keyword. We require a prop in v1 for all
        # ops except ``count``.
        if op != "count":
            if not prop:
                raise ValidationError(
                    code="missing_aggregate_prop",
                    message=f"aggregate op {op!r} requires a property",
                )
            _ensure_in_allowed(prop, allowed=allowed, where="$apply")
        elif prop:
            _ensure_in_allowed(prop, allowed=allowed, where="$apply")


# ---------- $filter tokenizer + recursive descent parser --------------------

_TOKEN_RE = re.compile(
    r"""
      (?P<WS>\s+)
    | (?P<STRING>'(?:[^']|'')*')
    | (?P<DATETIME>datetime(?:offset)?'[^']+')
    | (?P<NUMBER>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?[mMlLfFdD]?)
    | (?P<LPAREN>\()
    | (?P<RPAREN>\))
    | (?P<COMMA>,)
    | (?P<IDENT>[A-Za-z_][A-Za-z0-9_]*)
    | (?P<INVALID>.)
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str
    pos: int


def _tokenize_filter(raw: str) -> list[_Token]:
    tokens: list[_Token] = []
    for m in _TOKEN_RE.finditer(raw):
        kind = m.lastgroup or "INVALID"
        if kind == "WS":
            continue
        if kind == "INVALID":
            raise ValidationError(
                code="invalid_filter_char",
                message=f"unexpected character {m.group()!r} at position {m.start()}",
            )
        tokens.append(_Token(kind=kind, value=m.group(), pos=m.start()))
    return tokens


class _FilterParser:
    """Recursive descent parser for the whitelist $filter grammar.

    Does not build an AST — succeeds silently or raises ValidationError.
    """

    def __init__(
        self,
        tokens: list[_Token],
        *,
        version: ODataVersion,
        allowed: frozenset[str] | None,
    ) -> None:
        self._tokens = tokens
        self._pos = 0
        self._version = version
        self._allowed = allowed

    def parse(self) -> None:
        if not self._tokens:
            raise ValidationError(
                code="empty_filter",
                message="$filter must not be empty",
            )
        self._or_expr()
        if self._pos != len(self._tokens):
            tok = self._tokens[self._pos]
            raise ValidationError(
                code="trailing_filter_tokens",
                message=f"unexpected token {tok.value!r} at position {tok.pos}",
            )

    def _peek(self) -> _Token | None:
        if self._pos < len(self._tokens):
            return self._tokens[self._pos]
        return None

    def _advance(self) -> _Token:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _or_expr(self) -> None:
        self._and_expr()
        while True:
            tok = self._peek()
            if tok is None or tok.kind != "IDENT" or tok.value.lower() != "or":
                return
            self._advance()
            self._and_expr()

    def _and_expr(self) -> None:
        self._not_expr()
        while True:
            tok = self._peek()
            if tok is None or tok.kind != "IDENT" or tok.value.lower() != "and":
                return
            self._advance()
            self._not_expr()

    def _not_expr(self) -> None:
        tok = self._peek()
        if tok is not None and tok.kind == "IDENT" and tok.value.lower() == "not":
            self._advance()
            self._not_expr()
            return
        self._comparison()

    def _comparison(self) -> None:
        self._primary()
        tok = self._peek()
        if tok is not None and tok.kind == "IDENT" and tok.value.lower() in COMPARISON_OPS:
            self._advance()
            self._primary()

    def _primary(self) -> None:
        tok = self._peek()
        if tok is None:
            raise ValidationError(
                code="unexpected_filter_end",
                message="unexpected end of $filter expression",
            )
        if tok.kind == "LPAREN":
            self._advance()
            self._or_expr()
            close = self._peek()
            if close is None or close.kind != "RPAREN":
                raise ValidationError(
                    code="unclosed_paren",
                    message=f"missing closing ')' at position {tok.pos}",
                )
            self._advance()
            return
        if tok.kind == "IDENT":
            value_lower = tok.value.lower()
            if value_lower in LOGICAL_OPS or value_lower in UNARY_OPS:
                raise ValidationError(
                    code="misplaced_operator",
                    message=(f"operator {tok.value!r} cannot appear here " f"(position {tok.pos})"),
                )
            if value_lower in COMPARISON_OPS:
                raise ValidationError(
                    code="misplaced_comparison",
                    message=(
                        f"comparison operator {tok.value!r} cannot appear here "
                        f"(position {tok.pos})"
                    ),
                )
            self._advance()
            next_tok = self._peek()
            if next_tok is not None and next_tok.kind == "LPAREN":
                raise ValidationError(
                    code="function_call_forbidden",
                    message=(
                        f"function call {tok.value!r}(...) is not allowed in $filter "
                        "(whitelist v1 refuses all function calls including "
                        "any/all/cast/isof/length/substring/contains/...)"
                    ),
                )
            if value_lower in LITERAL_KEYWORDS:
                return
            # Treated as a property reference.
            _ensure_in_allowed(tok.value, allowed=self._allowed, where="$filter")
            return
        if tok.kind in {"STRING", "NUMBER", "DATETIME"}:
            if tok.kind == "DATETIME" and self._version == "v4":
                raise ValidationError(
                    code="v2_datetime_literal_in_v4",
                    message=(
                        "datetime'…' / datetimeoffset'…' literals are v2-only; "
                        "use ISO 8601 strings in v4"
                    ),
                )
            self._advance()
            return
        raise ValidationError(
            code="unexpected_filter_token",
            message=f"unexpected token {tok.value!r} at position {tok.pos}",
        )


def _validate_filter(
    raw: str,
    *,
    version: ODataVersion,
    allowed: frozenset[str] | None,
) -> None:
    if not raw.strip():
        raise ValidationError(
            code="empty_filter",
            message="$filter must not be empty",
        )
    tokens = _tokenize_filter(raw)
    parser = _FilterParser(tokens, version=version, allowed=allowed)
    parser.parse()


def _ensure_simple_identifier(value: str, *, where: str) -> None:
    if not IDENT_RE.match(value):
        raise ValidationError(
            code="invalid_identifier",
            message=(
                f"{where} identifier {value!r} is not a simple property name "
                "(navigation paths and special chars are forbidden in v1)"
            ),
        )


def _ensure_in_allowed(
    value: str,
    *,
    allowed: frozenset[str] | None,
    where: str,
) -> None:
    if allowed is None:
        _ensure_simple_identifier(value, where=where)
        return
    if value not in allowed:
        raise ValidationError(
            code="unknown_property",
            message=f"{where} references unknown property {value!r}",
        )


def _split_top_level_commas(raw: str) -> list[str]:
    """Split on commas that are not inside parentheses."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in raw:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                raise ValidationError(
                    code="unbalanced_parens",
                    message="unbalanced parentheses in $apply",
                )
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if depth != 0:
        raise ValidationError(
            code="unbalanced_parens",
            message="unbalanced parentheses in $apply",
        )
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return [p.strip() for p in parts if p.strip()]


__all__ = [
    "ALLOWED_QUERY_OPTIONS",
    "EXPLICITLY_FORBIDDEN_QUERY_OPTIONS",
    "COMPARISON_OPS",
    "LOGICAL_OPS",
    "AGGREGATE_OPS",
    "DEFAULT_MAX_TOP",
    "ValidationError",
    "validate_request",
]
