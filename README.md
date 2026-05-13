# piilot-pack-hello

> Hello world plugin — Piilot SDK scaffold starter.

<!-- scaffold-banner:start -->
> 🧩 **This repo is both a template and a working "hello" plugin.**
>
> **Just want to demo / dogfood?** Install it as-is, it loads as plugin
> `hello` with one module and one migration — no edits required.
>
> **Want to start your own plugin?** Fork via `gh repo create --template`,
> then rename everything to your namespace in one go:
>
> ```bash
> ./init-plugin.sh <namespace> "<description>" <category>
> ```
>
> See the [Piilot plugin development guide][guide] for the full workflow.
>
> [guide]: https://github.com/Kinetics-Consulting-V2/AICockpit/blob/main/docs/PLUGIN_DEVELOPMENT.md
<!-- scaffold-banner:end -->

---

## What it does

TODO: one-paragraph summary of this plugin's purpose and the problem
it solves for a Piilot company.

## What this template demonstrates (SDK v0.3)

The `hello` plugin is a functional showcase of the Piilot SDK v0.2+
primitives, pinned to `piilot-sdk>=0.3.0`. Fork the template and
start from a plugin that already wires:

| File | SDK primitive | What it illustrates |
|---|---|---|
| `piilot_pack_hello/handlers.py` | `ctx.handlers.register` | Module handlers dispatched by the module runtime |
| `piilot_pack_hello/migrations/` + `__init__.py` | `ctx.migrations.register_schema` | Idempotent per-plugin SQL schema + RLS policies |
| `piilot_pack_hello/locales/` + `__init__.py` | `ctx.i18n.register_locales` | Per-namespace locale catalogs merged into `/i18n/catalog` |
| `piilot_pack_hello/repo.py` + `migrations/002_*.sql` | `piilot.sdk.db` | `cursor()`, `run_in_thread`, `Json` — direct SQL with RLS propagation |
| `piilot_pack_hello/routes.py` | `piilot.sdk.http` | `register_router` + `Depends(require_user)` + `get_real_ip` |
| `piilot_pack_hello/tools.py` | `piilot.sdk.tools` + `piilot.sdk.session` | Agent `StructuredTool` with `system_prompt_builder` + session read |
| `piilot_pack_hello/seeds.py` | `piilot.sdk.modules` + `piilot.sdk.templates` | Idempotent `register_module` + `register_template` upserts |
| `piilot_pack_hello/connector.py` | `piilot.sdk.connectors` | **Commented out** — pattern for declaring an external API connector |
| `piilot_pack_hello/jobs.py` | `piilot.sdk.scheduler` | **Commented out** — pattern for a periodic sync handler |
| `frontend/src/index.ts` | `core.registerModuleView` + `registerI18nBundle` | Plugin UI entry — ships as `piilot-pack-hello-ui` on npm |
| `frontend/src/HelloModuleView.tsx` | React component rendered by the host `ModuleViewShell` | URL-backed sub-routing via `useSearchParams`, imports from `@plugin-host/*` |
| `.github/workflows/release-ui.yml` | npm publish on `ui-v*` tag | Mirrors the PyPI workflow for the backend |

Full reference: see the [Piilot plugin development guide][guide].

### Dual distribution

- **Backend** — `piilot-pack-hello` on PyPI, tagged `v<version>`.
- **Frontend** — `piilot-pack-hello-ui` on npm, tagged `ui-v<version>`.

Both ship from this single repo; the two release workflows publish
independently so a backend hot-fix doesn't force a frontend release
and vice-versa.

## Install

### Self-hosted Piilot (docker-compose.selfhost.yml)

```bash
# Drop the package into /app/plugins/
pip install piilot-pack-hello
# or for a git-based install while the SDK is still pre-PyPI:
pip install git+https://github.com/Kinetics-Consulting-V2/piilot-pack-hello.git@v0.1.0

# Restart the backend
docker compose restart backend
```

### Piilot Cloud (SaaS)

Add the dependency to the core's `requirements.txt`:

```
piilot-pack-hello @ git+https://github.com/Kinetics-Consulting-V2/piilot-pack-hello.git@v0.1.0
```

Coolify rebuilds the backend image; the loader picks up the plugin at
startup and applies migrations. Enable for a given company via:

```bash
curl -X PUT \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "X-Company-Id: $COMPANY_ID" \
  https://api.piilot.ai/admin/plugins/hello/activations/$COMPANY_ID
```

## Usage

TODO: how a user interacts with the plugin (module screens, agent
tools, integrations…).

## Development

### Local setup

```bash
# Clone next to the Piilot core
cd /opt/factory/projects
git clone https://github.com/Kinetics-Consulting-V2/piilot-pack-hello.git

# Install in editable mode with dev extras
cd piilot-pack-hello
pip install -e .[dev]
```

Then add the plugin as a bind mount in the core's
`docker-compose.override.yml` (gitignored):

```yaml
services:
  backend:
    volumes:
      - ../piilot-pack-hello:/app/plugins/piilot-pack-hello
```

Restart the backend and watch for:

```
[plugins] Loaded: hello v0.1.0 (handlers=1, tools=0)
```

### Run the tests

```bash
pytest
```

## Versioning

This plugin follows [Semantic Versioning](https://semver.org/). The
`sdk_compat` range in `pyproject.toml` pins the Piilot SDK versions
we build against. Watch the core's
[`docs/SDK_CHANGELOG.md`][changelog] for breaking changes.

[changelog]: https://github.com/Kinetics-Consulting-V2/AICockpit/blob/main/docs/SDK_CHANGELOG.md

## License

Apache-2.0. See [`LICENSE`](LICENSE).
