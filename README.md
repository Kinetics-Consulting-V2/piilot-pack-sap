# piilot-pack-sap

> SAP S/4HANA Cloud OData connector for Piilot — read-only agent access to FI / CO / MM / SD entities for financial and operational analytics.

[![PyPI](https://img.shields.io/pypi/v/piilot-pack-sap)](https://pypi.org/project/piilot-pack-sap/)
[![npm](https://img.shields.io/npm/v/piilot-pack-sap-ui)](https://www.npmjs.com/package/piilot-pack-sap-ui)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

---

## What it does

Connect your **Piilot agents** to a **SAP S/4HANA Cloud** instance via the
standard **OData v4** API. Read-only access to financial entities
(`A_JournalEntry`, `A_GLAccountLineItem`, `A_BusinessPartner`, …),
controlling entities (`A_CostCenter`, `A_ProfitCenter`, …) and
operational entities across MM / SD modules.

The plugin contributes :

* **1 module Piilot** `sap.connector` — connection config (auth +
  endpoint), status panel, OData entity browser, audit log.
* **1 connector** `sap.s4hana_cloud` — Basic auth or OAuth 2.0
  `client_credentials` against your SAP S/4HANA Cloud instance.
  Credentials encrypted at the DB boundary by the Piilot core
  (Fernet).
* **9 agent tools** (Phase 2 deliverable) — `sap_search_entity`,
  `sap_describe_entity`, `sap_select`, `sap_count`, `sap_aggregate`,
  `sap_top_n`, `sap_navigate`, `sap_lookup`, `sap_invoke_function`.
  All read-only. Strict whitelist OData validator (no `$expand`, no
  `$batch`, no function imports en écriture, no mutations).
* **1 KB plugin-owned** "SAP metadata" (Phase 1 deliverable) — embedded
  introspection of your SAP `$metadata` for RAG-driven entity discovery.

**Pattern** : 1 plugin, 1 module Piilot. Aligned with
`piilot-pack-pennylane` (treasury dashboard) and `piilot-pack-supabase`
(connector + tools). See `AICockpit/docs/sdk/PLUGIN_DEVELOPMENT.md`
§20 for the SDK frontend contract.

---

## Scope v1

| Variant | OData v4 | v1 support |
|---|---|---|
| **SAP S/4HANA Cloud** | ✅ Full standard | ✅ **Cible v1** |
| **SAP S/4HANA on-premise** | ✅ via Cloud Connector / API Mgmt | 🟡 v2+ |
| **SAP ECC (R/3 legacy)** | 🟡 OData v2 partiel + BAPIs RFC | ❌ v2+ (probably another plugin) |

Auth modes shipped in v1 :

* `basic` — username + password, sandbox-friendly + smaller installs.
* `oauth_client_credentials` — standard SAP S/4HANA Cloud productive
  Communication User. Token URL + Client ID/Secret + scope.

X.509 cert auth is deferred to v1.1.

---

## Status

🟢 **v0.1.0 — Phases 0 + 1 + 2 + 3 + 4 ready** (pending tag)

What ships:

* **3 tables** plugin-owned schema `integrations_sap`: `connections`,
  `schema_snapshot`, `audit_log`. RLS enforced.
* **Live OData v2 / v4 client** with auto-version detection,
  retries on 429+5xx (`Retry-After`-aware), three auth strategies
  (`ApiKey`, `Basic`, `OAuth client_credentials`).
* **Strict whitelist validator** — fails closed on `$expand`,
  `$batch`, function calls, lambda operators, navigation paths,
  mutations. Fuzzed against 14 attack payloads.
* **11 HTTP endpoints** under `/plugins/sap/*` (CRUD + test +
  sync + entities + audit), gated by `require_user` /
  `require_builder` / `require_admin`, rate-limited per company.
* **9 agent tools** (cf. table below) wrapped with `bind_session`,
  audited on every call, capped by a per-session cost guard
  (default 30 calls).
* **Frontend `SAPConnectorView`** with 4 shadcn `Tabs`:
  Connection / Status / Browser / Audit. URL-driven sub-routing.
* **Plugin-owned KB** "SAP Metadata — &lt;connection&gt;"
  auto-seeded on first sync, refreshed idempotently on every
  re-sync.

Test coverage: **~400 unit tests** (Python + TypeScript) + **5 live
sandbox** tests at 95% Python coverage.

See `AICockpit/docs/docs_dev/suivi.md` (internal) for the phase-by-phase
journal.

---

## Install

### Self-hosted Piilot

```bash
pip install piilot-pack-sap
docker compose restart backend
```

### Piilot Cloud (SaaS)

Pinned in core's `backend/api/requirements.txt`:

```
piilot-pack-sap==0.1.0
```

Frontend pinned in core's `frontend/package.json`:

```json
"piilot-pack-sap-ui": "^0.1.0"
```

Then the core's `vite.config.ts` resolves `@plugin/sap` via its 3-tier
alias (dev bind-mount → npm tier → noop shim). See
`AICockpit/docs/sdk/PLUGIN_DEV_WORKFLOW.md` §5.

Enable for a given company via the activation API :

```bash
curl -X PUT \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://api.piilot.ai/admin/plugins/sap/activations/$COMPANY_ID
```

---

## Configuration

A Piilot admin connects an SAP S/4HANA Cloud instance from the
plugin's module view (`/modules/<sap-connector-uuid>` once the plugin
is activated).

Required fields :

| Field | Description |
|---|---|
| **Auth mode** | `basic` or `oauth_client_credentials` |
| **Base URL** | Your S/4HANA Cloud tenant URL (e.g. `https://my123456.s4hana.cloud.sap`) |
| **Basic — username / password** | If `auth_mode = basic`. Communication User created in SAP. |
| **OAuth — token URL / client ID / client secret / scope** | If `auth_mode = oauth_client_credentials`. Configure a productive Communication Arrangement in SAP. |

Credentials are encrypted at rest (Fernet) by the core's
`plugin_connections` table. The plugin never stores raw secrets in
its own `integrations_sap.connections` row.

**Required SAP role** : the Communication User (Basic) or the
Communication Arrangement (OAuth) MUST have a **PFCG role restricted
to read-only access** on the EntitySets you want Piilot to consume.
See the *SAP-side setup* section below.

---

## SAP-side setup

### Option A — Basic auth Communication User

Quick way to onboard, suitable for trial instances or sandboxed
environments. NOT recommended for productive S/4HANA Cloud tenants
(use OAuth client_credentials instead).

1. **SAP S/4HANA Cloud** — log in with an admin user.
2. Open the **Maintain Communication Users** app
   (transaction code `SU05` on-premise; Communication Management
   tile on Cloud).
3. Create a **technical user** named e.g. `PIILOT_AGENT`. Generate a
   strong password (≥ 24 chars).
4. Go to **Communication Systems** and create a system pointing at
   Piilot's outbound IP range (your tenant's egress).
5. Go to **Communication Arrangements** and assign every OData service
   you want to expose (e.g. `SAP_COM_0507` for Business Partner,
   `SAP_COM_0019` for General Ledger).
6. Pick the technical user `PIILOT_AGENT` in the Arrangement's
   **Inbound Communication** section.
7. Note the **service URL** (base URL) printed at the bottom of each
   Arrangement page. Format:
   `https://<tenant>-api.s4hana.cloud.sap/sap/opu/odata/sap/<SERVICE>`.
8. In the Piilot UI, **Connection** tab → **+ New connection** →
   choose `auth_mode = basic`, paste the URL + username + password.

### Option B — OAuth 2.0 client_credentials (recommended)

Standard for productive S/4HANA Cloud. Token rotation handled by SAP
BTP; no shared passwords on the wire.

1. **SAP BTP Cockpit** → open the **XSUAA** service for the subaccount
   that hosts the S/4HANA Cloud subscription.
2. Create a new **service instance** with plan `application`. The
   `xs-security.json` should expose a `read` scope per OData service.
3. Create a **service key** on the instance. The key contains :
   - `clientid` → Piilot's "Client ID"
   - `clientsecret` → Piilot's "Client Secret"
   - `url` → token endpoint; append `/oauth/token` → Piilot's
     "Token URL"
4. Bind the BTP scope to a **Communication Arrangement** in S/4HANA
   Cloud (same arrangement as Option A, but check "OAuth 2.0
   Client Credentials Grant" instead of "Basic").
5. In the Piilot UI, **Connection** tab → **+ New connection** →
   choose `auth_mode = oauth_client_credentials`, paste the four
   fields (`token_url`, `client_id`, `client_secret`, optional
   `scope`).

### Verify connectivity

After saving the connection, open the **Status** tab and click
**Test connection**. The route fetches `$metadata` once and returns
either `ok` + entity_set_count, or a structured error. If it works,
click **Re-sync $metadata** to populate the local snapshot cache and
seed the plugin-owned KB.

---

## Agent tools — the 9 OData verbs

Every tool is exposed to Piilot agents as `sap_<name>` (LangChain
`StructuredTool`). `session_id` is injected by the runtime
(`bind_session`) so the LLM never picks the connection.

| Tool | Purpose | Sample agent prompt |
|---|---|---|
| `sap_search_entity` | substring search the cached EntitySet catalogue | "Trouve l'entité SAP qui contient les factures clients." |
| `sap_describe_entity` | return cached `$metadata` for one EntitySet | "Quelles colonnes a `A_BusinessPartner` ?" |
| `sap_select` | filtered + projected GET | "Liste les 10 premiers BP créés en 2026." |
| `sap_count` | row count | "Combien de BP catégorie '2' ?" |
| `sap_top_n` | wrapper $top + $orderby | "Top 5 commandes par montant décroissant." |
| `sap_aggregate` | `$apply=aggregate(...)` | "Somme des montants par mois." |
| `sap_navigate` | follow a Navigation Property | "Adresses du BP '11'." |
| `sap_lookup` | **admin only**: single record by primary key including technical fields | "Fetch the raw `A_GLAccount` row '400000'." |
| `sap_invoke_function` | **admin only**: invoke a read-only OData function import | "Run `ComputeBalance(CompanyCode='1000', Year=2026)`." |

All tools return a structured dict the LLM can parse directly:

```json
{
    "status": "ok",
    "data": { ... },
    "connection_label": "Sandbox",
    "audit_id": "uuid"
}
```

Possible `status` values: `ok` / `validator_rejected` /
`auth_error` / `http_error` / `rate_limited` / `timeout` /
`parse_error` / `resolution_error` / `session_unknown` /
`forbidden` / `cost_limit_exceeded` / `not_found`.

### Cost guard

Every call increments a per-session counter. The default cap is
**30 tool calls per session** (configurable via the
`SAP_TOOL_BUDGET_PER_SESSION` env var). Beyond the cap, the tool
returns `status="cost_limit_exceeded"` without hitting SAP. Sessions
are short-lived (≤30 min by host policy), so the counter resets
naturally.

### Rate limit

HTTP routes enforce per-company sliding-window limits:

* GET endpoints — 60/min
* POST / PATCH / DELETE — 10/min
* POST `/test` and `/sync` — 5/min

`429` responses carry a `Retry-After` header.

---

## Troubleshooting

### `HTTP 403 — UCON blocked`

SAP gateway's [UCON](https://help.sap.com/docs/SAP_NETWEAVER_731_BW_ABAP/280f016edb8049e998237fcbd80558e7/26257b7e9c194f7da4a8e2c80e8c4e0a.html)
filter rejected the request. Common causes:

* The Communication Arrangement does not expose the EntitySet you
  hit (check the service whitelist on the Arrangement screen).
* You're hitting an OData v4 endpoint on a tenant that only exposes
  v2 catalog entries.
* The technical user doesn't have the right PFCG role.

Fix: re-open the Communication Arrangement, add the service or the
role, save, then click **Test connection** again.

### `HTTP 401 — Unauthorized`

* **Basic** : the password rotated. Update via PATCH
  `/plugins/sap/connections/{id}` with `credentials.basic_password`.
* **OAuth** : the BTP service key was deleted or rotated. Re-create
  it on BTP, then PATCH the four oauth fields.

### `HTTP 406 — Not Acceptable` on `$metadata`

You're not hitting this — the plugin sends `Accept: application/xml`
on `$metadata` automatically. If you ever see it through a custom
client, switch the Accept header.

### `parse_error` after `Test connection`

The `$metadata` response wasn't valid XML. Either the endpoint
returned an HTML error page (login redirect, WAF block) or the
service is misconfigured. Check the underlying response with curl:

```bash
curl -u user:pass -v https://<tenant>/sap/opu/odata/sap/API_BP/\$metadata
```

### `validator_rejected` on every agent call

The agent is calling `sap_select` with a `$filter` that uses a
function call (e.g. `contains(Name, 'Foo')`). The v1 plugin refuses
function calls on purpose — guide the agent towards equality /
range comparisons (`Name eq 'Foo'`, `CreationDate ge datetime'...'`).

### `cost_limit_exceeded` on every call after a while

The session counter is exhausted. Either the agent is in a loop
(check the audit log for the same query repeated), or your budget
is too low. Bump `SAP_TOOL_BUDGET_PER_SESSION` to e.g. 100 if your
workflow legitimately needs many calls.

### `403 X-Company-Id` on routes

The Piilot host's `plugin_gate` middleware refused the request.
Check that:

* The Authorization header is valid.
* The `X-Company-Id` header matches a company the user belongs to.
* The plugin is **activated** for that company
  (`companies_plugins.enabled = true` for `provider='sap.s4hana_cloud'`).

---

## Development

### Local setup

```bash
# Clone next to the Piilot core
cd /opt/factory/projects/AICockpit/workspaces/<workspace>/plugins-dev
git clone https://github.com/Kinetics-Consulting-V2/piilot-pack-sap.git
cd piilot-pack-sap

# Install in editable mode with dev extras
pip install -e .[dev]

# Frontend (peer deps only, no install needed for source-only npm)
cd frontend && npm install --no-package-lock  # for vitest local
```

Bind-mount the plugin into the core's `compose.dev.yml` (gitignored
by AICockpit) :

```yaml
services:
  backend:
    volumes:
      - ../plugins-dev/piilot-pack-sap:/app/plugins/piilot-pack-sap
```

Restart the backend and watch for :

```
[plugins] Loaded: sap v0.1.0 (handlers=1, tools=0, modules=1, connectors=1)
```

### Run the tests

```bash
# Backend
pytest

# Frontend
cd frontend && npm test
```

---

## Versioning

This plugin follows [Semantic Versioning](https://semver.org/). The
`sdk_compat` range in `pyproject.toml` pins the Piilot SDK versions
we build against. v0.1.0 pins `piilot-sdk>=0.7.0,<1.0.0`. Watch the
core's [SDK changelog][changelog] for breaking changes.

[changelog]: https://github.com/Kinetics-Consulting-V2/AICockpit/blob/main/docs/sdk/SDK_CHANGELOG.md

## Dual distribution

* **Backend** — `piilot-pack-sap` on PyPI, tagged `v<version>`.
* **Frontend** — `piilot-pack-sap-ui` on npm, tagged `ui-v<version>`.

Both ship from this single repo; the two release workflows publish
independently via OIDC Trusted Publisher (PyPI) and Classic Automation
token (npm).

## License

Apache-2.0. See [`LICENSE`](LICENSE).
