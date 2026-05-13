"""Example use of ``piilot.sdk.tools`` + ``piilot.sdk.session`` — a
LangChain ``StructuredTool`` that LLM agents can call and a system-
prompt builder that advertises what the plugin offers.

Demonstrates:

* :func:`piilot.sdk.tools.register_tool` — registers the tool under
  the plugin's namespace (auto-filled from ``current_plugin``).
* :func:`piilot.sdk.tools.bind_session` — adapts the tool's
  ``session_id`` parameter so LangGraph injects it from
  ``RunnableConfig`` instead of asking the LLM to pass it. Required
  since SDK ``v0.6.0`` — without this wrapper the LLM no longer
  receives the session id and every tool call falls through to the
  "session not found" branch (the system prompt no longer carries
  a ``--- SESSION ---`` block since the host's PLT-35 prompt-cache
  fix).
* ``spec["system_prompt_builder"]`` — optional callable invoked at
  agent build time; its return value is appended to the system prompt
  if non-empty. Use it to tell the LLM about the plugin's active state.
* :func:`piilot.sdk.session.get` — read the session state to access
  the caller's company context.

The tool writes via the ``repo.py`` example, so it also demonstrates
end-to-end integration of session → tool → DB.
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from piilot.sdk.session import get as get_session
from piilot.sdk.tools import bind_session, register_tool

from . import repo


def _hello_greet_fn(name: str = "world", session_id: str = "") -> str:
    """Record a greeting for the active company and return a confirmation.

    Runs in the LangGraph ReAct loop — keep the return value short and
    human-friendly; the LLM will pick it up verbatim in its response.

    The ``session_id`` parameter is **not** exposed to the LLM —
    ``bind_session`` (applied to the export below) replaces it with a
    ``config: RunnableConfig`` slot that LangGraph's ``ToolNode``
    populates from the run's config. Direct calls to this function
    in unit tests still work — pass ``session_id=`` explicitly.
    """
    state = get_session(session_id)
    if state is None:
        return "Session not found."
    company_id = state.user_infos.get("_organization_id")
    if not company_id:
        return "No company context in session."

    # We're inside a sync tool callback — ``run_in_thread`` is already
    # wrapping the caller. Direct sync calls are fine here.
    new_count = repo._increment_counter_sync(
        company_id,
        {"name": name, "source": "agent_tool"},
    )
    return f"Hi {name}! (greet #{new_count})"


# ``bind_session`` strips ``session_id`` from the LLM-facing schema and
# forwards LangGraph's ``RunnableConfig`` to the inner ``_fn``. Required
# since SDK 0.6.0 — without it the LLM has no way to pass the session
# id (the ``--- SESSION ---`` system-prompt block was removed by the
# host's PLT-35 prompt-cache stabilisation).
hello_greet = StructuredTool.from_function(
    bind_session(_hello_greet_fn),
    name="hello_greet",
    description="Greets someone by name and increments the greet counter.",
)


def build_hello_prompt_block(company_id: str) -> str:
    """System-prompt block — advertises the hello plugin to the LLM.

    Called on every agent build for a given company. Returning ``""``
    keeps the block out of the prompt (e.g. if the plugin isn't
    configured for this tenant).

    Signature must be ``(company_id: str) -> str`` — see
    ``piilot.sdk.tools.register_tool`` documentation.
    """
    # A real plugin would inspect DB / cache state here to decide what
    # to advertise. For the template we keep it unconditional.
    return (
        "\n\n--- HELLO ---\n"
        "The ``hello_greet(name)`` tool is available. "
        "Use it to greet users by name."
    )


def wire_tools() -> None:
    """Register the hello tool + its prompt builder.

    Called from ``Plugin.register()``. The spec dict's ``id`` becomes
    ``hello_greet`` in the agent ``TOOL_REGISTRY`` (namespace + name
    joined with ``_``).
    """
    register_tool(
        {
            "id": "hello.greet",
            "tool": hello_greet,
            "label_key": "hello.tools.greet.label",
            "description_key": "hello.tools.greet.description",
            "system_prompt_builder": build_hello_prompt_block,
        }
    )
