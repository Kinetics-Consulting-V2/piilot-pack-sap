/**
 * SAP S/4HANA Cloud connector module view.
 *
 * Shell that wires the 4 functional panels (Connection / Status /
 * Browser / Audit) into a shadcn ``Tabs`` layout. The active tab is
 * URL-driven via ``?tab=…`` so the back button and copy-paste keep
 * working across refreshes.
 *
 * Shared state — the currently selected connection id — lives here so
 * the Status / Browser / Audit panels can stay focused on the chosen
 * connection without re-fetching the list each time.
 *
 * Props documented in PLUGIN_DEVELOPMENT.md §20.
 */

import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'

import {
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
} from '@plugin-host/components/ui/tabs'
import type { ModuleViewProps } from '@plugin-host/lib/pluginUI'

import AuditLogPanel from './components/AuditLogPanel'
import ConnectionPanel from './components/ConnectionPanel'
import EntityBrowser from './components/EntityBrowser'
import StatusPanel from './components/StatusPanel'

const TAB_KEYS = ['connection', 'status', 'browser', 'audit'] as const
type TabKey = (typeof TAB_KEYS)[number]
const DEFAULT_TAB: TabKey = 'connection'

function parseTab(raw: string | null): TabKey {
    if (raw && (TAB_KEYS as readonly string[]).includes(raw)) {
        return raw as TabKey
    }
    return DEFAULT_TAB
}

export default function SAPConnectorView(_props: ModuleViewProps) {
    const { t } = useTranslation()
    const [searchParams, setSearchParams] = useSearchParams()
    const activeTab = parseTab(searchParams.get('tab'))

    // Cross-panel shared state — the currently selected connection.
    // Status / Browser / Audit need this, Connection writes it after
    // create / delete to keep the right row "active".
    const [selectedConnectionId, setSelectedConnectionId] = useState<string | null>(
        searchParams.get('connection_id'),
    )

    // Keep the connection_id query param in sync with state so a hard
    // refresh restores the selection.
    useEffect(() => {
        const current = searchParams.get('connection_id')
        if (selectedConnectionId === current) {
            return
        }
        const next = new URLSearchParams(searchParams)
        if (selectedConnectionId) {
            next.set('connection_id', selectedConnectionId)
        } else {
            next.delete('connection_id')
        }
        setSearchParams(next, { replace: true })
    }, [selectedConnectionId, searchParams, setSearchParams])

    const handleTabChange = (value: string) => {
        const next = new URLSearchParams(searchParams)
        next.set('tab', value)
        setSearchParams(next, { replace: true })
    }

    const tabs = useMemo(
        () => [
            { key: 'connection', label: t('sap.view.tabs.connection', 'Connexion') },
            { key: 'status', label: t('sap.view.tabs.status', 'Statut') },
            { key: 'browser', label: t('sap.view.tabs.browser', 'Explorateur') },
            { key: 'audit', label: t('sap.view.tabs.audit', 'Audit') },
        ] as const,
        [t],
    )

    return (
        <div className='space-y-4 p-6'>
            <div>
                <h1 className='text-2xl font-semibold'>
                    {t('sap.modules.connector.title', 'SAP S/4HANA Cloud')}
                </h1>
                <p className='mt-1 text-sm text-muted-foreground'>
                    {t(
                        'sap.modules.connector.description',
                        'Connectez-vous à votre instance SAP S/4HANA Cloud via OData.',
                    )}
                </p>
            </div>

            <Tabs value={activeTab} onValueChange={handleTabChange}>
                <TabsList>
                    {tabs.map((tab) => (
                        <TabsTrigger key={tab.key} value={tab.key}>
                            {tab.label}
                        </TabsTrigger>
                    ))}
                </TabsList>

                <TabsContent value='connection'>
                    <ConnectionPanel
                        selectedConnectionId={selectedConnectionId}
                        onSelectConnection={setSelectedConnectionId}
                    />
                </TabsContent>

                <TabsContent value='status'>
                    <StatusPanel connectionId={selectedConnectionId} />
                </TabsContent>

                <TabsContent value='browser'>
                    <EntityBrowser connectionId={selectedConnectionId} />
                </TabsContent>

                <TabsContent value='audit'>
                    <AuditLogPanel connectionId={selectedConnectionId} />
                </TabsContent>
            </Tabs>
        </div>
    )
}
