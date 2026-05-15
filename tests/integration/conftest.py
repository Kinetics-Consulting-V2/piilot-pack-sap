"""Shared fixtures + auto-skip for integration tests.

The integration suite hits ``sandbox.api.sap.com`` over the real network and
needs a working ``SAP_API_HUB_KEY``. It is opt-in:

* Skipped silently if ``SAP_API_HUB_KEY`` is not set.
* The optional ``.env.dev`` file at the repo root is loaded automatically
  (when ``python-dotenv`` is installed) so contributors who keep their
  sandbox key there don't need to export it manually.

To run only this suite::

    pytest tests/integration -m integration

To exclude it from the default run::

    pytest -m "not integration"
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOTENV_PATH = REPO_ROOT / ".env.dev"

try:  # pragma: no cover - optional dependency
    from dotenv import load_dotenv

    if DOTENV_PATH.exists():
        load_dotenv(DOTENV_PATH, override=False)
except ImportError:  # pragma: no cover - optional dependency
    pass


SAP_API_HUB_KEY = os.environ.get("SAP_API_HUB_KEY")
SAP_SANDBOX_BASE_URL = os.environ.get(
    "SAP_SANDBOX_BASE_URL", "https://sandbox.api.sap.com/s4hanacloud"
)


def pytest_collection_modifyitems(config, items):
    """Mark every test in this folder as ``integration`` and skip without key."""
    skip = pytest.mark.skip(reason="SAP_API_HUB_KEY not set — integration tests skipped")
    for item in items:
        item.add_marker(pytest.mark.integration)
        if SAP_API_HUB_KEY is None:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def sandbox_api_key() -> str:
    assert SAP_API_HUB_KEY is not None, "SAP_API_HUB_KEY must be set"
    return SAP_API_HUB_KEY


@pytest.fixture(scope="session")
def sandbox_bp_base_url() -> str:
    """Business Partner OData v2 service base URL on the sandbox."""
    return f"{SAP_SANDBOX_BASE_URL.rstrip('/')}" "/sap/opu/odata/sap/API_BUSINESS_PARTNER"
