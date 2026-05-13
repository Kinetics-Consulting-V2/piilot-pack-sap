"""Agent tools for the SAP connector — Phase 2 deliverable.

In v0.1.0 (Phase 0) ``wire_tools()`` is a no-op. Phase 2 will populate
this module with 9 OData tools:

* ``sap_search_entity(query)`` — RAG on metadata KB
* ``sap_describe_entity(name)`` — entity properties / navigations
* ``sap_select(entity, filters, select, orderby, top)`` — OData $filter
* ``sap_count(entity, filters)`` — OData $count=true
* ``sap_aggregate(entity, property, op, filters)`` — OData
  ``$apply=aggregate(...)``
* ``sap_top_n(entity, property, n, order, filters)`` — wrapper
* ``sap_navigate(entity, key, navigation)`` — follow Navigation Property
* ``sap_lookup(t-code, key)`` — admin opt-in technical-table access
* ``sap_invoke_function(function, args)`` — admin only

All tools will be wrapped with :func:`piilot.sdk.tools.bind_session`
so LangGraph can inject ``session_id`` via ``RunnableConfig`` (mandatory
since SDK 0.6.0, see ``PLUGIN_DEVELOPMENT.md §16``).

i18n keys required (FR + EN, populated at Phase 2 alongside the tool
registrations): ``sap.tools.<tool_name>.{label, description}``.
"""

from __future__ import annotations


def wire_tools() -> None:
    """No-op in Phase 0 — populated in Phase 2."""
    # Phase 2: 9 register_tool() calls, each wrapping a StructuredTool
    # built from a function decorated with bind_session.
    return None
