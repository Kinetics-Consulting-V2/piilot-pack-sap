-- ============================================================
-- Migration: 001_init.sql
-- Plugin: hello
-- ============================================================
-- All plugin migrations MUST be idempotent: the Piilot loader refuses
-- a plugin whose .sql files contain a CREATE TABLE / CREATE INDEX /
-- CREATE SCHEMA without IF NOT EXISTS (static heuristic check).
--
-- Use your plugin's namespace as the PG schema name — it isolates
-- your tables and guarantees no collision with the core or other plugins.
-- ============================================================

CREATE SCHEMA IF NOT EXISTS hello;

-- Example table — replace with your real domain model.
CREATE TABLE IF NOT EXISTS hello.example_entity (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id   UUID NOT NULL,
    label        TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_hello_example_company
    ON hello.example_entity (company_id);

-- RLS — plugin-owned tables that hold per-company data MUST enable RLS
-- and add an is_company_member policy. The core does not enforce this
-- automatically; it's on the plugin author.
ALTER TABLE hello.example_entity ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS hello_example_select_member
    ON hello.example_entity;
CREATE POLICY hello_example_select_member
    ON hello.example_entity
    FOR SELECT
    USING (public.is_company_member(company_id));
