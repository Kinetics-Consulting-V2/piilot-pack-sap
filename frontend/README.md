# piilot-pack-hello-ui

Frontend contributions for the `hello` Piilot plugin. Ships alongside
the backend package `piilot-pack-hello` on PyPI — the two share a
namespace and a per-company activation flag.

## What's in here

- `src/index.ts` — plugin entry point. Exports `register(core)` called
  by the host at boot.
- `src/HelloModuleView.tsx` — React component rendered when the user
  opens `/modules/:slug` matching `hello.hello`.
- `src/locales/{fr,en}.json` — translation keys merged under the
  `hello` namespace by the host's i18next.
- `__tests__/` — Vitest isolated tests.

## Pattern

Source-only package : `main`/`exports` point at `./src/index.ts`.
The consumer (the Piilot host) transforms and bundles via Vite. No
`dist/` to build or ship.

## Host import contract

The plugin imports back into the host via the `@plugin-host/*`
alias — see `tsconfig.json` paths. Never reach around with
`../../../frontend/src/...` : the alias is stable across the planned
Module Federation migration; deep paths are not.

## Publish

Bump `package.json` version, commit, tag `ui-v<version>` in the
plugin repo :

```bash
git tag ui-v0.3.0
git push origin ui-v0.3.0
```

The `.github/workflows/release-ui.yml` workflow publishes to npm.
See the root `CLAUDE.md` for token setup.

## Full contract

For the complete guide (Vite 3-tier resolution, host-side consumption,
module federation roadmap) see :
[`docs/sdk/PLUGIN_DEVELOPMENT.md`](https://github.com/Kinetics-Consulting-V2/AICockpit/blob/main/docs/sdk/PLUGIN_DEVELOPMENT.md)
§20 — "Frontend contributions".
