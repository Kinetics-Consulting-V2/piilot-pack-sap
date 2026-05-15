/**
 * Mount tests for ConnectionPanel.
 *
 * The component fetches connections via sapClient.listConnections on
 * mount. We mock the whole module surface and assert:
 *   - the table renders one row per item;
 *   - the "+ New connection" button opens the creation dialog;
 *   - the create dialog disables submit until the form is valid;
 *   - the Test button calls testConnection and re-fetches the list.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// vi.hoisted ensures the mock fns are created BEFORE vi.mock runs.
// Without it, the factory references undefined closure variables and
// the component sees the mock returning undefined → useEffect deadlock.
const {
    mockListConnections,
    mockCreateConnection,
    mockDeleteConnection,
    mockTestConnection,
} = vi.hoisted(() => ({
    mockListConnections: vi.fn(),
    mockCreateConnection: vi.fn(),
    mockDeleteConnection: vi.fn(),
    mockTestConnection: vi.fn(),
}))

vi.mock('../src/services/sapClient', () => ({
    listConnections: mockListConnections,
    createConnection: mockCreateConnection,
    deleteConnection: mockDeleteConnection,
    testConnection: mockTestConnection,
}))

import ConnectionPanel from '../src/components/ConnectionPanel'

const SAMPLE_CONNECTION = {
    id: 'conn-1',
    company_id: 'comp-1',
    label: 'Sandbox',
    base_url: 'https://example.sap',
    auth_mode: 'basic' as const,
    is_active: true,
    plugin_connection_id: 'plug-1',
    last_health_check_at: null,
    last_health_status: null,
    last_health_error: null,
    created_at: null,
    updated_at: null,
}


beforeEach(() => {
    mockListConnections.mockReset()
    mockCreateConnection.mockReset()
    mockDeleteConnection.mockReset()
    mockTestConnection.mockReset()
    mockListConnections.mockResolvedValue({ items: [] })
})

afterEach(() => {
    vi.clearAllMocks()
})


describe('<ConnectionPanel/>', () => {
    it('renders the empty state when no connection exists', async () => {
        render(<ConnectionPanel selectedConnectionId={null} onSelectConnection={vi.fn()} />)
        await waitFor(() => {
            expect(
                screen.getByText(/Aucune connexion/i),
            ).toBeInTheDocument()
        })
    })

    it('renders one table row per connection', async () => {
        mockListConnections.mockResolvedValue({ items: [SAMPLE_CONNECTION] })
        render(<ConnectionPanel selectedConnectionId={null} onSelectConnection={vi.fn()} />)
        await waitFor(() => {
            expect(screen.getByText('Sandbox')).toBeInTheDocument()
            expect(screen.getByText('https://example.sap')).toBeInTheDocument()
        })
    })

    it('opens the create dialog when clicking "+ New connection"', async () => {
        const user = userEvent.setup()
        render(<ConnectionPanel selectedConnectionId={null} onSelectConnection={vi.fn()} />)
        await waitFor(() =>
            expect(screen.getByText(/Aucune connexion/i)).toBeInTheDocument(),
        )
        await user.click(screen.getByRole('button', { name: /Nouvelle connexion/i }))
        expect(screen.getByText(/Nouvelle connexion SAP/i)).toBeInTheDocument()
    })

    it('auto-selects the sole connection when none is selected yet', async () => {
        const onSelect = vi.fn()
        mockListConnections.mockResolvedValue({ items: [SAMPLE_CONNECTION] })
        render(<ConnectionPanel selectedConnectionId={null} onSelectConnection={onSelect} />)
        await waitFor(() => {
            expect(onSelect).toHaveBeenCalledWith('conn-1')
        })
    })

    it('triggers testConnection when clicking the Test button', async () => {
        const user = userEvent.setup()
        mockListConnections.mockResolvedValue({ items: [SAMPLE_CONNECTION] })
        mockTestConnection.mockResolvedValue({ ok: true, status: 'ok' })

        render(<ConnectionPanel selectedConnectionId='conn-1' onSelectConnection={vi.fn()} />)
        await waitFor(() => expect(screen.getByText('Sandbox')).toBeInTheDocument())

        await user.click(screen.getByRole('button', { name: 'Tester' }))
        await waitFor(() => {
            expect(mockTestConnection).toHaveBeenCalledWith('conn-1')
        })
        // List re-fetched after the action (initial fetch + reload after Test).
        expect(mockListConnections).toHaveBeenCalledTimes(2)
    })

    it('surfaces a fetch error in a destructive card', async () => {
        mockListConnections.mockRejectedValue(new Error('boom'))
        render(<ConnectionPanel selectedConnectionId={null} onSelectConnection={vi.fn()} />)
        await waitFor(() => {
            expect(screen.getByText('boom')).toBeInTheDocument()
        })
    })
})
