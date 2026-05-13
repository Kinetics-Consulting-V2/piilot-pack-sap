"""Example use of ``piilot.sdk.http`` — two routes illustrating the
``register_router`` + auth dependency pattern.

Demonstrates:

* :func:`piilot.sdk.http.register_router` — mounts the router under
  ``/plugins/hello{prefix}``. The router's own prefix is ignored at
  mount time; use the ``prefix`` parameter.
* ``Depends(require_user)`` — any authenticated user with a company
  membership; returns ``(user_id, role, company_id)``.
* :func:`piilot.sdk.http.get_real_ip` — honors Cloudflare's
  ``CF-Connecting-IP`` and the X-Forwarded-For chain.

The two routes use the ``repo.py`` repository to demonstrate the
db primitives end-to-end.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from piilot.sdk.http import get_real_ip, register_router, require_user

from . import repo

router = APIRouter()

# Modern FastAPI auth dependency pattern (PEP 593). Returns the tuple
# `(user_id, role, company_id)` — see piilot.sdk.http.require_user.
AuthDep = Annotated[tuple, Depends(require_user)]


@router.get("/counter")
async def get_counter(auth: AuthDep):
    """Return the current greet count for the caller's company."""
    user_id, role, company_id = auth
    if not company_id:
        return {"count": 0, "note": "user has no company membership"}
    count = await repo.get_counter(company_id)
    return {"count": count, "company_id": company_id}


@router.post("/greet")
async def greet(
    request: Request,
    payload: dict,
    auth: AuthDep,
):
    """Increment the counter and return the new value.

    Records the caller's IP and user_id in the last_metadata JSONB
    column — useful to demonstrate how to enrich DB writes with
    per-request context.
    """
    user_id, role, company_id = auth
    if not company_id:
        return {"status": "error", "detail": "no company context"}
    metadata = {
        "name": payload.get("name", "world"),
        "ip": get_real_ip(request),
        "user_id": user_id,
    }
    new_count = await repo.increment_counter(company_id, metadata)
    return {
        "status": "ok",
        "count": new_count,
        "greeted": metadata["name"],
    }


def wire_routes() -> None:
    """Register the router under ``/plugins/hello``.

    Called from ``Plugin.register()``. The empty ``prefix`` means the
    routes are mounted at the namespace root:

    * ``GET  /plugins/hello/counter``
    * ``POST /plugins/hello/greet``
    """
    register_router(router, prefix="")
