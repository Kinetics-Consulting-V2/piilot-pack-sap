"""Example — ``piilot.sdk.scheduler`` (commented out).

This file illustrates the pattern for declaring a periodic sync
handler that polls the plugin's connector and upserts external data
into local tables. It is **not** wired in the template runtime because
a functional sync needs a real connector (see ``connector.py``).

When you fork the template and implement your connector, uncomment
the body of ``wire_jobs`` and implement the ``sync_hello`` handler.

Documentation: see ``docs/sdk/PLUGIN_DEVELOPMENT.md`` section 15
(Scheduler) in the Piilot core repo.
"""

from __future__ import annotations

# async def sync_hello(connection: dict) -> dict:
#     """Full sync of the plugin's external data into local tables.
#
#     The core scheduler calls this once per connection whose
#     ``next_sync_at`` has passed. Signature: ``async def (conn: dict) -> dict``.
#
#     Return the created sync_log dict (see piilot.sdk.connectors.log_sync).
#     """
#     from datetime import datetime, timezone
#     from piilot.sdk.connectors import log_sync
#
#     started_at = datetime.now(timezone.utc)
#     company_id = connection["company_id"]
#
#     # ... call the external API, upsert rows into hello.* tables ...
#
#     return log_sync(
#         connection_id=connection["id"],
#         company_id=company_id,
#         sync_type="full",
#         status="success",
#         started_at=started_at,
#         completed_at=datetime.now(timezone.utc),
#         items_synced=0,
#     )


def wire_jobs() -> None:
    """Register sync handlers against the plugin's connector provider.

    Uncomment and adapt below when you have a real connector.
    """
    # from piilot.sdk.scheduler import register_sync_handler
    #
    # register_sync_handler(
    #     provider="hello",                # matches connection.provider
    #     handler=sync_hello,
    #     # firm_handler=sync_hello_firm,   # optional — multi-client variant
    # )
    pass
