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

🟡 **v0.1.0 — Phase 0 scaffolding** (unreleased)

This release ships the plugin skeleton :

* Manifest declared (namespace, module, connector, permissions).
* Migration `001_init_sap.sql` (3 tables : connections, schema_snapshot,
  audit_log) with RLS.
* `Plugin.register()` wires migrations, i18n, module handler,
  connector spec, routes (no-op tools, no-op seeds for KB / agent
  templates).
* Frontend `SAPConnectorView` with phase banner.

**No OData traffic yet.** Phases 1 → 5 add the real functionality —
introspect `$metadata`, parser/validator, 9 agent tools, 4-tab UX,
hardening, beta dogfood.

See `AICockpit/docs/docs_dev/suivi.md` (internal) for the phase-by-phase
checklist.

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
See `docs/SAP_ROLE_SETUP.md` (Phase 4 deliverable) for the SAP
transaction snippets.

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
