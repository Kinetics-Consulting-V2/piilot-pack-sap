"""Piilot plugin ``sap`` — SAP S/4HANA Cloud OData connector.

Entry point of the plugin. The ``Plugin`` class is referenced by
``[project.entry-points."piilot.plugins"]`` in ``pyproject.toml`` and
instantiated once at Piilot backend startup.

What this plugin provides (v0.1.0 — Phases 0 + 1 + 2 shipped)
-------------------------------------------------------------

* **1 module Piilot** ``sap.connector`` — single ModuleView that carries
  the whole plugin UX (connection config, status, entity browser, audit
  log). Pattern aligned with ``piilot-pack-pennylane`` and
  ``piilot-pack-supabase``.

* **1 connector** ``sap.s4hana_cloud`` — Basic auth + OAuth 2.0
  ``client_credentials`` against a SAP S/4HANA Cloud OData v2 / v4
  endpoint (auto-detected from ``$metadata``).

* **Migrations** ``integrations_sap.{connections, schema_snapshot,
  audit_log}`` — per-company connection storage, $metadata snapshot,
  immutable audit trail of OData queries.

* **9 agent tools** — ``sap_describe_entity``, ``sap_search_entity``,
  ``sap_select``, ``sap_count``, ``sap_top_n``, ``sap_aggregate``,
  ``sap_navigate``, ``sap_lookup`` (admin), ``sap_invoke_function``
  (admin). Strict whitelist OData validator. Audit log on every call.

Roadmap
-------

* Phase 3 — Frontend ``SAPConnectorView`` with 4 internal tabs
  (Connection / Status / Browser / Audit).
* Phase 4 — Hardening (prompt-injection tests, rate limit per-company,
  cost guard rails).
* Phase 5 — Beta dogfood on real SAP partner instance + agent templates
  (SAP-FI Auditor, SAP-CO Controller).

Full SDK reference: ``docs/sdk/PLUGIN_DEVELOPMENT.md`` in the Piilot
core repo. Pitfalls and pre-tag checklist:
``docs/sdk/PLUGIN_DEV_WORKFLOW.md``.
"""

from __future__ import annotations

from piilot.sdk import Plugin as _Plugin
from piilot.sdk import load_manifest

from .connector import wire_connectors
from .handlers import sap_connector_handler
from .routes import wire_routes
from .seeds import wire_seeds
from .tools import wire_tools


class Plugin(_Plugin):
    """Plugin entry class — must subclass ``piilot.sdk.Plugin``."""

    manifest = load_manifest(__file__)

    def register(self, ctx) -> None:
        """Wire up everything this plugin provides.

        Called once at backend startup with a boot-time ``Context``
        (``ctx.company`` is None here; runtime contexts are built per
        request later on).
        """
        # ---- Migrations: integrations_sap.{connections, schema_snapshot,
        #      audit_log} ----
        ctx.migrations.register_schema(
            "sap",
            __file__,
            "migrations",
        )

        # ---- i18n catalogs (FR + EN) ----
        ctx.i18n.register_locales(
            "sap",
            __file__,
            "locales",
        )

        # ---- Module handler ----
        # The id MUST match provides.modules[].id in pyproject.toml.
        ctx.handlers.register("sap.connector", sap_connector_handler)

        # ---- SDK primitives ----
        wire_routes()        # HTTP endpoints under /plugins/sap/*
        wire_tools()         # 9 OData agent tools (Phase 2)
        wire_seeds()         # Module row seed (sap.connector)
        wire_connectors()    # SAP S/4HANA Cloud connector spec
