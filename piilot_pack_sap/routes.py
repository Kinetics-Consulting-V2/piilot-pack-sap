"""HTTP routes mounted under ``/plugins/sap/*``.

In v0.1.0 (Phase 0 scaffolding) we ship a single ``/health`` endpoint
so the host can verify the router mount machinery works. Phase 1 adds
the real routes:

* ``GET  /plugins/sap/connections``         list connections / company
* ``POST /plugins/sap/connections``         create connection
* ``DELETE /plugins/sap/connections/{id}``  remove connection
* ``POST /plugins/sap/connections/{id}/test`` test reachability
* ``POST /plugins/sap/connections/{id}/sync-metadata`` refresh $metadata
* ``GET  /plugins/sap/entities``            list cached EntitySets
* ``GET  /plugins/sap/entities/{name}``     describe one entity
* ``GET  /plugins/sap/audit``               paginated audit log

All routes will require an authenticated user with a company
membership (``Depends(require_user)``). Admin-only routes additionally
check the user's role.

See :func:`piilot.sdk.http.register_router` for the mount mechanics.
The router's own ``prefix`` argument is ignored at mount time — use
the ``prefix`` parameter of ``register_router``. Routes land at
``/plugins/<namespace><prefix>/...``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from piilot.sdk.http import register_router, require_user

router = APIRouter()

# Modern FastAPI auth dependency pattern (PEP 593). Returns the tuple
# `(user_id, role, company_id)` — see piilot.sdk.http.require_user.
AuthDep = Annotated[tuple, Depends(require_user)]


@router.get("/health")
async def health(auth: AuthDep) -> dict:
    """Return the plugin's runtime health for the caller's company.

    Phase 0 stub — Phase 1 will enrich with connection count, last
    metadata sync, audit log row count, and per-connection health
    snapshots.
    """
    user_id, role, company_id = auth
    return {
        "plugin": "sap",
        "version": "0.1.0",
        "phase": "0-scaffolding",
        "company_id": company_id,
        "user_id": user_id,
        "role": role,
    }


def wire_routes() -> None:
    """Register the router under ``/plugins/sap``.

    Called from ``Plugin.register()``. The empty ``prefix`` means the
    routes are mounted at the namespace root:

    * ``GET /plugins/sap/health``
    """
    register_router(router, prefix="")
