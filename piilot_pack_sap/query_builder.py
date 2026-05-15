"""OData query composition + URL building.

Builds the ``(path, params)`` tuple consumed by :class:`httpx.AsyncClient`.
Every query is validated by :mod:`piilot_pack_sap.odata_validator` before the
path is returned — invalid queries never leave this module.

The v2 / v4 split is handled in one place:

* ``$count`` is a path segment in v2 (``…/A_BusinessPartner/$count``) and a
  query option in v4 (``…/Orders?$count=true``).
* ``datetime'…'`` literals are v2 only; v4 uses ISO 8601 strings.

Callers should treat :class:`ODataQuery` as immutable: replace with a new
instance instead of mutating.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from piilot_pack_sap.odata_validator import (
    DEFAULT_MAX_TOP,
    ODataVersion,
    validate_request,
)

OrderDirection = Literal["asc", "desc"]


@dataclass(frozen=True)
class ODataQuery:
    """A read-only OData query specification.

    :param entity_set: e.g. ``"A_BusinessPartner"``.
    :param select: tuple of property names to project. Empty means server default.
    :param filter: raw ``$filter`` expression (will be validated).
    :param order_by: tuple of ``(property, direction)`` pairs.
    :param top: maximum number of records to return.
    :param skip: number of records to skip (pagination).
    :param count: include row count. v4 inline, v2 path segment.
    :param apply: raw ``$apply`` aggregate expression.
    :param format: response format. Defaults to ``"json"`` when emitted.
    """

    entity_set: str
    select: tuple[str, ...] = ()
    filter: str | None = None
    order_by: tuple[tuple[str, OrderDirection], ...] = ()
    top: int | None = None
    skip: int | None = None
    count: bool = False
    apply: str | None = None
    format: str | None = "json"

    def build_url(
        self,
        base_path: str,
        *,
        version: ODataVersion = "v2",
        max_top: int = DEFAULT_MAX_TOP,
        allowed_properties: Iterable[str] | None = None,
    ) -> tuple[str, dict[str, str]]:
        """Return ``(path, params)`` ready for an HTTP GET.

        Raises :class:`piilot_pack_sap.odata_validator.ValidationError` on any
        whitelist violation.
        """
        if not self.entity_set or not _is_simple_segment(self.entity_set):
            from piilot_pack_sap.odata_validator import ValidationError

            raise ValidationError(
                code="invalid_entity_set",
                message=(
                    f"entity_set {self.entity_set!r} must be a simple identifier"
                ),
            )

        path = f"{base_path.rstrip('/')}/{self.entity_set}"
        params: dict[str, str] = {}

        if self.count and version == "v2":
            path = f"{path}/$count"
            # In v2, $count path mode supports $filter as the only useful query
            # option. Other options (select, orderby, top, skip, apply) would
            # be ignored or cause errors server-side, so we refuse them up
            # front to keep the contract obvious.
            if any(
                [
                    self.select,
                    self.order_by,
                    self.top is not None,
                    self.skip is not None,
                    self.apply,
                ]
            ):
                from piilot_pack_sap.odata_validator import ValidationError

                raise ValidationError(
                    code="count_v2_extra_options",
                    message=(
                        "v2 $count path segment only allows $filter; drop "
                        "$select / $orderby / $top / $skip / $apply"
                    ),
                )
            if self.filter is not None:
                params["$filter"] = self.filter
            # NB: $format=json is intentionally NOT emitted on v2 /$count —
            # SAP gateways return HTTP 400 because the endpoint serves
            # text/plain (a raw integer), not JSON. The client overrides the
            # Accept header to text/plain when needed; the caller asks the
            # ODataClient for the count and gets {"count": <int>} regardless.
            validate_request(
                "GET",
                params,
                version=version,
                max_top=max_top,
                allowed_properties=allowed_properties,
            )
            return path, params

        if self.select:
            params["$select"] = ",".join(self.select)
        if self.filter is not None:
            params["$filter"] = self.filter
        if self.order_by:
            params["$orderby"] = ",".join(
                f"{name} {direction}" for name, direction in self.order_by
            )
        if self.top is not None:
            params["$top"] = str(self.top)
        if self.skip is not None:
            params["$skip"] = str(self.skip)
        if self.count and version == "v4":
            params["$count"] = "true"
        if self.apply is not None:
            params["$apply"] = self.apply
        if self.format is not None:
            params["$format"] = self.format

        validate_request(
            "GET",
            params,
            version=version,
            max_top=max_top,
            allowed_properties=allowed_properties,
        )
        return path, params


def _is_simple_segment(value: str) -> bool:
    """Entity sets must be plain identifiers — no slashes, no parens."""
    if not value:
        return False
    return all(ch.isalnum() or ch == "_" for ch in value) and not value[0].isdigit()


__all__ = ["ODataQuery", "OrderDirection"]
