"""Module handler for ``sap.connector``.

Dispatched by the Piilot module runtime when a user opens the
``sap.connector`` module from the UI. Registered in
``__init__.py::Plugin.register()``.

The handler is intentionally minimal in Phase 0 — the real UX lives in
the React ``SAPConnectorView`` (frontend), which calls the plugin's
HTTP routes (``/plugins/sap/*``) for connection config, health check,
schema browser, etc.
"""

from __future__ import annotations

from typing import Any


def sap_connector_handler(ctx: Any, payload: dict) -> dict:
    """Module handler for ``sap.connector``.

    Returns an introspection summary describing the plugin's current
    state for the active company. The real wiring (list connections,
    test reachability, count audit rows) lands in Phase 1.
    """
    company_label = ctx.company.name if ctx.company else "<no company bound>"
    ctx.logger.info("sap.connector handler invoked for %s", company_label)
    return {
        "status": "ok",
        "module": "sap.connector",
        "company": company_label,
        "phase": "0-scaffolding",
        "next": "Phase 1 — introspection $metadata + KB template",
    }
