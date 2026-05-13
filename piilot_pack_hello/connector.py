"""Example — ``piilot.sdk.connectors`` (commented out).

This file illustrates the pattern for declaring and using an
integration connector. It is **not** wired in the template runtime
because a functional connector needs a real external API key and
endpoint — registering an inert one would pollute the Settings UI.

When you fork the template for a real plugin, uncomment the body of
``wire_connectors`` and adapt the spec to your external API.

Documentation: see ``docs/sdk/PLUGIN_DEVELOPMENT.md`` section 10
(Settings integrations) in the Piilot core repo.
"""

from __future__ import annotations


def wire_connectors() -> None:
    """Register the plugin's external-API connectors.

    Uncomment and adapt below when you have a real external API.
    """
    # from piilot.sdk.connectors import register_connector
    #
    # # Declare a connector. The spec's ``id`` must be namespaced
    # # (``<plugin_ns>.<connector_id>``). Fields marked ``type: secret``
    # # in credentials_schema are auto-encrypted when a user saves their
    # # credentials via the Settings UI.
    # register_connector({
    #     "id": "hello.api",
    #     "auth_type": "api_key",
    #     "credentials_schema": [
    #         {
    #             "name": "api_key",
    #             "type": "secret",
    #             "required": True,
    #             "label_key": "hello.connectors.api.api_key.label",
    #         },
    #         {
    #             "name": "base_url",
    #             "type": "string",
    #             "required": True,
    #             "default": "https://api.hello.example.com",
    #             "label_key": "hello.connectors.api.base_url.label",
    #         },
    #     ],
    # })
    #
    # # Once declared, your plugin code (usually in a sync handler or
    # # agent tool) reads live credentials via:
    # #
    # #   from piilot.sdk.connectors import list_connections, get_connection
    # #   conns = list_connections(company_id, provider="hello")
    # #   decrypted = get_connection(conns[0]["id"])
    # #   # decrypted["credentials"]["api_key"] is the plaintext
    pass
