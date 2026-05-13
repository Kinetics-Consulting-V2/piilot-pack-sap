"""Seed the ``sap.connector`` module row.

Called from ``Plugin.register()``. The :func:`register_module` call is
idempotent — re-installing the plugin refreshes descriptive columns
(name, icon, description) while preserving the row's UUID so user
grants / bookmarks stay stable.

Agent templates and KB templates are NOT seeded in Phase 0. They will
be added later:

* Phase 1 — KB template "SAP metadata" via ``register_kb_template`` once
  the ``$metadata`` introspection lands.
* Phase 5 — Agent templates (SAP-FI Auditor, SAP-CO Controller…) once we
  have a real SAP partner instance to dogfood against.
"""

from __future__ import annotations

from piilot.sdk.modules import register_module


def wire_seeds() -> None:
    """Register the SAP connector module row."""

    register_module(
        {
            "slug": "sap.connector",
            "module_name": "SAP S/4HANA Cloud",
            "description": (
                "Connect to a SAP S/4HANA Cloud instance via OData v4. "
                "Read-only agent access to FI / CO / MM / SD entities "
                "for financial and operational analytics."
            ),
            "icon": "plug",
            "category": "integration",
            "status": "published",
            "config": {
                "type": "connector",
                "supports_basic_auth": True,
                "supports_oauth_client_credentials": True,
            },
        }
    )
