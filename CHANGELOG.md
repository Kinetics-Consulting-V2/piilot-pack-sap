# Changelog — piilot-pack-hello

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

### Fixed — `init-plugin.sh` residual hunt

Source: retro post-`piilot-pack-compta-esms` (06/05/2026) — 9 residuals
documented in `AICockpit/docs/sdk/PLUGIN_DEV_WORKFLOW.md` §2.5.

- **`.ts` / `.tsx` files now scanned** by `init-plugin.sh` — without
  this, `t('hello.module.X')` and `core.registerI18nBundle('hello', ...)`
  in the frontend scaffold survived init and the runtime i18n namespace
  silently mismatched the backend's.
- **TOML entry-point key** `hello = "piilot_pack_hello:Plugin"` →
  `<ns> = "piilot_pack_<ns>:Plugin"` (only the value side was rewritten
  before).
- **TOML permissions wildcard** `["hello.*"]` → `["<ns>.*"]` (the
  identifier-scoped regex didn't match the `*`).
- **Single-quoted TS strings** `'hello'` (used by `registerI18nBundle`
  and the host alias resolver) → `'<ns>'`.
- **Migration filenames** `002_hello_<...>.sql` → `002_<ns>_<...>.sql`
  (only the SQL contents were rewritten before).
- **Reset version to 0.1.0** in `pyproject.toml` AND
  `frontend/package.json` after init (the template tracks SDK versions,
  but the user's first tag should be `v0.1.0`).
- **Replace TODO authors** with the Kinetics Consulting V2 default
  (third-party forks override post-init).
- **Extra targeted seds** for migration header comments
  (`-- Plugin: hello`) and URL path docstrings (`/plugins/hello/<word>`).

### Refactored — `frontend/src/index.ts` namespace constant

The locale JSON unwrap previously hardcoded `(fr as ...).hello`, which
broke after init (the JSON's top-level key is the user's namespace, not
`hello`). The template now declares a single `const NS = 'hello'`
referenced from every call site (`registerModuleView`,
`registerI18nBundle`, JSON unwrap) — `init-plugin.sh` rewrites the
literal once, all references stay in sync.

### Added — `scripts/post-init-check.sh`

Auto-invoked at the end of `init-plugin.sh`. Audits the working tree
for known residuals (raw `hello` in code/config files, leftover migration
filenames, version drift, TODO authors). Excludes itself + markdown
prose. Re-runnable any time. Exit 1 on residuals.

### Added — printed warnings for residuals init-plugin.sh CAN'T fix

- The manifest module's `id = "<ns>.hello"` (the module id within the
  namespace stays `hello` — user renames to a meaningful id).
- `tests/test_v02_examples.py` imports every submodule (cut some?
  delete the test).

## [0.4.0] — 2026-04-30

### Changed

- **SDK bump 0.4.x → 0.6.0** — pin `piilot-sdk>=0.6.0,<1.0.0` and
  `sdk_compat = ">=0.6.0,<1.0.0"`. CI matrix now tests `0.6.0`.
- **`tools.py` showcases `bind_session`** — the `hello_greet` tool
  is now wrapped with `bind_session(_hello_greet_fn)` before being
  passed to `StructuredTool.from_function`. Required since SDK 0.6
  because the host's PLT-35 prompt-cache stabilisation removed the
  `--- SESSION ---` block from agent system prompts. Without
  `bind_session`, the LLM never receives the session id and every
  tool call falls through to the "Session not found" branch.

### Added

- Inline doc on `tools.py` explaining when and why to use
  `bind_session`. Direct `_fn` calls in unit tests still work
  (the wrapper preserves the underlying function).
- **`frontend/` scaffold** (carried over from the previously
  unreleased section) — source-only npm package showcase
  (`piilot-pack-hello-ui`). Ships alongside the PyPI backend under
  the same repo. Includes :
  - `package.json` with publishable config (`main`/`exports`/`files`
    point at `src/index.ts` — no build step).
  - `tsconfig.json` with the `@plugin-host/*` alias declared for
    TS-aware editor support.
  - `src/index.ts` entry wiring `registerModuleView` +
    `registerI18nBundle`.
  - `src/HelloModuleView.tsx` sample component with URL-backed
    sub-routing (`useSearchParams`) — the canonical pattern.
  - `src/locales/{fr,en}.json` sample bundles.
  - `__tests__/index.test.ts` smoke test on `register(core)`.
  - `README.md` — quick reference.
  - `.github/workflows/release-ui.yml` — tag `ui-v*` → npm publish
    with the Classic Automation token pattern.
- **README.md** — gained a "Dual distribution" subsection naming the
  PyPI + npm pair, plus 3 new rows in the showcase table for the
  frontend files.

---

## [0.3.0] — 2026-04-24

### Changed

- **`sdk_compat`** tightened from `>=0.2.0,<1.0.0` to
  `>=0.3.0,<1.0.0`. Forks that only need the v0.2 showcase can pin
  the previous template tag — no migration forced.
- **`dependencies`** — `piilot-sdk` range bumped to `>=0.3.0,<1.0.0`.
- **`pyproject.toml`** — version bumped `0.2.0` → `0.3.0`, description
  updated to "Piilot SDK v0.3 scaffold starter".

### Added

- **`tests/conftest.py`** — autouse session fixture `_stub_sdk_http`
  calling the new `piilot.sdk.testing.stub_http_primitives()` helper.
  Plugin tests that exercise routes (slowapi `key_func`) no longer
  need their own `get_real_ip` stub — ships with the SDK.

### Upgrade notes

Forks on `0.2.x` can upgrade at their own pace. The breaking change
in SDK v0.3 that impacts plugin code is
`piilot.sdk.crypto.decrypt()` now returning `str` (was `bytes`); if
your plugin doesn't call `decrypt` directly, the bump is
drop-in. If it does, replace
`decrypt(token).decode("utf-8")` with `decrypt(token)`. See the
[SDK v0.3.0 changelog][sdk-v0.3-changelog] for the full list of new
primitives (`connectors.set_active`, `connectors.update_config`,
`modules.get_by_slug`, `utils.run_async`, `testing.*`,
`on_duplicate` on registries).

[sdk-v0.3-changelog]: https://github.com/Kinetics-Consulting-V2/AICockpit/blob/main/docs/sdk/SDK_CHANGELOG.md#030--2026-04-24--pennylane-dogfood-follow-up

---

## [0.2.0] — 2026-04-21

### Added

Full showcase of the Piilot SDK v0.2 primitives. The `hello` plugin
now wires every major extension point so a fork starts from a
minimally functional example of each.

- **`repo.py`** — `piilot.sdk.db.cursor` + `run_in_thread` + `Json`.
  Example repository that tracks per-company greet counts.
- **Migration `002_hello_counter.sql`** — backing table for the repo
  with RLS policies.
- **`routes.py`** — `piilot.sdk.http.register_router` + two routes
  (`GET /counter`, `POST /greet`) using `Depends(require_user)` and
  `get_real_ip`.
- **`tools.py`** — `piilot.sdk.tools.register_tool` with
  `system_prompt_builder`, plus `piilot.sdk.session.get` for reading
  the active conversation state. LLM agents can now call
  `hello_greet(name)`.
- **`seeds.py`** — `piilot.sdk.modules.register_module` and
  `piilot.sdk.templates.register_template`. Both idempotent
  (`ON CONFLICT DO UPDATE`), safe to re-run on every boot.
- **`connector.py`** — commented-out pattern for
  `piilot.sdk.connectors.register_connector`. Uncomment and adapt
  when you have a real external API.
- **`jobs.py`** — commented-out pattern for
  `piilot.sdk.scheduler.register_sync_handler`. Enable once your
  connector is live.
- **`tests/test_v02_examples.py`** — 6 smoke tests covering the new
  examples (module import, `Plugin.register()` e2e, namespace
  attribution, prompt builder).
- **`tests/conftest.py`** — new `plugin_context` fixture that sets
  `current_plugin` contextvar around the test, required by the v0.2
  primitives.

### Changed

- **Version bumped** from `0.1.0` to `0.2.0`.
- **`sdk_compat`** tightened from `>=0.1.0,<1.0.0` to
  `>=0.2.0,<1.0.0` — the new wirings need v0.2.
- **`dependencies`** added `fastapi>=0.115` + `langchain-core>=0.3`
  (consumed by `routes.py` + `tools.py`).
- **`pyproject.toml` manifest** — new `provides.agent_tools` block,
  commented templates for `provides.connectors` and
  `provides.scheduled_jobs`.
- **`tests/conftest.py`** — autouse fixture resets the SDK registries
  between tests to avoid cross-test pollution.

### Upgrade notes

If you forked this template at `0.1.x`, upgrading to the v0.2
showcase is optional — your `0.1.x` plugin keeps working against the
v0.2 SDK (backwards compatible). Adopt the new primitives à la carte
by copying the example files you need.

---

## [0.1.0] — YYYY-MM-DD

### Added

- Initial scaffold from `piilot-plugin-template`.
- Example module `hello.hello` — replace with the
  real pipeline.
- Dedicated PG schema `hello` with example table
  (migration `001_init.sql`).
- French and English locales.
