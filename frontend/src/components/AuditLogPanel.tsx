/**
 * Audit log panel — paginated list of OData calls for the selected
 * connection.
 *
 * Filters: status (everything / ok / error subset). The "Refresh"
 * button is the only manual refresh — there's no auto-poll because
 * a) the audit log is append-only and b) the user usually opens this
 * tab after running a query, not in advance.
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
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@plugin-host/components/ui/select'
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@plugin-host/components/ui/table'

import {
    type AuditEntry,
    type AuditStatus,
    listAudit,
} from '../services/sapClient'

interface Props {
    connectionId: string | null
}

const STATUS_FILTERS: { value: string; key: string; default: string }[] = [
    { value: '', key: 'sap.audit.filter_all', default: 'Tous' },
    { value: 'ok', key: 'sap.audit.filter_ok', default: 'OK' },
    {
        value: 'http_error',
        key: 'sap.audit.filter_http_error',
        default: 'Erreurs HTTP',
    },
    {
        value: 'validator_rejected',
        key: 'sap.audit.filter_validator_rejected',
        default: 'Refusés validator',
    },
    {
        value: 'auth_error',
        key: 'sap.audit.filter_auth_error',
        default: 'Erreurs auth',
    },
    {
        value: 'rate_limited',
        key: 'sap.audit.filter_rate_limited',
        default: 'Rate limited',
    },
]

export default function AuditLogPanel({ connectionId }: Props) {
    const { t } = useTranslation()
    const [items, setItems] = useState<AuditEntry[]>([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [statusFilter, setStatusFilter] = useState<string>('')

    const reload = useCallback(async () => {
        if (!connectionId) {
            setItems([])
            return
        }
        setLoading(true)
        setError(null)
        try {
            const data = await listAudit(connectionId, {
                limit: 100,
                status: statusFilter || undefined,
            })
            setItems(data.items)
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err))
        } finally {
            setLoading(false)
        }
    }, [connectionId, statusFilter])

    useEffect(() => {
        void reload()
    }, [reload])

    if (!connectionId) {
        return (
            <Card>
                <CardContent className='p-6 text-sm text-muted-foreground'>
                    {t(
                        'sap.audit.empty',
                        'Sélectionnez une connexion dans l’onglet Connexion.',
                    )}
                </CardContent>
            </Card>
        )
    }

    return (
        <Card>
            <CardHeader>
                <CardTitle className='flex items-center justify-between'>
                    <span>{t('sap.audit.title', "Journal d'audit OData")}</span>
                    <div className='flex gap-2'>
                        <Select
                            value={statusFilter || '__all__'}
                            onValueChange={(value) =>
                                setStatusFilter(value === '__all__' ? '' : value)
                            }
                        >
                            <SelectTrigger className='w-48'>
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {STATUS_FILTERS.map((opt) => (
                                    <SelectItem
                                        key={opt.value || '__all__'}
                                        value={opt.value || '__all__'}
                                    >
                                        {t(opt.key, opt.default)}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        <Button
                            size='sm'
                            variant='outline'
                            onClick={() => void reload()}
                            disabled={loading}
                        >
                            {t('sap.audit.refresh', 'Rafraîchir')}
                        </Button>
                    </div>
                </CardTitle>
            </CardHeader>
            <CardContent>
                {error && (
                    <p className='text-sm text-destructive'>{error}</p>
                )}
                {loading && items.length === 0 ? (
                    <p className='text-sm text-muted-foreground'>
                        {t('sap.audit.loading', 'Chargement…')}
                    </p>
                ) : items.length === 0 ? (
                    <p className='text-sm text-muted-foreground'>
                        {t(
                            'sap.audit.no_rows',
                            'Aucune requête enregistrée pour ces critères.',
                        )}
                    </p>
                ) : (
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>
                                    {t('sap.audit.col_time', 'Date')}
                                </TableHead>
                                <TableHead>
                                    {t('sap.audit.col_tool', 'Tool')}
                                </TableHead>
                                <TableHead>
                                    {t('sap.audit.col_entity', 'Entité')}
                                </TableHead>
                                <TableHead>
                                    {t('sap.audit.col_status', 'Statut')}
                                </TableHead>
                                <TableHead className='text-right'>
                                    {t('sap.audit.col_latency', 'Latence')}
                                </TableHead>
                                <TableHead className='text-right'>
                                    {t('sap.audit.col_result', 'Résultats')}
                                </TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {items.map((row) => (
                                <TableRow key={row.id}>
                                    <TableCell className='text-xs font-mono'>
                                        {row.created_at ?? '—'}
                                    </TableCell>
                                    <TableCell className='font-mono text-xs'>
                                        {row.tool_id ?? '—'}
                                    </TableCell>
                                    <TableCell>{row.entity_set ?? '—'}</TableCell>
                                    <TableCell>
                                        <StatusBadge status={row.status} />
                                        {row.error && (
                                            <p className='text-xs text-destructive mt-1'>
                                                {row.error}
                                            </p>
                                        )}
                                    </TableCell>
                                    <TableCell className='text-right text-xs'>
                                        {row.latency_ms !== null
                                            ? `${row.latency_ms} ms`
                                            : '—'}
                                    </TableCell>
                                    <TableCell className='text-right text-xs'>
                                        {row.result_count ?? '—'}
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                )}
            </CardContent>
        </Card>
    )
}

function StatusBadge({ status }: { status: AuditStatus }) {
    if (status === 'ok') {
        return <Badge className='bg-green-600 text-white'>ok</Badge>
    }
    if (status === 'rate_limited' || status === 'timeout') {
        return (
            <Badge className='bg-amber-500 text-white'>{status}</Badge>
        )
    }
    return <Badge variant='destructive'>{status}</Badge>
}
