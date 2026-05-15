/**
 * Status panel — health of the currently selected SAP connection.
 *
 * Renders nothing useful when no connection is selected — the user is
 * nudged to go back to the Connection tab.
 *
 * Two actions:
 *   - **Test**     reach the SAP ``$metadata`` endpoint without
 *                  persisting. Reports OK / error inline.
 *   - **Sync**     refresh ``schema_snapshot`` and the plugin KB.
 *                  Heavier — disables the button while in flight.
 */

import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Badge } from '@plugin-host/components/ui/badge'
import { Button } from '@plugin-host/components/ui/button'
import {
    Card,
    CardContent,
    CardHeader,
    CardTitle,
} from '@plugin-host/components/ui/card'

import {
    type EntitySummary,
    type SAPConnection,
    type SyncResult,
    type TestConnectionResult,
    getConnection,
    listEntities,
    syncConnection,
    testConnection,
} from '../services/sapClient'

interface Props {
    connectionId: string | null
}

export default function StatusPanel({ connectionId }: Props) {
    const { t } = useTranslation()
    const [connection, setConnection] = useState<SAPConnection | null>(null)
    const [entityCount, setEntityCount] = useState<number | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [testResult, setTestResult] = useState<TestConnectionResult | null>(null)
    const [syncResult, setSyncResult] = useState<SyncResult | null>(null)
    const [busy, setBusy] = useState<'test' | 'sync' | null>(null)

    const reload = useCallback(async () => {
        if (!connectionId) {
            setConnection(null)
            setEntityCount(null)
            return
        }
        setLoading(true)
        setError(null)
        try {
            const [conn, entities] = await Promise.all([
                getConnection(connectionId),
                listEntities(connectionId, { limit: 10_000 }).catch(
                    () => ({ items: [] as EntitySummary[] }),
                ),
            ])
            setConnection(conn)
            setEntityCount((entities?.items ?? []).length)
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err))
        } finally {
            setLoading(false)
        }
    }, [connectionId])

    useEffect(() => {
        setTestResult(null)
        setSyncResult(null)
        void reload()
    }, [reload])

    if (!connectionId) {
        return (
            <Card>
                <CardContent className='p-6 text-sm text-muted-foreground'>
                    {t(
                        'sap.status.empty',
                        'Sélectionnez une connexion dans l’onglet Connexion.',
                    )}
                </CardContent>
            </Card>
        )
    }

    const handleTest = async () => {
        setBusy('test')
        setError(null)
        try {
            const result = await testConnection(connectionId)
            setTestResult(result)
            await reload()
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err))
        } finally {
            setBusy(null)
        }
    }

    const handleSync = async () => {
        setBusy('sync')
        setError(null)
        try {
            const result = await syncConnection(connectionId)
            setSyncResult(result)
            await reload()
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err))
        } finally {
            setBusy(null)
        }
    }

    return (
        <div className='space-y-4'>
            {loading && !connection && (
                <p className='text-sm text-muted-foreground'>
                    {t('sap.status.loading', 'Chargement…')}
                </p>
            )}

            {connection && (
                <Card>
                    <CardHeader>
                        <CardTitle className='flex justify-between'>
                            <span>{connection.label}</span>
                            <HealthBadge connection={connection} />
                        </CardTitle>
                    </CardHeader>
                    <CardContent className='space-y-3 text-sm'>
                        <KeyValue
                            label={t('sap.status.base_url', 'URL OData')}
                            value={connection.base_url}
                            mono
                        />
                        <KeyValue
                            label={t('sap.status.auth_mode', 'Authentification')}
                            value={connection.auth_mode}
                        />
                        <KeyValue
                            label={t(
                                'sap.status.last_health_check_at',
                                'Dernier test',
                            )}
                            value={connection.last_health_check_at ?? '—'}
                        />
                        <KeyValue
                            label={t(
                                'sap.status.entity_set_count',
                                "EntitySets dans le cache",
                            )}
                            value={
                                entityCount === null
                                    ? '—'
                                    : String(entityCount)
                            }
                        />
                        {connection.last_health_error && (
                            <p className='text-xs text-destructive'>
                                {connection.last_health_error}
                            </p>
                        )}
                    </CardContent>
                </Card>
            )}

            <div className='flex gap-2'>
                <Button
                    onClick={() => void handleTest()}
                    disabled={busy !== null}
                >
                    {busy === 'test'
                        ? t('sap.status.testing', 'Test en cours…')
                        : t('sap.status.test', 'Tester la connexion')}
                </Button>
                <Button
                    onClick={() => void handleSync()}
                    disabled={busy !== null}
                    variant='secondary'
                >
                    {busy === 'sync'
                        ? t('sap.status.syncing', 'Sync en cours…')
                        : t('sap.status.sync', 'Re-synchroniser $metadata')}
                </Button>
            </div>

            {testResult && <TestResultCard result={testResult} />}
            {syncResult && <SyncResultCard result={syncResult} />}
            {error && (
                <Card className='border-destructive'>
                    <CardContent className='p-4 text-sm text-destructive'>
                        {error}
                    </CardContent>
                </Card>
            )}
        </div>
    )
}

