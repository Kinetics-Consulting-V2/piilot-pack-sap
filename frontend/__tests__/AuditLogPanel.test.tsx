/**
 * Mount tests for AuditLogPanel.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { mockListAudit } = vi.hoisted(() => ({
    mockListAudit: vi.fn(),
}))

vi.mock('../src/services/sapClient', () => ({
    listAudit: mockListAudit,
}))

import AuditLogPanel from '../src/components/AuditLogPanel'

const SAMPLE_AUDIT = [
    {
        id: 'a1',
        tool_id: 'sap.select',
        entity_set: 'A_BusinessPartner',
        odata_url: '/A_BusinessPartner?$top=10',
        status: 'ok' as const,
        http_status: 200,
        latency_ms: 142,
        result_count: 10,
        error: null,
        created_at: '2026-05-15T09:00:00Z',
    },
    {
        id: 'a2',
        tool_id: 'sap.count',
        entity_set: 'A_BusinessPartner',
        odata_url: '/A_BusinessPartner/$count',
        status: 'http_error' as const,
        http_status: 500,
        latency_ms: 300,
        result_count: null,
        error: 'boom',
        created_at: '2026-05-15T08:55:00Z',
    },
]


beforeEach(() => {
    mockListAudit.mockReset()
    mockListAudit.mockResolvedValue({ items: SAMPLE_AUDIT })
})

afterEach(() => {
    vi.clearAllMocks()
})


describe('<AuditLogPanel/>', () => {
    it('renders the empty state when no connection is selected', () => {
        render(<AuditLogPanel connectionId={null} />)
        expect(
            screen.getByText(/Sélectionnez une connexion/i),
        ).toBeInTheDocument()
        expect(mockListAudit).not.toHaveBeenCalled()
    })

    it('renders one row per audit entry', async () => {
        render(<AuditLogPanel connectionId='conn-1' />)
        await waitFor(() => {
            expect(screen.getByText('sap.select')).toBeInTheDocument()
            expect(screen.getByText('sap.count')).toBeInTheDocument()
        })
        // Error text shows up under the failed row.
        expect(screen.getByText('boom')).toBeInTheDocument()
    })

    it('refetches on Refresh button click', async () => {
        const user = userEvent.setup()
        render(<AuditLogPanel connectionId='conn-1' />)
        await waitFor(() =>
            expect(screen.getByText('sap.select')).toBeInTheDocument(),
        )
        expect(mockListAudit).toHaveBeenCalledTimes(1)

        await user.click(screen.getByRole('button', { name: /Rafraîchir/i }))
        await waitFor(() => {
            expect(mockListAudit).toHaveBeenCalledTimes(2)
        })
    })

    it('passes the connection id and the no-status filter to sapClient', async () => {
        render(<AuditLogPanel connectionId='conn-1' />)
        await waitFor(() =>
            expect(mockListAudit).toHaveBeenCalled(),
        )
        const call = mockListAudit.mock.calls[0]
        expect(call[0]).toBe('conn-1')
        expect(call[1]).toMatchObject({ limit: 100, status: undefined })
    })

    it('shows the empty-state message when the API returns no rows', async () => {
        mockListAudit.mockResolvedValue({ items: [] })
        render(<AuditLogPanel connectionId='conn-1' />)
        await waitFor(() => {
            expect(
                screen.getByText(/Aucune requête enregistrée/i),
            ).toBeInTheDocument()
        })
    })

    it('surfaces a fetch error', async () => {
        mockListAudit.mockRejectedValue(new Error('audit down'))
        render(<AuditLogPanel connectionId='conn-1' />)
        await waitFor(() => {
            expect(screen.getByText('audit down')).toBeInTheDocument()
        })
    })
})
