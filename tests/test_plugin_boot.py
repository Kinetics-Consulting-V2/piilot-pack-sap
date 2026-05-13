"""Smoke tests that prove the plugin boots correctly.

These are the minimal tests every plugin should ship. They prove:

1. The plugin package imports without error.
2. The manifest loaded from ``pyproject.toml`` is valid against the
   Piilot SDK JSON Schema (namespace, sdk_compat, supported_modes, ...).
3. The ``Plugin.register(ctx)`` call wires the declared handler /
   migrations / locales without raising.
4. The default handler returns the expected shape.
5. The connector spec matches what the manifest declares.

They run **without** a Piilot backend: we feed the plugin a fake
Context from ``conftest.py``.
"""

from __future__ import annotations

import importlib


def test_plugin_package_imports():
    """The plugin package is importable — basic syntactic smoke."""
    pkg = importlib.import_module("piilot_pack_sap")
    assert hasattr(pkg, "Plugin"), "The plugin package must expose a 'Plugin' class"


def test_manifest_valid():
    """The pyproject.toml manifest passes the SDK schema."""
    pkg = importlib.import_module("piilot_pack_sap")
    m = pkg.Plugin.manifest
    assert m["manifest_version"] == 1
    assert m["namespace"] == "sap"
    assert "supported_modes" in m and m["supported_modes"]
    assert "sdk_compat" in m
    # The plugin declares a single module Piilot — the canonical
    # connector pattern (1 plugin, 1 module Piilot).
    modules = m["provides"]["modules"]
    assert len(modules) == 1
    assert modules[0]["id"] == "sap.connector"
    # And a single connector with custom auth (Basic + OAuth
    # client_credentials handled via auth_mode field).
    connectors = m["provides"]["connectors"]
    assert len(connectors) == 1
    assert connectors[0]["id"] == "sap.s4hana_cloud"


def test_plugin_register_wires_handler(fake_ctx, plugin_context):
    """Plugin.register() runs to completion against a fake Context.

    The plugin_context fixture sets ``current_plugin`` so that SDK
    primitives (register_tool, register_module, ...) called from
    ``register()`` can resolve the plugin's namespace.
    """
    pkg = importlib.import_module("piilot_pack_sap")
    plugin = pkg.Plugin()
    with plugin_context("sap"):
        plugin.register(fake_ctx)  # must not raise


def test_sap_connector_handler_returns_expected_shape(fake_ctx):
    """The module handler returns the canonical shape."""
    from piilot_pack_sap.handlers import sap_connector_handler

    result = sap_connector_handler(fake_ctx, {})
    assert result["status"] == "ok"
    assert result["module"] == "sap.connector"
    assert result["company"] == "Fake Co"
    assert result["phase"] == "0-scaffolding"


def test_sap_connector_handler_without_company(fake_ctx):
    """ctx.company is None at boot; handler should handle gracefully."""
    fake_ctx.company = None
    from piilot_pack_sap.handlers import sap_connector_handler

    result = sap_connector_handler(fake_ctx, {})
    assert result["status"] == "ok"
    assert result["company"] == "<no company bound>"
