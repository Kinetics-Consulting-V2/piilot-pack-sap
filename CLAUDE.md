# CLAUDE.md — piilot-pack-sap

> Context file for Claude Code when working inside this plugin repo.
> The root-level CLAUDE.md of the Piilot **core** (`AICockpit`) covers
> the wider engineering factory; this file zooms in on plugin-specific
> conventions and the minimum Claude needs to not go off-rails.

---

## What this repo is

A **Piilot plugin** (`piilot-pack-sap`, namespace `sap`) — SAP
S/4HANA Cloud OData connector. Read-only agent access to FI / CO /
MM / SD entities for financial and operational analytics. Pattern :
1 plugin, 1 module Piilot `sap.connector`, 9 agent tools (Phase 2),
1 KB plugin-owned "SAP metadata" (Phase 1).

Plugins extend the Piilot core without modifying it. They ship in
**two halves** from a single repo :

- **Backend** (`piilot_pack_sap/`, published as `piilot-pack-sap`
  on PyPI) — imports from `piilot.sdk.*` only, never from `backend.*`.
  Data lives in a dedicated PG schema named after the plugin.
- **Frontend** (`frontend/`, published as `piilot-pack-sap-ui` on
  npm) — source-only package. Imports back into the host via
  `@plugin-host/*` alias. Contributes exactly 2 things : a module
  view and i18n bundles.

---

## Non-negotiable rules

1. **Import rule (backend)** — only `piilot.sdk.*` is allowed. The
   core loader runs a static AST check that refuses any `from
   backend.*` or `import backend`. If you're tempted to reach into
   the core internals, stop, open an issue upstream against
   `AICockpit`.
2. **Import rule (frontend)** — only `@plugin-host/*` is allowed
   when reaching into the host (UI components, services, i18n).
   Never do `../../../frontend/src/...` — the alias is stable across
   the planned Module Federation migration; deep paths break.
3. **Namespace** — every identifier this plugin exposes (handler ids,
   tool ids, i18n keys, PG schema, env vars, HTTP routes, React
   component file names) is prefixed by `sap`.
4. **Migrations are idempotent** — every `CREATE TABLE` / `CREATE INDEX`
   / `CREATE SCHEMA` uses `IF NOT EXISTS`. Every `ADD COLUMN` uses
   `ADD COLUMN IF NOT EXISTS`. The loader refuses the plugin otherwise.
5. **Routes** — if this plugin exposes HTTP routes, they live under
   `/plugins/sap/` (no exception, webhooks included).
6. **Secrets** — fields marked `type: secret` in the manifest's
   `credentials_schema` are encrypted at the DB boundary. Never log
   them, never store raw secrets in `config` JSON.
7. **Frontend is source-only** — the npm package's `main`/`exports`
   point at `./src/index.ts`. Never add a build step that emits a
   `dist/` unless you also flip those fields — the consumer's Vite
   relies on raw source transformation to keep React instances
   deduped.

---

## Git workflow — same verrous humains as the core

Three human-only decisions apply in this repo, identical to the core:

| Step | Who decides |
|---|---|
| Validate the implementation plan | The dev |
| Ask to open the PR | The dev |
| Approve and ask to merge | The dev |

Claude Code is allowed to COMMENT / REQUEST_CHANGES on PRs. **Claude
never does APPROVE** — the dev alone approves.

No direct pushes on `main`. All work happens on `feature/xxx`,
`fix/xxx`, `refactor/xxx` or `docs/xxx` branches and merges via PR.

---

## Typical loop when developing a feature

1. **Plan** — Claude proposes the change, the dev validates.
2. **Code** — inside a `feature/xxx` branch. Keep commits small and
   logical.
3. **Test** — `pytest` must stay green. New code gets new tests.
4. **Signal the dev** — "feature ready, summary: …".
5. Dev verifies locally against a running Piilot core (bind-mount).
6. Dev says "open the PR" — Claude creates it (COMMENT style).
7. Dev approves + says "merge" — Claude squash-merges.

