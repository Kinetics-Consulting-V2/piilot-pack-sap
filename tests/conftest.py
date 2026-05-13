"""Shared fixtures for ``piilot-pack-sap`` tests.

The unit tests don't require a running Piilot backend. We build a
minimal fake Context that exposes exactly what the plugin's handlers
and tools read.

SDK v0.2+ primitives — ``register_tool`` / ``register_module`` /
``register_template`` / ``register_router`` — read the
``piilot.sdk._runtime.current_plugin`` contextvar to resolve the
caller's namespace. Tests that invoke ``Plugin.register()`` must set
the contextvar around the call; the ``plugin_context`` fixture does
that for you.

SDK v0.3 — ``piilot.sdk.testing`` now ships two helpers that
plugin test suites previously had to hand-roll. We wire them here as
an autouse session fixture:

* ``stub_http_primitives()`` replaces ``piilot.sdk.http.get_real_ip``
  with a deterministic ``"127.0.0.1"`` return so slowapi's
  ``key_func(request)`` doesn't trip on ``NotImplementedError`` when
  a plugin test touches its own HTTP routes without going through
  host boot.
* ``mock_db_conn(cursor)`` (context manager) is available from test
  bodies when you mock ``_get_conn`` — it neutralises the
  ``execute_values`` helper so the raw bytes-join implementation
  doesn't trip on a ``MagicMock`` cursor. Not autouse — opt-in per
  test because most plugin tests don't hit the DB directly.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from types import SimpleNamespace

import pytest


@pytest.fixture
def fake_ctx():
    """Return a minimal fake :class:`piilot.sdk.Context`.

    Handlers in this template read ``ctx.logger``, ``ctx.company`` (may
    be None at boot) and ``ctx.handlers/tools/...`` registries. Add
    more attributes here as your plugin grows.
    """
    return SimpleNamespace(
        db=None,
        company=SimpleNamespace(id="fake-company", name="Fake Co"),
        user=None,
        logger=logging.getLogger("test.sap"),
        handlers=SimpleNamespace(register=lambda *a, **kw: None),
        tools=SimpleNamespace(register=lambda *a, **kw: None),
        migrations=SimpleNamespace(register_schema=lambda *a, **kw: None),
        i18n=SimpleNamespace(register_locales=lambda *a, **kw: None),
        connectors=SimpleNamespace(register_connector=lambda *a, **kw: None),
        scheduler=SimpleNamespace(register_job=lambda *a, **kw: None),
        events=SimpleNamespace(on=lambda *a, **kw: None, emit=lambda *a, **kw: None),
        templates=SimpleNamespace(register=lambda *a, **kw: None),
    )


@contextmanager
def _plugin_context(namespace: str):
    """Set ``piilot.sdk._runtime.current_plugin`` for the duration of the
    block. Module-level ``register_tool`` / ``register_module`` /
    ``register_router`` resolve the plugin's namespace from this contextvar;
    calling them outside a context raises ``RuntimeError``.
    """
    from piilot.sdk._runtime import current_plugin

    token = current_plugin.set(namespace)
    try:
        yield
    finally:
        current_plugin.reset(token)


@pytest.fixture
def plugin_context():
    """Fixture wrapper around :func:`_plugin_context` — use as a context
    manager inside a test::

        def test_something(plugin_context):
            with plugin_context("sap"):
                plugin.register(fake_ctx)
    """
    return _plugin_context


@pytest.fixture(autouse=True, scope="session")
def _stub_sdk_http():
    """Patch ``piilot.sdk.http.get_real_ip`` so slowapi's ``key_func``
    doesn't trip on ``NotImplementedError`` in isolated plugin tests.

    The host loader wires the real implementation at boot; this fixture
    emulates that so the test suite doesn't need a running backend.
    New in SDK v0.3 — prior to that, every plugin had to copy this
    stub into its own ``conftest.py``.
    """
    try:
        from piilot.sdk.testing import stub_http_primitives
    except ImportError:
        yield
        return

    stub_http_primitives()
    yield


@pytest.fixture(autouse=True)
def _reset_sdk_registries():
    """Clear SDK-internal registries between tests so state from a prior
    test's ``Plugin.register()`` call doesn't leak into the next one."""
    # Import lazily — test collection shouldn't depend on piilot-sdk being
    # installed at module-scan time.
    try:
        from piilot.sdk import http as sdk_http
        from piilot.sdk import modules as sdk_modules
        from piilot.sdk import templates as sdk_templates
        from piilot.sdk import tools as sdk_tools
    except ImportError:
        yield
        return

    # Snapshot and restore — in case the wiring is idempotent-broken
    # or a fixture runs its own setup.
    sdk_tools._reset_for_tests() if hasattr(sdk_tools, "_reset_for_tests") else None
    sdk_modules._drain()
    sdk_templates._drain()
    sdk_http._drain()

    yield

    sdk_tools._reset_for_tests() if hasattr(sdk_tools, "_reset_for_tests") else None
    sdk_modules._drain()
    sdk_templates._drain()
    sdk_http._drain()
