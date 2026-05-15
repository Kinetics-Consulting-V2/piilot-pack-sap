-- ============================================================
-- Migration: 001_init_sap.sql
-- Plugin: sap (piilot-pack-sap v0.1.0)
-- ============================================================
-- Idempotent DDL for the SAP S/4HANA Cloud OData connector. All
-- statements use IF NOT EXISTS / DROP ... IF EXISTS — the core
-- loader's static heuristic refuses non-idempotent migrations.
--
-- Schema: integrations_sap (one schema per connector, isolated from
-- core + other plugins). Same convention as piilot-pack-supabase
-- (integrations_supabase) and piilot-pack-pennylane
-- (integrations_pennylane).
--
-- Tables:
--   * connections        per-company SAP connection (encrypted creds
--                        live in core's plugin_connections table,
--                        this one stores config metadata)
--   * schema_snapshot    $metadata XML introspection cache,
--                        re-synced on demand from the SAP instance
--   * audit_log          immutable trail of every OData query
--                        executed by an agent tool
-- ============================================================

BEGIN;

CREATE SCHEMA IF NOT EXISTS integrations_sap;
GRANT USAGE ON SCHEMA integrations_sap TO piilot, piilot_app;

-- ------------------------------------------------------------
-- connections — one row per (company, base_url) tuple
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS integrations_sap.connections (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id           UUID NOT NULL,
    -- Foreign key to core's plugin_connections — that's where the
    -- encrypted creds (basic password / oauth client_secret) live.
    plugin_connection_id UUID,
    -- Display label shown in the UI ("Sandbox", "Prod", "QA"...).
    label                TEXT NOT NULL,
    -- Sanitized base URL (no trailing slash). Stored for fast lookups.
    base_url             TEXT NOT NULL,
    -- "basic" | "oauth_client_credentials" — auth mode used for this
    -- connection. Matches credentials_schema.auth_mode in the manifest.
    auth_mode            TEXT NOT NULL,
    -- Connection lifecycle flag.
    is_active            BOOLEAN NOT NULL DEFAULT TRUE,
    -- Health snapshot (last test connection result).
    last_health_check_at TIMESTAMPTZ,
    last_health_status   TEXT,
    last_health_error    TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (company_id, label)
);

CREATE INDEX IF NOT EXISTS idx_sap_connections_company
    ON integrations_sap.connections (company_id);

CREATE INDEX IF NOT EXISTS idx_sap_connections_plugin_conn
    ON integrations_sap.connections (plugin_connection_id);

ALTER TABLE integrations_sap.connections ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS sap_connections_select_member
    ON integrations_sap.connections;
CREATE POLICY sap_connections_select_member
    ON integrations_sap.connections
    FOR SELECT
    USING (public.is_company_member(company_id));

DROP POLICY IF EXISTS sap_connections_insert_member
    ON integrations_sap.connections;
CREATE POLICY sap_connections_insert_member
    ON integrations_sap.connections
    FOR INSERT
    WITH CHECK (public.is_company_member(company_id));

DROP POLICY IF EXISTS sap_connections_update_member
    ON integrations_sap.connections;
CREATE POLICY sap_connections_update_member
    ON integrations_sap.connections
    FOR UPDATE
    USING (public.is_company_member(company_id))
    WITH CHECK (public.is_company_member(company_id));

DROP POLICY IF EXISTS sap_connections_delete_member
    ON integrations_sap.connections;
CREATE POLICY sap_connections_delete_member
    ON integrations_sap.connections
    FOR DELETE
    USING (public.is_company_member(company_id));

-- ------------------------------------------------------------
-- schema_snapshot — $metadata XML introspection cache
-- ------------------------------------------------------------
-- One row per (connection, entity_set) tuple. Populated by the
-- $metadata sync (Phase 1). Each row captures a single EntitySet's
-- shape: properties + their types + navigation properties. The
-- payload column carries the structured introspection result; the
-- raw XML is NOT stored (re-fetchable on demand).
CREATE TABLE IF NOT EXISTS integrations_sap.schema_snapshot (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id   UUID NOT NULL REFERENCES integrations_sap.connections (id)
                                  ON DELETE CASCADE,
    company_id      UUID NOT NULL,
    -- E.g. "A_BusinessPartner", "A_JournalEntryItem".
    entity_set_name TEXT NOT NULL,
    -- Service path on the SAP side
    -- (e.g. "/sap/opu/odata/sap/API_BUSINESS_PARTNER").
    service_path    TEXT NOT NULL,
    -- Free-text label / description extracted from $metadata or curated
    -- by the plugin author.
    label           TEXT,
    description     TEXT,
    -- Full structured introspection result (properties, navigations,
    -- annotations). See docstring in introspect.py (Phase 1) for the
    -- exact JSON shape.
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- When this snapshot row was last refreshed from the SAP instance.
    last_synced_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (connection_id, service_path, entity_set_name)
);

