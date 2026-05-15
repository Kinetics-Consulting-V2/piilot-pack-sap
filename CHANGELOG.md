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

### Added — Phase 3 (HTTP routes CRUD + frontend SAPConnectorView)

- **`piilot_pack_sap/routes.py`** — 11 endpoints under
  ``/plugins/sap/*``. Connection CRUD (``GET / POST / PATCH / DELETE``)
  with ``require_user`` / ``require_builder`` / ``require_admin``
  gating per route. Encrypted credentials routed through
  ``piilot.sdk.connectors.save_connection`` + ``update_config``
  + ``delete_connection`` (auto-encrypts ``type: secret`` fields).
  ``POST /connections/{id}/test`` fetches ``$metadata`` once for a
  reachability check (no persistence); ``POST /connections/{id}/sync``
  fetches + persists snapshot + re-seeds the plugin-owned KB.
  ``GET /connections/{id}/entities`` / ``…/{name}`` /
  ``…/audit`` for browsing.

- **`piilot_pack_sap/connection_resolver.py` extension** — new
  public method ``resolve_for_connection_id(connection_id,
  company_id)`` that bypasses the session-scope lookup and loads a
  specific connection directly. Used by ``/test`` and ``/sync``
  routes that already carry an explicit id in the URL — the agent
  tool path keeps using the original ``resolve`` (scope-first).

- **`piilot_pack_sap/repository.py` extension** — new CRUD helpers
  ``insert_connection``, ``update_connection`` (allow-list of
  mutable fields), ``delete_connection`` (cascade preserved on
  audit_log via ON DELETE SET NULL), ``set_connection_health``
  (timestamp + status + error).

- **Frontend `SAPConnectorView.tsx`** — refactored from the Phase 0
  banner into a shadcn ``Tabs`` shell with 4 URL-driven panels
  (``?tab=connection|status|browser|audit``). Cross-panel state
  (selected ``connection_id``) lives at the view level and is
  echoed into the URL so a refresh restores the selection.

- **Frontend `components/ConnectionPanel.tsx`** — list of
  connections with Test / Delete actions per row + creation
  dialog. The form gates credentials fields by ``auth_mode``
  (basic vs oauth_client_credentials) and refuses submission
  until every required field is filled.

- **Frontend `components/StatusPanel.tsx`** — card view of the
  selected connection (URL, auth mode, last health, cached entity
  count) with Test + Sync action buttons. Sync result surfaces the
  KB outcome inline.

- **Frontend `components/EntityBrowser.tsx`** — searchable table
  of cached EntitySets with client-side substring filter (renders
  up to 200 rows at a time). Clicking a row opens a dialog that
  fetches ``payload`` (properties + navigations) lazily via
  ``getEntity``.

- **Frontend `components/AuditLogPanel.tsx`** — paginated audit log
  with a status dropdown (all / ok / http_error /
  validator_rejected / auth_error / rate_limited) + manual refresh.

- **Frontend `services/sapClient.ts`** — typed wrapper over the 11
  backend endpoints. Every method delegates to
  ``apiFetch`` from ``@plugin-host/services/httpClient``.

- **Frontend locales** — full rewrite of ``locales/{fr,en}.json``
  (the Phase 0 file was still the hello-world template). 60+ keys
  organized under ``sap.{connection,status,browser,audit,view}.*``.

- **Vitest setup** — ``vitest.config.ts`` aliases ``@plugin-host``
  to a local stub tree under ``__tests__/stubs/plugin-host/``
  (services + lib + UI primitives) so tests resolve imports
  without the real host being present. 19 frontend tests covering
  ``sapClient`` URL construction + the ``index.ts``
  ``register(core)`` smoke test.

- **`.gitignore`** — ignore ``node_modules/`` and
  ``*.tsbuildinfo`` (npm install happens locally / in CI, never
  committed).

### Tests

- 45 new pytest tests (28 routes + 17 repository extensions),
  plus 19 vitest tests on the frontend side. Total: 373 unit
  Python + 19 unit TypeScript + 5 live SAP = **397 tests**.
  Coverage: 95% on the Python package (no regression — every new
  module ≥ 95%).

### Added — Phase 2 (9 agent tools + connection resolver + executor)

- **`piilot_pack_sap/connection_resolver.py`** — async resolver that
  decides which SAP connection an agent call should hit. Lookup order:
  (1) ``piilot.sdk.session.get_scope`` if the user pinned a connection
  for this run, (2) most-recently-updated active row in
  ``integrations_sap.connections``. Loads encrypted credentials from
  the core via ``piilot.sdk.connectors.get_connection`` +
  ``piilot.sdk.crypto.decrypt`` and builds the right
  :class:`~piilot_pack_sap.auth.Auth` (Basic or
  OAuthClientCredentials). Plugin namespace check on the scope (a SAP
  tool cannot inherit another plugin's pinned connection).
- **`piilot_pack_sap/tool_executor.py`** — single pipeline shared by
  every tool: resolve company_id from the session state, resolve the
  connection, build :class:`ODataClient`, run the query, append an
  audit row, return a typed ``ToolResult``. Two surfaces:
  ``execute_odata_call`` for :class:`ODataQuery`-shaped requests and
  ``execute_raw_call`` for paths that don't fit the composer
  (navigation properties, function imports). Maps every exception to
  the audit status taxonomy: ``ok`` / ``session_unknown`` /
  ``resolution_error`` / ``validator_rejected`` / ``auth_error`` /
  ``http_error`` / ``rate_limited`` / ``timeout`` / ``parse_error``.
  Tools never raise — they always return a structured dict so the LLM
  can react gracefully.
- **9 agent tools (`piilot_pack_sap/tools.py`)** — every tool is an
  async function wrapped with ``piilot.sdk.tools.bind_session`` so
  ``session_id`` is stripped from the LLM-facing JSON schema (mandatory
  pattern since SDK 0.6).
  - ``sap_describe_entity(entity_set)`` — reads
    ``integrations_sap.schema_snapshot``, no live OData call.
  - ``sap_search_entity(query, limit)`` — case-insensitive substring
    search over cached EntitySet names + descriptions.
  - ``sap_select(entity_set, filter, select, order_by, top)`` — full
    OData GET with whitelist validation.
  - ``sap_count(entity_set, filter)`` — row count (v2 path-segment
    ``/$count``, v4 inline ``$count=true``).
  - ``sap_top_n(entity_set, n, order_by, filter, select)`` — thin
    wrapper around ``$top`` + ``$orderby``.
  - ``sap_aggregate(entity_set, aggregation, filter)`` — ``$apply=
    aggregate(...)`` with allowed ops ``sum / avg / min / max / count
    / countdistinct``.
  - ``sap_navigate(entity_set, key, navigation_property, top)`` —
    follow a Navigation Property from a single record. Key is
    OData-escaped (single quotes doubled) before path embedding.
  - ``sap_lookup(entity_set, key, select)`` — **admin only**. Single
    record by primary key. Refused for non-admin sessions.
  - ``sap_invoke_function(function_name, params)`` — **admin only**.
    Read-only OData function imports. Rejects unsupported param types
    (lists, dicts) and non-identifier function names.
- **Manifest** (``pyproject.toml``) — 9 ``[[provides.agent_tools]]``
  entries, each ``requires = "connectors.sap.s4hana_cloud"`` so the
  Builder hides the bundle when the connector isn't configured. Admin
  enforcement is documented as a comment but happens at runtime
  inside the tool function (the manifest layer has no role gating
  primitive in SDK 0.7).
- **i18n** — 18 new keys under ``sap.tools.<tool>.{label, description}``
  in both ``fr.json`` and ``en.json``. Zero hardcoded strings in the
  agent tool layer.
- **`piilot_pack_sap/repository.py` extensions** — three new
  functions consumed by the resolver: ``list_connections``,
  ``get_connection_by_id``, ``get_active_connection``.
- **`piilot_pack_sap/odata_client.py` extension** — new
  ``ODataClient.request_raw(path_after_base, params=...)`` for paths
  outside the ``ODataQuery`` shape. Bypasses the validator (caller is
  responsible for path safety — only used by tool functions that have
  already screened identifiers).
- **Tests** — 5 new test files, 118 unit tests added on top of Phase 1.
  Mocking pattern: SDK primitives (``get_session``, ``get_scope``,
  ``get_connection``, ``decrypt``, ``run_in_thread``) are patched per
  fixture; the test never touches a DB or makes a real HTTP call.
  Tools tests verify (a) the right ``ODataQuery`` is built, (b) the
  validator refusal is surfaced as ``status=validator_rejected``, (c)
  admin gates fail closed for non-admin roles, (d) ``session_id`` is
  stripped from every tool's LLM-facing JSON schema.

Coverage globale (Phases 0 + 1 + 2) : 336 unit + 5 live = 341 tests
verts, **95% coverage** sur tout le package.

### Added — Phase 1 Bloc C (persistence + audit + KB seeding)

- **`piilot_pack_sap/repository.py`** — direct SQL access to the three
  `integrations_sap` tables created by `001_init_sap.sql`. Wraps
  `piilot.sdk.db.cursor` (sync — async handlers must call through
  `run_in_thread`). API: `upsert_schema_snapshot` (`execute_values` +
  ON CONFLICT on `(connection_id, service_path, entity_set_name)`),
  `list_schema_snapshot`, `get_snapshot_entry`, `insert_audit_log`
  (returns id), `list_audit_log` (optional status filter).
- **`piilot_pack_sap/snapshot_service.py`** — bridges the
  `introspect.SchemaSnapshot` type with the repo. `persist_schema_snapshot`
  converts each `EntitySet` into a row with a JSONB payload (full
  serialised properties + navigations + SAP annotations) so downstream
  agent tools can `sap_describe_entity` without re-parsing XML.
  Derives a human description from the first `sap:label` annotations.
- **`piilot_pack_sap/audit.py`** — `record_call` primitive used by every
  agent tool (Phase 2) and HTTP route (Phase 3) to append to
  `integrations_sap.audit_log`. Documents the status taxonomy
  (`ok` | `validator_rejected` | `auth_error` | `http_error` |
  `parse_error` | `rate_limited` | `timeout`). Truncates `error`
  payloads to 2 000 chars to keep audit rows small.
- **`piilot_pack_sap/kb_seeder.py`** — auto-creates the plugin-owned
  KB "SAP Metadata — <connection_label>" on the first sync via
  `piilot.sdk.knowledge.create_kb` + `add_column` + `insert_batch`
  (schema_locked, 5 columns: entity_set_name / entity_type /
  description / key_fields / properties_count). Re-sync = diff
  against existing rows via `find_rows`, `update_row` for known
  entity sets, `insert_batch` for new ones. The `description` column
  is text-rich (sap:label + first 15 properties + key) for the host's
  auto-embedder so the RAG agent (`sap_search_entity`, Phase 2) gets
  semantic signal out of the box.
- **`tests/test_repository.py`** + **`test_snapshot_service.py`** +
  **`test_audit.py`** + **`test_kb_seeder.py`** — 35 unit tests
  covering 100% of `repository`, `audit`, `kb_seeder` and 96% of
  `snapshot_service`. SDK primitives (`cursor`, `Json`, `find_kb`,
  `create_kb`, `add_column`, `find_rows`, `insert_batch`,
  `update_row`) are mocked; `piilot.sdk.testing.mock_db_conn`
  neutralises `execute_values` for the upsert path.

Coverage globale Phase 1 (Blocs A + B + C) : 259 unit + 5 live = 264 tests
verts, **96% coverage** sur tout le package.

### Decided

- **No `register_kb_template`.** The v0.7 SDK primitive declares a
  blueprint exposed in the user-facing template catalogue. Our plugin
  auto-creates a single KB per connection from `kb_seeder` directly —
  the user never picks "SAP Metadata" from the catalogue, so the
  template would just be visual noise.

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