---

## Tests

Three suites :

- **Backend unit** (`tests/`) — isolated, no backend. Use the
  `fake_ctx` fixture from `tests/conftest.py`. Fast, always run.
  `pytest` must stay green.
- **Backend integration** (optional, `tests/integration/`) — run
  against a real Piilot backend bound via docker-compose. Slower,
  separate pytest marker.
- **Frontend** (`frontend/__tests__/`) — Vitest. Unit tests on
  `register(core)` plus mount tests on the module view with
  `@testing-library/react`. Runs with `cd frontend && npm test`.

Target coverage : ≥ 80% on both halves.

---

## Stack

**Backend**

- Python 3.12+
- `piilot-sdk` (pinned range in `pyproject.toml`, currently
  `>=0.7.0,<1.0.0`)
- PostgreSQL — plugin-owned schema `integrations_sap`
- Optional : LangChain `StructuredTool` for agent tools
- Ruff + Black (CI enforces) · Pytest + pytest-cov

**Frontend**

- TypeScript 5 strict, React 19 (peer dep)
- Consumer's Vite transforms `.tsx` — no plugin-side build step
- `@plugin-host/*` alias (declared in `frontend/tsconfig.json`) for
  imports back into the host (shadcn/ui, services, i18n)
- Vitest for unit tests · Bundled peerDeps only (no React in the
  published tarball — deduped via host's `resolve.dedupe`)

---

## When the plugin hits a missing SDK primitive

The answer is **always the same**: open an issue upstream against
`Kinetics-Consulting-V2/AICockpit`, propose the primitive in
`piilot.sdk.*`, land the PR, bump `sdk_compat` here, then use it.

Do **not** route around the AST check via `importlib` or `exec`. It
passes the check but breaks at the next core refactor.

See the internal workflow doc in the core repo:
[`docs/docs_dev/PLUGIN_DEV_WORKFLOW.md`](https://github.com/Kinetics-Consulting-V2/AICockpit/blob/main/docs/docs_dev/PLUGIN_DEV_WORKFLOW.md).

---

## Dual distribution

A plugin release is **two packages from the same repo** :

| Package | Registry | Tag | Workflow |
|---|---|---|---|
| `piilot-pack-sap` (backend) | PyPI | `v<version>` | `.github/workflows/release.yml` |
| `piilot-pack-sap-ui` (frontend) | npm | `ui-v<version>` | `.github/workflows/release-ui.yml` |

Independent cadences : a backend hot-fix can ship without touching
the frontend version, and vice-versa. Keep the two versions aligned
on major/minor bumps so users don't get surprised by skew.

---

## What Claude should never do here

- Push to `main` directly
- Approve a PR
- Open a PR without explicit dev request
- Add dependencies on `backend.*` or any non-SDK internal (Python
  side) or `../../../frontend/src/*` (TypeScript side)
- Drop the RLS policies added by the init migration
- Change `namespace` in `pyproject.toml` after the first release
  (it's the stable identifier)
- Hardcode secrets anywhere
- Add a build step to the plugin frontend without flipping
  `main`/`exports` at the same time (breaks consumer's Vite resolution)

---

## Reference

- [Piilot plugin development guide (public)][dev-guide] — the
  contractual reference for editors.
- [SDK changelog][sdk-changelog] — what's new / deprecated on every
  SDK release. Watch this before bumping `sdk_compat`.
- [Theme tokens][theme-tokens] — for branding-related plugins.

[dev-guide]: https://github.com/Kinetics-Consulting-V2/AICockpit/blob/main/docs/sdk/PLUGIN_DEVELOPMENT.md
[sdk-changelog]: https://github.com/Kinetics-Consulting-V2/AICockpit/blob/main/docs/sdk/SDK_CHANGELOG.md
[theme-tokens]: https://github.com/Kinetics-Consulting-V2/AICockpit/blob/main/docs/sdk/THEME_TOKENS.md