CREATE INDEX IF NOT EXISTS idx_sap_schema_snap_company
    ON integrations_sap.schema_snapshot (company_id);

CREATE INDEX IF NOT EXISTS idx_sap_schema_snap_conn_entity
    ON integrations_sap.schema_snapshot (connection_id, entity_set_name);

ALTER TABLE integrations_sap.schema_snapshot ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS sap_schema_snap_select_member
    ON integrations_sap.schema_snapshot;
CREATE POLICY sap_schema_snap_select_member
    ON integrations_sap.schema_snapshot
    FOR SELECT
    USING (public.is_company_member(company_id));

DROP POLICY IF EXISTS sap_schema_snap_insert_member
    ON integrations_sap.schema_snapshot;
CREATE POLICY sap_schema_snap_insert_member
    ON integrations_sap.schema_snapshot
    FOR INSERT
    WITH CHECK (public.is_company_member(company_id));

DROP POLICY IF EXISTS sap_schema_snap_update_member
    ON integrations_sap.schema_snapshot;
CREATE POLICY sap_schema_snap_update_member
    ON integrations_sap.schema_snapshot
    FOR UPDATE
    USING (public.is_company_member(company_id))
    WITH CHECK (public.is_company_member(company_id));

DROP POLICY IF EXISTS sap_schema_snap_delete_member
    ON integrations_sap.schema_snapshot;
CREATE POLICY sap_schema_snap_delete_member
    ON integrations_sap.schema_snapshot
    FOR DELETE
    USING (public.is_company_member(company_id));

-- ------------------------------------------------------------
-- audit_log — immutable trail of every OData query
-- ------------------------------------------------------------
-- Append-only. One row per OData call issued by an agent tool. Used
-- for compliance ("who accessed what when"), debugging (chain a slow
-- agent response back to the offending query) and security forensics
-- (spot prompt-injection attempts).
--
-- Retention policy: no automatic purge. The application layer
-- (Phase 2) is responsible for truncation if needed. Audit log
-- expectations = unbounded.
CREATE TABLE IF NOT EXISTS integrations_sap.audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL,
    connection_id   UUID REFERENCES integrations_sap.connections (id)
                          ON DELETE SET NULL,
    -- User that triggered the agent run; NULL for system tools.
    user_id         UUID,
    -- Agent session that triggered the call.
    session_id      TEXT,
    -- Tool that built the OData query (one of the 9 tools shipped in
    -- Phase 2: "sap.select", "sap.aggregate"...).
    tool_id         TEXT NOT NULL,
    -- Target entity set (e.g. "A_BusinessPartner").
    entity_set      TEXT,
    -- Final OData URL issued (with $filter/$select/$top/$apply...).
    -- Stored as plain text for grep-ability.
    odata_url       TEXT NOT NULL,
    -- HTTP method (always GET in v1 — read-only).
    http_method     TEXT NOT NULL DEFAULT 'GET',
    -- "ok" | "validator_rejected" | "auth_error" | "http_error" |
    -- "parse_error" | "rate_limited" | "timeout"
    status          TEXT NOT NULL,
    http_status     INTEGER,
    -- Latency in milliseconds (round-trip including auth refresh).
    latency_ms      INTEGER,
    -- Optional error payload (validator reason, HTTP error body
    -- truncated to 2 KB, ...). NEVER store the raw OData response
    -- body — would explode the table and risk leaking customer data.
    error           TEXT,
    -- Approximate result size — number of entries returned, NOT bytes.
    result_count    INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sap_audit_company_created
    ON integrations_sap.audit_log (company_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_sap_audit_tool
    ON integrations_sap.audit_log (tool_id);

CREATE INDEX IF NOT EXISTS idx_sap_audit_status_partial
    ON integrations_sap.audit_log (company_id, created_at DESC)
    WHERE status <> 'ok';

ALTER TABLE integrations_sap.audit_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS sap_audit_select_member
    ON integrations_sap.audit_log;
CREATE POLICY sap_audit_select_member
    ON integrations_sap.audit_log
    FOR SELECT
    USING (public.is_company_member(company_id));

DROP POLICY IF EXISTS sap_audit_insert_member
    ON integrations_sap.audit_log;
CREATE POLICY sap_audit_insert_member
    ON integrations_sap.audit_log
    FOR INSERT
    WITH CHECK (public.is_company_member(company_id));

-- No UPDATE / DELETE policies on audit_log — immutable by design.

-- ------------------------------------------------------------
-- Maintenance triggers — refresh updated_at on every row write
-- ------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_sap_connections_set_updated_at
    ON integrations_sap.connections;
CREATE TRIGGER trg_sap_connections_set_updated_at
    BEFORE UPDATE ON integrations_sap.connections
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_sap_schema_snap_set_updated_at
    ON integrations_sap.schema_snapshot;
CREATE TRIGGER trg_sap_schema_snap_set_updated_at
    BEFORE UPDATE ON integrations_sap.schema_snapshot
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

COMMIT;
