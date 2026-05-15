/**
 * Tests for ``src/services/sapClient.ts`` — URL construction + payload
 * shape verification.
 *
 * ``apiFetch`` from ``@plugin-host/services/httpClient`` is mocked
 * globally so the test never touches a real network. We assert the
 * exact path + method + body the client builds for each route.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiFetchMock = vi.fn()

vi.mock('@plugin-host/services/httpClient', () => ({
    apiFetch: apiFetchMock,
}))

beforeEach(() => {
    apiFetchMock.mockReset()
    apiFetchMock.mockResolvedValue({ items: [] })
})

describe('sapClient — URL construction', () => {
    it('getHealth hits /plugins/sap/health', async () => {
        const { getHealth } = await import('../src/services/sapClient')
        await getHealth()
        expect(apiFetchMock).toHaveBeenCalledWith('/plugins/sap/health', {
            method: 'GET',
        })
    })

    it('listConnections without filter omits the active_only flag', async () => {
        const { listConnections } = await import('../src/services/sapClient')
        await listConnections()
        expect(apiFetchMock).toHaveBeenCalledWith('/plugins/sap/connections', {
            method: 'GET',
        })
    })

    it('listConnections with active_only appends the query string', async () => {
        const { listConnections } = await import('../src/services/sapClient')
        await listConnections({ active_only: true })
        expect(apiFetchMock).toHaveBeenCalledWith(
            '/plugins/sap/connections?active_only=true',
            { method: 'GET' },
        )
    })

    it('getConnection embeds the id in the path', async () => {
        const { getConnection } = await import('../src/services/sapClient')
        await getConnection('conn-1')
        expect(apiFetchMock).toHaveBeenCalledWith(
            '/plugins/sap/connections/conn-1',
            { method: 'GET' },
        )
    })

    it('createConnection POSTs the payload as JSON', async () => {
        const { createConnection } = await import('../src/services/sapClient')
        await createConnection({
            label: 'Sandbox',
            base_url: 'https://x.sap/',
            auth_mode: 'basic',
            credentials: { basic_username: 'u', basic_password: 'p' },
        })
        const [path, options] = apiFetchMock.mock.calls[0]
        expect(path).toBe('/plugins/sap/connections')
        expect(options.method).toBe('POST')
        const body = JSON.parse(options.body as string)
        expect(body.label).toBe('Sandbox')
        expect(body.auth_mode).toBe('basic')
        expect(body.credentials.basic_username).toBe('u')
    })

    it('updateConnection uses PATCH', async () => {
        const { updateConnection } = await import('../src/services/sapClient')
        await updateConnection('conn-1', { label: 'Renamed' })
        const [path, options] = apiFetchMock.mock.calls[0]
        expect(path).toBe('/plugins/sap/connections/conn-1')
        expect(options.method).toBe('PATCH')
        expect(JSON.parse(options.body as string)).toEqual({ label: 'Renamed' })
    })

    it('deleteConnection uses DELETE', async () => {
        const { deleteConnection } = await import('../src/services/sapClient')
        await deleteConnection('conn-1')
        expect(apiFetchMock).toHaveBeenCalledWith(
            '/plugins/sap/connections/conn-1',
            { method: 'DELETE' },
        )
    })

    it('testConnection POSTs to /test without a body', async () => {
        const { testConnection } = await import('../src/services/sapClient')
        await testConnection('conn-1')
        expect(apiFetchMock).toHaveBeenCalledWith(
            '/plugins/sap/connections/conn-1/test',
            { method: 'POST' },
        )
    })

    it('syncConnection POSTs to /sync without a body', async () => {
        const { syncConnection } = await import('../src/services/sapClient')
        await syncConnection('conn-1')
        expect(apiFetchMock).toHaveBeenCalledWith(
            '/plugins/sap/connections/conn-1/sync',
            { method: 'POST' },
        )
    })

    it('listEntities respects the limit option', async () => {
        const { listEntities } = await import('../src/services/sapClient')
        await listEntities('conn-1', { limit: 500 })
        expect(apiFetchMock).toHaveBeenCalledWith(
            '/plugins/sap/connections/conn-1/entities?limit=500',
            { method: 'GET' },
        )
    })

    it('listEntities omits the query string when no options', async () => {
        const { listEntities } = await import('../src/services/sapClient')
        await listEntities('conn-1')
        expect(apiFetchMock).toHaveBeenCalledWith(
            '/plugins/sap/connections/conn-1/entities',
            { method: 'GET' },
        )
    })

    it('getEntity URL-encodes the entity name', async () => {
        const { getEntity } = await import('../src/services/sapClient')
        await getEntity('conn-1', 'A_BusinessPartner')
        expect(apiFetchMock).toHaveBeenCalledWith(
            '/plugins/sap/connections/conn-1/entities/A_BusinessPartner',
            { method: 'GET' },
        )
    })

    it('getEntity escapes special characters in the entity name', async () => {
        const { getEntity } = await import('../src/services/sapClient')
        await getEntity('conn-1', 'My/Weird Name')
        const [path] = apiFetchMock.mock.calls[0]
        expect(path).toBe(
            '/plugins/sap/connections/conn-1/entities/My%2FWeird%20Name',
        )
    })

    it('listAudit builds a status query string when provided', async () => {
        const { listAudit } = await import('../src/services/sapClient')
        await listAudit('conn-1', { limit: 50, status: 'http_error' })
        const [path] = apiFetchMock.mock.calls[0]
        expect(path).toContain('limit=50')
        expect(path).toContain('status=http_error')
    })

    it('listAudit without filters keeps the URL clean', async () => {
        const { listAudit } = await import('../src/services/sapClient')
        await listAudit('conn-1')
        expect(apiFetchMock).toHaveBeenCalledWith(
            '/plugins/sap/connections/conn-1/audit',
            { method: 'GET' },
        )
    })
})

describe('sapClient — response passthrough', () => {
    it('returns whatever apiFetch returns (typed surface only)', async () => {
        apiFetchMock.mockResolvedValueOnce({
            items: [{ id: 'conn-1', label: 'Sandbox' }],
        })
        const { listConnections } = await import('../src/services/sapClient')
        const result = await listConnections()
        expect(result.items).toHaveLength(1)
        expect(result.items[0].id).toBe('conn-1')
    })

    it('propagates apiFetch rejections', async () => {
        apiFetchMock.mockRejectedValueOnce(new Error('network down'))
        const { listConnections } = await import('../src/services/sapClient')
        await expect(listConnections()).rejects.toThrow('network down')
    })
})
