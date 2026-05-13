"""Smoke tests that prove the plugin boots correctly.

These are the minimal tests every plugin should ship. They prove:

1. The plugin package imports without error.
2. The manifest loaded from ``pyproject.toml`` is valid against the
   Piilot SDK JSON Schema (namespace, sdk_compat, supported_modes, ...).
3. The ``Plugin.register(ctx)`` call wires the declared handler /
   migrations / locales without raising.
4. The default handler returns the expected shape.

They run **without** a Piilot backend: we feed the plugin a fake
Context from ``conftest.py``.
"""

from __future__ import annotations

import importlib


def test_plugin_package_imports():
    """The plugin package is importable — basic syntactic smoke."""
    pkg = importlib.import_module("piilot_pack_hello")
    assert hasattr(pkg, "Plugin"), "The plugin package must expose a 'Plugin' class"


def test_manifest_valid():
    """The pyproject.toml manifest passes the SDK schema.

    We don't hardcode the namespace value — the test must keep passing
    after ``./init-plugin.sh`` renames the plugin.
    """
    pkg = importlib.import_module("piilot_pack_hello")
    m = pkg.Plugin.manifest
    assert m["manifest_version"] == 1
    assert isinstance(m["namespace"], str) and m["namespace"]
    # The SDK validated the shape at load time; we just sanity-check the fused dict.
    assert "supported_modes" in m and m["supported_modes"]
    assert "sdk_compat" in m


def test_plugin_register_wires_handler(fake_ctx, plugin_context):
    """Plugin.register() runs to completion against a fake Context.

    The plugin_context fixture sets ``current_plugin`` so that SDK
    primitives (register_tool, register_module, ...) called from
    ``register()`` can resolve the plugin's namespace.
    """
    pkg = importlib.import_module("piilot_pack_hello")
    plugin = pkg.Plugin()
    with plugin_context("hello"):
        plugin.register(fake_ctx)  # must not raise


def test_hello_handler_returns_expected_shape(fake_ctx):
    """The sample handler returns the canonical shape."""
    from piilot_pack_hello.handlers import hello_handler

    result = hello_handler(fake_ctx, {"name": "Alice"})
    assert result["status"] == "ok"
    assert "Hello Alice" in result["message"]
    assert result["company"] == "Fake Co"


def test_hello_handler_without_company(fake_ctx):
    """ctx.company is None at boot; handler should handle gracefully."""
    fake_ctx.company = None
    from piilot_pack_hello.handlers import hello_handler

    result = hello_handler(fake_ctx, {})
    assert result["status"] == "ok"
    assert result["company"] == "<no company bound>"
