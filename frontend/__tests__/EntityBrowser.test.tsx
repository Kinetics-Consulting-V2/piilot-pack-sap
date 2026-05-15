/**
 * Mount tests for EntityBrowser.
 *
 * Covers the cache-driven entity list + the substring filter. The
 * detail dialog (which fetches via getEntity on click) is exercised
 * with a single happy-path test.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { mockListEntities, mockGetEntity } = vi.hoisted(() => ({
    mockListEntities: vi.fn(),
    mockGetEntity: vi.fn(),
}))

vi.mock('../src/services/sapClient', () => ({
    listEntities: mockListEntities,
    getEntity: mockGetEntity,
}))

import EntityBrowser from '../src/components/EntityBrowser'


const SAMPLE_ENTITIES = [
    {
        entity_set_name: 'A_BusinessPartner',
        service_path: '/sap',
        label: 'Business Partner',
        description: 'BP master data',
        last_synced_at: '2026-05-15T08:00:00Z',
    },
    {
        entity_set_name: 'A_BillingDocument',
        service_path: '/sap',
        label: 'Billing Document',
        description: 'Invoice header table',
        last_synced_at: '2026-05-15T08:00:00Z',
    },
    {
        entity_set_name: 'A_PurchaseOrder',
        service_path: '/sap',
        label: 'Purchase Order',
        description: 'PO header table',
        last_synced_at: '2026-05-15T08:00:00Z',
    },
]


beforeEach(() => {
    mockListEntities.mockReset()
    mockGetEntity.mockReset()
    mockListEntities.mockResolvedValue({ items: SAMPLE_ENTITIES })
})

afterEach(() => {
    vi.clearAllMocks()
})


describe('<EntityBrowser/>', () => {
    it('renders the empty state when no connection is selected', () => {
        render(<EntityBrowser connectionId={null} />)
        expect(
            screen.getByText(/Sélectionnez une connexion/i),
        ).toBeInTheDocument()
        expect(mockListEntities).not.toHaveBeenCalled()
    })

    it('renders every entity row when the cache has items', async () => {
        render(<EntityBrowser connectionId='conn-1' />)
        await waitFor(() => {
            expect(screen.getByText('A_BusinessPartner')).toBeInTheDocument()
            expect(screen.getByText('A_BillingDocument')).toBeInTheDocument()
            expect(screen.getByText('A_PurchaseOrder')).toBeInTheDocument()
        })
    })

    it('substring-filters the list as the user types', async () => {
        const user = userEvent.setup()
        render(<EntityBrowser connectionId='conn-1' />)
        await waitFor(() => {
            expect(screen.getByText('A_BusinessPartner')).toBeInTheDocument()
        })

        const search = screen.getByPlaceholderText(/Rechercher/i)
        await user.type(search, 'invoice')

        await waitFor(() => {
            expect(screen.getByText('A_BillingDocument')).toBeInTheDocument()
            expect(screen.queryByText('A_PurchaseOrder')).not.toBeInTheDocument()
            expect(
                screen.queryByText('A_BusinessPartner'),
            ).not.toBeInTheDocument()
        })
    })

    it('opens the detail dialog and fetches the entity on click', async () => {
        const user = userEvent.setup()
        mockGetEntity.mockResolvedValue({
            entity_set_name: 'A_BusinessPartner',
            service_path: '/sap',
            label: 'Business Partner',
            description: 'BP master data',
            last_synced_at: '2026-05-15T08:00:00Z',
            payload: {
                name: 'A_BusinessPartner',
                entity_type: 'ns.A_BusinessPartnerType',
                key: ['BusinessPartner'],
                properties: [
                    {
                        name: 'BusinessPartner',
                        type: 'Edm.String',
                        nullable: false,
                        max_length: 10,
                        precision: null,
                        scale: null,
                        sap_label: 'BP ID',
                        sap_filterable: true,
                        sap_sortable: true,
                        sap_creatable: false,
                        sap_updatable: false,
                        sap_semantics: null,
                    },
                ],
                navigations: [],
            },
        })
        render(<EntityBrowser connectionId='conn-1' />)
        await waitFor(() =>
            expect(screen.getByText('A_BusinessPartner')).toBeInTheDocument(),
        )

        await user.click(screen.getByText('A_BusinessPartner'))
        await waitFor(() => {
            expect(mockGetEntity).toHaveBeenCalledWith(
                'conn-1',
                'A_BusinessPartner',
            )
        })
        // Property table populated inside the dialog.
        await waitFor(() => {
            expect(screen.getByText('BP ID')).toBeInTheDocument()
        })
    })

    it('surfaces a fetch error inline', async () => {
        mockListEntities.mockRejectedValue(new Error('cache down'))
        render(<EntityBrowser connectionId='conn-1' />)
        await waitFor(() => {
            expect(screen.getByText('cache down')).toBeInTheDocument()
        })
    })
})