function KeyValue({
    label,
    value,
    mono,
}: {
    label: string
    value: string
    mono?: boolean
}) {
    return (
        <div className='flex gap-2'>
            <span className='font-medium min-w-[160px]'>{label} :</span>
            <span className={mono ? 'font-mono text-xs' : ''}>{value}</span>
        </div>
    )
}

function HealthBadge({ connection }: { connection: SAPConnection }) {
    const { t } = useTranslation()
    if (connection.last_health_status === 'ok') {
        return (
            <Badge className='bg-green-600 text-white'>
                {t('sap.status.health_ok', 'OK')}
            </Badge>
        )
    }
    if (connection.last_health_status === 'error') {
        return (
            <Badge variant='destructive'>
                {t('sap.status.health_error', 'Erreur')}
            </Badge>
        )
    }
    return (
        <Badge variant='outline'>
            {t('sap.status.health_unknown', 'Non testé')}
        </Badge>
    )
}

function TestResultCard({ result }: { result: TestConnectionResult }) {
    const { t } = useTranslation()
    return (
        <Card className={result.ok ? 'border-green-600' : 'border-destructive'}>
            <CardContent className='p-4 text-sm space-y-1'>
                <p className='font-medium'>
                    {result.ok
                        ? t('sap.status.test_ok', 'Connexion OK')
                        : t('sap.status.test_failed', 'Échec du test')}
                </p>
                {result.entity_set_count !== undefined && (
                    <p className='text-muted-foreground'>
                        {t(
                            'sap.status.test_entity_count',
                            '{{count}} EntitySets exposées (OData {{version}})',
                            {
                                count: result.entity_set_count,
                                version: result.odata_version ?? '?',
                            },
                        )}
                    </p>
                )}
                {result.error && (
                    <p className='text-destructive'>{result.error}</p>
                )}
            </CardContent>
        </Card>
    )
}

function SyncResultCard({ result }: { result: SyncResult }) {
    const { t } = useTranslation()
    return (
        <Card className='border-green-600'>
            <CardContent className='p-4 text-sm space-y-1'>
                <p className='font-medium'>
                    {t('sap.status.sync_done', 'Synchronisation terminée')}
                </p>
                <p className='text-muted-foreground'>
                    {t(
                        'sap.status.sync_summary',
                        '{{rows}} entités persistées · KB {{kbId}} ({{inserted}} ajoutées / {{updated}} mises à jour)',
                        {
                            rows: result.snapshot_rows,
                            kbId: result.kb.kb_id,
                            inserted: result.kb.inserted,
                            updated: result.kb.updated,
                        },
                    )}
                </p>
            </CardContent>
        </Card>
    )
}
