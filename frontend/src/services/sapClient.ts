/**
 * Typed wrapper over the SAP plugin's HTTP routes (mounted under
 * ``/plugins/sap/*``). Every method delegates to the host's
 * ``apiFetch`` which:
 *
 *   - injects the auth header
 *   - injects ``X-Company-Id`` from the active espace context
 *     (required by the plugin_gate middleware)
 *   - throws on non-2xx with the response body attached
 *
 * Components import the named functions directly rather than
 * instantiating a class — keeps mocking trivial in vitest.
 */

import { apiFetch } from '@plugin-host/services/httpClient'

const ROOT = '/plugins/sap'

// ---------------------------------------------------------------------------
// Types — mirror the Pydantic schemas in routes.py
// ---------------------------------------------------------------------------

export type AuthMode = 'basic' | 'oauth_client_credentials'

export interface SAPConnection {
    id: string
    company_id: string
    label: string
    base_url: string
    auth_mode: AuthMode
    is_active: boolean
    plugin_connection_id: string | null
    last_health_check_at: string | null
    last_health_status: string | null
    last_health_error: string | null
    created_at: string | null
    updated_at: string | null
}

export interface ConnectionCredentialsPayload {
    basic_username?: string
    basic_password?: string
    oauth_token_url?: string
    oauth_client_id?: string
    oauth_client_secret?: string
    oauth_scope?: string
}

export interface ConnectionCreatePayload {
    label: string
    base_url: string
    auth_mode: AuthMode
    credentials: ConnectionCredentialsPayload
}

export interface ConnectionUpdatePayload {
    label?: string
    base_url?: string
    auth_mode?: AuthMode
    is_active?: boolean
    credentials?: ConnectionCredentialsPayload
}

export interface PluginHealth {
    plugin: 'sap'
    version: string
    company_id: string
    user_id: string
    role: string
    connections_total: number
    connections_active: number
}

export interface TestConnectionResult {
    ok: boolean
    status: 'ok' | 'http_error' | 'unreachable' | 'parse_error'
    http_status?: number
    entity_set_count?: number
    odata_version?: 'v2' | 'v4'
    error?: string
}

export interface SyncResult {
    ok: boolean
    entity_set_count: number
    snapshot_rows: number
    kb: {
        kb_id: string
        inserted: number
        updated: number
        total: number
        created: boolean
    }
}

export interface EntitySummary {
    entity_set_name: string
    service_path: string | null
    label: string | null
    description: string | null
    last_synced_at: string | null
}

export interface EntityProperty {
    name: string
    type: string
    nullable: boolean
    max_length: number | null
    precision: number | null
    scale: number | null
    sap_label: string | null
    sap_filterable: boolean
    sap_sortable: boolean
    sap_creatable: boolean
    sap_updatable: boolean
    sap_semantics: string | null
}

export interface EntityNavigation {
    name: string
    target_entity_type: string | null
    multiplicity: '1' | '0..1' | '*' | null
    relationship: string | null
    from_role: string | null
    to_role: string | null
}

export interface EntityDetail extends EntitySummary {
    payload: {
        name?: string
        entity_type?: string
        key?: string[]
        properties?: EntityProperty[]
        navigations?: EntityNavigation[]
    }
}

export type AuditStatus =
    | 'ok'
    | 'validator_rejected'
    | 'auth_error'
    | 'http_error'
    | 'rate_limited'
    | 'timeout'
    | 'parse_error'
    | 'resolution_error'
    | 'session_unknown'
    | 'forbidden'
    | 'not_found'

export interface AuditEntry {
    id: string
    tool_id: string | null
    entity_set: string | null
    odata_url: string | null
    status: AuditStatus
    http_status: number | null
    latency_ms: number | null
    result_count: number | null
    error: string | null
    created_at: string | null
}

// ---------------------------------------------------------------------------
// API methods
// ---------------------------------------------------------------------------

export async function getHealth(): Promise<PluginHealth> {
    return apiFetch(`${ROOT}/health`, { method: 'GET' })
}

export async function listConnections(
    options: { active_only?: boolean } = {},
): Promise<{ items: SAPConnection[] }> {
    const qs = options.active_only ? '?active_only=true' : ''
    return apiFetch(`${ROOT}/connections${qs}`, { method: 'GET' })
}

export async function getConnection(connectionId: string): Promise<SAPConnection> {
    return apiFetch(`${ROOT}/connections/${connectionId}`, { method: 'GET' })
}

export async function createConnection(
    payload: ConnectionCreatePayload,
): Promise<SAPConnection> {
    return apiFetch(`${ROOT}/connections`, {
        method: 'POST',
        body: JSON.stringify(payload),
    })
}

export async function updateConnection(
    connectionId: string,
    payload: ConnectionUpdatePayload,
): Promise<SAPConnection> {
    return apiFetch(`${ROOT}/connections/${connectionId}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
    })
}

export async function deleteConnection(connectionId: string): Promise<void> {
    await apiFetch(`${ROOT}/connections/${connectionId}`, {
        method: 'DELETE',
    })
}

export async function testConnection(
    connectionId: string,
): Promise<TestConnectionResult> {
    return apiFetch(`${ROOT}/connections/${connectionId}/test`, {
        method: 'POST',
    })
}

export async function syncConnection(connectionId: string): Promise<SyncResult> {
    return apiFetch(`${ROOT}/connections/${connectionId}/sync`, {
        method: 'POST',
    })
}

export async function listEntities(
    connectionId: string,
    options: { limit?: number } = {},
): Promise<{ items: EntitySummary[] }> {
    const qs = options.limit ? `?limit=${options.limit}` : ''
    return apiFetch(`${ROOT}/connections/${connectionId}/entities${qs}`, {
        method: 'GET',
    })
}

export async function getEntity(
    connectionId: string,
    entityName: string,
): Promise<EntityDetail> {
    return apiFetch(
        `${ROOT}/connections/${connectionId}/entities/${encodeURIComponent(entityName)}`,
        { method: 'GET' },
    )
}

export async function listAudit(
    connectionId: string,
    options: { limit?: number; status?: string } = {},
): Promise<{ items: AuditEntry[] }> {
    const params = new URLSearchParams()
    if (options.limit !== undefined) params.set('limit', String(options.limit))
    if (options.status) params.set('status', options.status)
    const qs = params.toString() ? `?${params.toString()}` : ''
    return apiFetch(`${ROOT}/connections/${connectionId}/audit${qs}`, {
        method: 'GET',
    })
}
