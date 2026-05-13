"""Module handlers for the ``hello`` plugin.

Each handler is a callable ``(ctx, payload) -> dict`` dispatched by the
Piilot module runtime when a user triggers the module from the UI.
Handlers are registered in ``__init__.py::Plugin.register()``.
"""

from __future__ import annotations

from typing import Any


def hello_handler(ctx: Any, payload: dict) -> dict:
    """Minimal module handler — echoes a greeting.

    Replace the body with the real pipeline of your plugin. Common
    patterns:

    * Read from your own PG schema (``hello.*``) via
      standard psycopg cursors.
    * Call your own connector's runtime CRUD via
      ``ctx.connectors.get_connection(...)``.
    * Emit structured logs with ``ctx.logger.info(...)``.
    """
    name = payload.get("name", "world")
    company_label = ctx.company.name if ctx.company else "<no company bound>"
    ctx.logger.info("hello.hello invoked for %s", company_label)
    return {
        "status": "ok",
        "message": f"Hello {name} from hello",
        "company": company_label,
    }
