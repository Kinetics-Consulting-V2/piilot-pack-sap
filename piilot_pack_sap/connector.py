"""SAP S/4HANA Cloud OData v4 connector specification.

Registers the ``sap.s4hana_cloud`` connector with the Piilot core so it
appears in Settings → Integrations. The actual auth handshake + OData
client live in Phase 1 — for now ``wire_connectors`` just declares the
connector shape so the host UI can render the connection form.

Decision tour-1 (suivi.md): v1 supports two auth modes only:

* **basic** — username + password, sandbox-friendly + small clients
* **oauth_client_credentials** — standard SAP S/4HANA Cloud productive
  Communication Arrangement / Communication User

X.509 cert auth is deferred to v1.1.
"""

from __future__ import annotations

from piilot.sdk.connectors import register_connector


def wire_connectors() -> None:
    """Register the SAP S/4HANA Cloud connector spec.

    The credentials schema mirrors ``[[tool.piilot.plugin.provides
    .connectors.credentials_schema]]`` in ``pyproject.toml`` — both
    must stay in sync. The manifest entry is informational; the
    runtime registry is populated by this call.
    """
    register_connector(
        {
            "id": "sap.s4hana_cloud",
            "auth_type": "custom",
            "credentials_schema": [
                {
                    "name": "auth_mode",
                    "type": "string",
                    "required": True,
                    "default": "basic",
                    # Values accepted at runtime:
                    #   "basic" | "oauth_client_credentials"
                    "label_key": (
                        "sap.connectors.s4hana_cloud.auth_mode.label"
                    ),
                },
                {
                    "name": "base_url",
                    "type": "string",
                    "required": True,
                    # E.g. https://my123456.s4hana.cloud.sap (no trailing /)
                    "label_key": (
                        "sap.connectors.s4hana_cloud.base_url.label"
                    ),
                },
                # --- Basic auth fields ---
                {
                    "name": "basic_username",
                    "type": "string",
                    "required": False,
                    "label_key": (
                        "sap.connectors.s4hana_cloud.basic_username.label"
                    ),
                },
                {
                    "name": "basic_password",
                    "type": "secret",
                    "required": False,
                    "label_key": (
                        "sap.connectors.s4hana_cloud.basic_password.label"
                    ),
                },
                # --- OAuth 2.0 client_credentials fields ---
                {
                    "name": "oauth_token_url",
                    "type": "string",
                    "required": False,
                    "label_key": (
                        "sap.connectors.s4hana_cloud.oauth_token_url.label"
                    ),
                },
                {
                    "name": "oauth_client_id",
                    "type": "string",
                    "required": False,
                    "label_key": (
                        "sap.connectors.s4hana_cloud.oauth_client_id.label"
                    ),
                },
                {
                    "name": "oauth_client_secret",
                    "type": "secret",
                    "required": False,
                    "label_key": (
                        "sap.connectors.s4hana_cloud.oauth_client_secret.label"
                    ),
                },
                {
                    "name": "oauth_scope",
                    "type": "string",
                    "required": False,
                    "label_key": (
                        "sap.connectors.s4hana_cloud.oauth_scope.label"
                    ),
                },
            ],
        }
    )
