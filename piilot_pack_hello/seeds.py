"""Example use of ``piilot.sdk.modules`` + ``piilot.sdk.templates`` — seed
a dashboard module row and a ready-to-use agent template.

Demonstrates:

* :func:`piilot.sdk.modules.register_module` — idempotent upsert on
  ``modules.modules`` keyed on ``module_slug``. Re-installs refresh
  the row's descriptive columns (name, icon, description, ...) while
  preserving the UUID so user grants / bookmarks stay stable.
* :func:`piilot.sdk.templates.register_template` — idempotent upsert
  on ``agents.agent_templates`` keyed on ``id`` (UUID). Use a stable
  UUID per template across plugin versions.
"""

from __future__ import annotations

from piilot.sdk.modules import register_module
from piilot.sdk.templates import register_template

# Stable UUID for the hello agent template. Never regenerate this —
# change the UUID only if you want a NEW template (the old row is left
# alone for users who've customized it).
_HELLO_AGENT_TEMPLATE_ID = "aaaaaaaa-0000-4000-8000-0000000000ff"


def wire_seeds() -> None:
    """Register the template's module + agent template.

    Called from ``Plugin.register()``. Both calls are buffered by the
    SDK and upserted by the plugin loader after ``register()`` returns —
    safe to call on every boot.
    """

    # Module seed — appears in the Modules section of the UI once the
    # plugin is activated for a company.
    register_module(
        {
            "slug": "hello.dashboard",
            "module_name": "Hello Demo",
            "description": "Minimal demo module — see the piilot-plugin-template.",
            "icon": "hand",
            "category": "other",
            "status": "published",
            "config": {
                "type": "dashboard",
            },
        }
    )

    # Agent template seed — appears in the agent builder for the
    # activated company.
    register_template(
        {
            "id": _HELLO_AGENT_TEMPLATE_ID,
            "slug": "hello-assistant",
            "template_name": "Hello Assistant",
            "description": "Demo agent that can greet users via hello_greet.",
            "template_category": "other",
            "icon": "hand",
            "prompt_system": (
                "You are a helpful assistant. "
                "Use the hello_greet tool when asked to greet someone."
            ),
            "tools_enabled": ["hello_greet", "send_message", "finish"],
            "llm_model": "gpt-4o-mini",
            "llm_temperature": 0.3,
        }
    )
