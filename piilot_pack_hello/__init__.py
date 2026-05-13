"""Piilot plugin ``hello`` — showcase of SDK v0.2+ primitives.

Entry point of the template. The ``Plugin`` class is referenced by
``[project.entry-points."piilot.plugins"]`` in ``pyproject.toml`` and
instantiated once at Piilot backend startup.

What this plugin demonstrates (SDK v0.2+, pinned >=0.3.0)
---------------------------------------------------------

**Wired in runtime** (work with the plugin activated for a company):

* ``ctx.migrations`` — register the plugin's own SQL migrations.
* ``ctx.i18n`` — merge per-namespace locale catalogs.
* ``ctx.handlers`` — register module handlers (dispatched by the
  module runtime).
* :mod:`piilot.sdk.db` — see ``repo.py`` (cursor + Json + run_in_thread).
* :mod:`piilot.sdk.http` — see ``routes.py`` (register_router +
  Depends(require_user) + get_real_ip).
* :mod:`piilot.sdk.tools` + :mod:`piilot.sdk.session` — see ``tools.py``
  (register_tool with system_prompt_builder; session.get).
* :mod:`piilot.sdk.modules` + :mod:`piilot.sdk.templates` — see
  ``seeds.py`` (register_module + register_template, both idempotent).

**Illustrated in comments only** (need real external config):

* :mod:`piilot.sdk.connectors` — see ``connector.py``. Uncomment and
  adapt when you wire a real external API.
* :mod:`piilot.sdk.scheduler` — see ``jobs.py``. Uncomment the
  ``register_sync_handler`` call once you've implemented the sync fn.

Full reference: ``docs/sdk/PLUGIN_DEVELOPMENT.md`` in the Piilot core
repo.
"""

from __future__ import annotations

from piilot.sdk import Plugin as _Plugin
from piilot.sdk import load_manifest

from .connector import wire_connectors
from .handlers import hello_handler
from .jobs import wire_jobs
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
        # ---- Built-in registries (via ctx.X) ----

        # Declare migrations — the loader applies pending .sql files
        # from piilot_pack_hello/migrations/ in alphabetical order.
        ctx.migrations.register_schema(
            "hello",
            __file__,
            "migrations",
        )

        # Merge the plugin's i18n catalogs into the global catalog served
        # at GET /i18n/catalog. Every root key in locales/*.json MUST
        # equal the plugin's namespace.
        ctx.i18n.register_locales(
            "hello",
            __file__,
            "locales",
        )

        # Register the module handler. The id must match the one declared
        # in pyproject.toml (provides.modules[].id).
        ctx.handlers.register("hello.hello", hello_handler)

        # ---- SDK primitives (via piilot.sdk.* module-level API) ----

        # Mount /plugins/hello/counter and /plugins/hello/greet routes.
        wire_routes()

        # Register the hello_greet agent tool + its system-prompt builder.
        wire_tools()

        # Seed a module row + a ready-to-use agent template. Both
        # upserts are idempotent — safe to re-run at every boot.
        wire_seeds()

        # Connectors + sync handler are illustrated in comments only —
        # they need real external API config before they can be wired.
        wire_connectors()
        wire_jobs()
