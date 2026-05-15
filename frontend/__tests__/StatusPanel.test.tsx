/**
 * Mount tests for StatusPanel.
 *
 * Verifies that:
 *   - the empty state shows when no connection is selected;
 *   - the card renders connection metadata after mount;
 *   - Test / Sync buttons call the right sapClient methods;
 *   - the sync result is surfaced inline.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const {
    mockGetConnection,
    mockListEntities,
    mockTestConnection,
    mockSyncConnection,
} = vi.hoisted(() => ({
    mockGetConnection: vi.fn(),
    mockListEntities: vi.fn(),
    mockTestConnection: vi.fn(),
    mockSyncConnection: vi.fn(),
}))

vi.mock('../src/services/sapClient', () => ({
    getConnection: mockGetConnection,
    listEntities: mockListEntities,
    testConnection: mockTestConnection,
    syncConnection: mockSyncConnection,
}))

import StatusPanel from '../src/components/StatusPanel'

const SAMPLE_CONNECTION = {
    id: 'conn-1',
    company_id: 'comp-1',
    label: 'Sandbox',
    base_url: 'https://example.sap',
    auth_mode: 'basic' as const,
    is_active: true,
    plugin_connection_id: 'plug-1',
    last_health_check_at: '2026-05-15T08:00:00Z',
    last_health_status: 'ok',
    last_health_error: null,
    created_at: null,
    updated_at: null,
}


beforeEach(() => {
    mockGetConnection.mockReset()
    mockListEntities.mockReset()
    mockTestConnection.mockReset()
    mockSyncConnection.mockReset()
    mockGetConnection.mockResolvedValue(SAMPLE_CONNECTION)
    mockListEntities.mockResolvedValue({ items: [] })
})

afterEach(() => {
    vi.clearAllMocks()
})


describe('<StatusPanel/>', () => {
    it('renders the empty state when no connection is selected', () => {
        render(<StatusPanel connectionId={null} />)
        expect(
            screen.getByText(/Sélectionnez une connexion/i),
        ).toBeInTheDocument()
        expect(mockGetConnection).not.toHaveBeenCalled()
    })

    it('renders the connection metadata after mount', async () => {
        render(<StatusPanel connectionId='conn-1' />)
        await waitFor(() => {
            expect(screen.getByText('Sandbox')).toBeInTheDocument()
            expect(screen.getByText('https://example.sap')).toBeInTheDocument()
        })
    })

    it('calls testConnection when clicking Test', async () => {
        const user = userEvent.setup()
        mockTestConnection.mockResolvedValue({
            ok: true,
            status: 'ok',
            entity_set_count: 65,
            odata_version: 'v2',
        })
        render(<StatusPanel connectionId='conn-1' />)
        await waitFor(() => expect(screen.getByText('Sandbox')).toBeInTheDocument())

        await user.click(screen.getByRole('button', { name: /Tester la connexion/i }))
        await waitFor(() => {
            expect(mockTestConnection).toHaveBeenCalledWith('conn-1')
        })
        // Test result card visible.
        await waitFor(() => {
            expect(screen.getByText(/Connexion OK/i)).toBeInTheDocument()
        })
    })

    it('calls syncConnection when clicking Sync', async () => {
        const user = userEvent.setup()
        mockSyncConnection.mockResolvedValue({
            ok: true,
            entity_set_count: 65,
            snapshot_rows: 65,
            kb: {
                kb_id: 'kb-1',
                inserted: 65,
                updated: 0,
                total: 65,
                created: true,
            },
        })
        render(<StatusPanel connectionId='conn-1' />)
        await waitFor(() => expect(screen.getByText('Sandbox')).toBeInTheDocument())

        await user.click(screen.getByRole('button', { name: /Re-synchroniser/i }))
        await waitFor(() => {
            expect(mockSyncConnection).toHaveBeenCalledWith('conn-1')
        })
        // Sync summary card visible.
        await waitFor(() => {
            expect(
                screen.getByText(/Synchronisation terminée/i),
            ).toBeInTheDocument()
        })
    })

    it('reports a sync error inline', async () => {
        const user = userEvent.setup()
        mockSyncConnection.mockRejectedValue(new Error('sap down'))
        render(<StatusPanel connectionId='conn-1' />)
        await waitFor(() => expect(screen.getByText('Sandbox')).toBeInTheDocument())

        await user.click(screen.getByRole('button', { name: /Re-synchroniser/i }))
        await waitFor(() => {
            expect(screen.getByText('sap down')).toBeInTheDocument()
        })
    })
})
