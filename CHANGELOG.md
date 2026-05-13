# Changelog — piilot-pack-sap

Notable changes to this plugin are tracked here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This
plugin follows [Semantic Versioning](https://semver.org/).

> **Relation to the Piilot SDK**
>
> Every release of this plugin pins a Piilot SDK range via
> `sdk_compat` in `pyproject.toml`. A breaking SDK bump (e.g. 1.x →
> 2.x) requires a new major release of this plugin.

---

## [Unreleased]

### Roadmap

* **Phase 1** — Introspection `$metadata` XML → `schema_snapshot` cache
  + KB template seeding via `register_kb_template` (SDK 0.7). Strict
  whitelist OData parser/validator (no `$expand`, no `$batch`, no
  function imports in writes).
* **Phase 2** — 9 agent tools (`sap_search_entity`, `sap_describe_entity`,
  `sap_select`, `sap_count`, `sap_aggregate`, `sap_top_n`,
  `sap_navigate`, `sap_lookup`, `sap_invoke_function`). All wrapped with
  `bind_session` per SDK 0.6+ convention.
* **Phase 3** — Frontend `SAPConnectorView` with 4 internal tabs
  (Connection / Status / Browser / Audit).
* **Phase 4** — Hardening (parser OData fuzzing, prompt-injection tests,
  rate limit per-company, cost guard rails).
* **Phase 5** — Beta dogfood on a real SAP S/4HANA Cloud partner
  instance. Add agent templates (SAP-FI Auditor, SAP-CO Controller).

---

## [0.1.0] — Phase 0 scaffolding (unreleased)

### Added

- **Manifest** declaring the `sap` namespace, the single module Piilot
  `sap.connector` (canonical 1-plugin-1-module pattern aligned with
  `piilot-pack-pennylane` and `piilot-pack-supabase`), and the
  `sap.s4hana_cloud` connector with custom auth handling Basic and
  OAuth 2.0 `client_credentials`.
- **Migration `001_init_sap.sql`** — idempotent DDL for the
  `integrations_sap` schema with three tables :
  - `connections` (per-company connection metadata, encrypted creds
    live in core's `plugin_connections`),
  - `schema_snapshot` (`$metadata` introspection cache, populated in
    Phase 1),
  - `audit_log` (immutable trail of every OData query, populated in
    Phase 2).
  RLS policies on all three tables. Maintenance triggers on
  `updated_at`.
- **i18n catalogs** (FR + EN) for the module label and the connector's
  credentials schema fields.
- **Frontend** `SAPConnectorView` placeholder with phase banner. The
  4-tab UX (Connection / Status / Browser / Audit) lands in Phase 3.
- **Smoke tests** — boot test, manifest validation, single-module
  assertion, handler shape.

### Notes

- SDK pin set to `>=0.7.0,<1.0.0` (KB templates primitive shipped in
  0.7).
- No agent tools shipped yet (Phase 2 deliverable). `wire_tools()` is
  a no-op.
- No agent template / KB template seeded yet. Phase 1 will seed the KB
  template "SAP metadata" via `register_kb_template`. Phase 5 will seed
  agent templates against a real partner instance.
- Cible v1 — SAP S/4HANA Cloud only (OData v4 standardisé). On-premise
  + ECC reportés à v2+.
- Auth modes shipped in v1 — Basic + OAuth 2.0 `client_credentials`.
  X.509 reporté à v1.1.
- Parser OData scope strict — whitelist `$filter` (eq/ne/gt/lt/ge/le/
  and/or/not), `$select`, `$top`, `$orderby`, `$count`, `$apply=
  aggregate`. Refuse `$expand`, `$batch`, function imports en écriture,
  lambda operators, cast, isof.
