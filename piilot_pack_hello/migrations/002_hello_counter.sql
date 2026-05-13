-- ============================================================
-- Migration: 002_hello_counter.sql
-- Plugin: hello
-- ============================================================
-- Adds a greet counter backing the repo.py example. Idempotent as
-- required by the Piilot plugin loader.
-- ============================================================

CREATE TABLE IF NOT EXISTS hello.greet_counter (
    company_id     UUID PRIMARY KEY,
    count          INTEGER NOT NULL DEFAULT 0,
    last_metadata  JSONB DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- RLS — same pattern as 001_init.sql: plugin-owned tables with per-company
-- data MUST enable RLS and gate SELECT on company membership.
ALTER TABLE hello.greet_counter ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS hello_greet_counter_select_member
    ON hello.greet_counter;
CREATE POLICY hello_greet_counter_select_member
    ON hello.greet_counter
    FOR SELECT
    USING (public.is_company_member(company_id));
