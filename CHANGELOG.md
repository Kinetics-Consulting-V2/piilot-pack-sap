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

### Added — Phase 1 Bloc B (network + auth + sandbox round-trip)

- **`piilot_pack_sap/auth.py`** — three pluggable async auth strategies
  sharing a single `Auth` protocol: `ApiKeyAuth` (SAP API Hub header),
  `BasicAuth` (RFC 7617, used for SAP technical users), and
  `OAuthClientCredentials` (OAuth 2.0 client_credentials with
  in-memory token cache, expiry-buffer refresh, and concurrent-fetch
  serialization via `asyncio.Lock`).
- **`piilot_pack_sap/odata_client.py`** — async OData v2 / v4 HTTP
  client built on `httpx.AsyncClient`. Wires the validator on every
  outgoing request (`ODataQuery.build_url`). Implements bounded
  retries with full-jitter exponential backoff on transient errors
  (`429` honoring `Retry-After`, `5xx`, connection errors); never
  retries on definitive 4xx. Versioned headers (`OData-MaxVersion` /
  `OData-Version` on v4 only). `$metadata` fetched with
  `Accept: application/xml`. `$count` v2 path-segment responses
  normalized to `{"count": <int>}`.
- **`tests/test_auth.py`** + **`tests/test_auth_oauth.py`** +
  **`tests/test_odata_client.py`** — 45 unit tests using `respx` to
  mock httpx. Covers happy path, retry policy, Retry-After parsing
  (seconds + HTTP-date), connection error fallback, header injection
  per auth mode, OAuth token cache / refresh / 401 / non-JSON / missing
  expires_in / concurrent fetch.
- **`tests/integration/`** — 5 live tests against
  `sandbox.api.sap.com` (skip-auto when `SAP_API_HUB_KEY` env var is
  absent, pytest marker `integration`). Loads optional `.env.dev` via
  `python-dotenv`. Covers BP fetch, `$metadata` parse round-trip,
  `$filter`+`$select`, `$count` v2 path segment, invalid key → 401/403.

### Changed

- **`query_builder.py`** — v2 `$count` requests no longer emit
  `$format=json`. SAP gateways serve the count as `text/plain` and
  return `HTTP 400` when `$format=json` is set alongside `/$count`.
  The body is still consumed by the client and surfaced as
  `{"count": <int>}` for caller consistency.

### Fixed

- **`odata_validator.ValidationError`** and **`odata_client.ODataHTTPError`** — switched from `@dataclass(frozen=True)` to plain
  `Exception` subclasses. The frozen variant raised
  `FrozenInstanceError` when the runtime attached `__traceback__`
  during propagation through `async with` blocks. Public surface
  (`.code` / `.message` / `.status` attributes, `str(exc)` format)
  is preserved.

### Roadmap

* **Phase 1 Bloc C** — Persist `schema_snapshot` (already-existing
  `integrations_sap.schema_snapshot` table). Seed KB plugin-owned
  "SAP metadata" via `register_kb_template` (SDK 0.7). Embed entities
  asynchronously. Wire audit log writes.
* **Phase 2** — 9 agent tools (`sap_search_entity`,
  `sap_describe_entity`, `sap_select`, `sap_count`, `sap_aggregate`,
  `sap_top_n`, `sap_navigate`, `sap_lookup`, `sap_invoke_function`).
  All wrapped with `bind_session` per SDK 0.6+ convention.
* **Phase 3** — Frontend `SAPConnectorView` with 4 internal tabs
  (Connection / Status / Browser / Audit).
* **Phase 4** — Hardening (parser OData fuzzing already shipped,
  add prompt-injection tests, rate limit per-company, cost guard
  rails).
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
