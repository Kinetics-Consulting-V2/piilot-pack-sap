/**
 * Entity browser — searchable list of cached SAP EntitySets.
 *
 * Loads the snapshot once via ``listEntities`` (up to 10k rows by
 * default, plenty for any S/4HANA service) and filters client-side
 * as the user types. Clicking a row opens a dialog that fetches the
 * full ``payload`` (props + navigations) via ``getEntity``.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Badge } from '@plugin-host/components/ui/badge'
import {
    Card,
    CardContent,
    CardHeader,
    CardTitle,
} from '@plugin-host/components/ui/card'
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from '@plugin-host/components/ui/dialog'
import { Input } from '@plugin-host/components/ui/input'
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@plugin-host/components/ui/table'

import {
    type EntityDetail,
    type EntitySummary,
    getEntity,
    listEntities,
} from '../services/sapClient'

interface Props {
    connectionId: string | null
}

const MAX_RENDER = 200

export default function EntityBrowser({ connectionId }: Props) {
    const { t } = useTranslation()
    const [items, setItems] = useState<EntitySummary[]>([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [query, setQuery] = useState('')
    const [detail, setDetail] = useState<EntityDetail | null>(null)
    const [detailLoading, setDetailLoading] = useState(false)

    const reload = useCallback(async () => {
        if (!connectionId) {
            setItems([])
            return
        }
        setLoading(true)
        setError(null)
        try {
            const data = await listEntities(connectionId, { limit: 10_000 })
            setItems(data.items)
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err))
        } finally {
            setLoading(false)
        }
    }, [connectionId])

    useEffect(() => {
        void reload()
    }, [reload])

    const filtered = useMemo(() => {
        const needle = query.trim().toLowerCase()
        if (!needle) return items.slice(0, MAX_RENDER)
        return items
            .filter((row) => {
                const haystack = [
                    row.entity_set_name,
                    row.label ?? '',
                    row.description ?? '',
                ]
                    .join(' ')
                    .toLowerCase()
                return haystack.includes(needle)
            })
            .slice(0, MAX_RENDER)
    }, [items, query])

    if (!connectionId) {
        return (
            <Card>
                <CardContent className='p-6 text-sm text-muted-foreground'>
                    {t(
                        'sap.browser.empty',
                        'Sélectionnez une connexion dans l’onglet Connexion pour explorer ses entités.',
                    )}
                </CardContent>
            </Card>
        )
    }

    const openDetail = async (name: string) => {
        setDetailLoading(true)
        try {
            const data = await getEntity(connectionId, name)
            setDetail(data)
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err))
        } finally {
            setDetailLoading(false)
        }
    }

    return (
        <div className='space-y-4'>
            <Card>
                <CardHeader>
                    <CardTitle>
                        {t('sap.browser.title', 'Entités SAP en cache')}
                    </CardTitle>
                </CardHeader>
                <CardContent className='space-y-3'>
                    <Input
                        placeholder={t(
                            'sap.browser.search_placeholder',
                            'Rechercher (nom, label, description)…',
                        )}
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                    />

                    {error && (
                        <p className='text-sm text-destructive'>{error}</p>
                    )}

                    {loading ? (
                        <p className='text-sm text-muted-foreground'>
                            {t('sap.browser.loading', 'Chargement…')}
                        </p>
                    ) : items.length === 0 ? (
                        <p className='text-sm text-muted-foreground'>
                            {t(
                                'sap.browser.no_entities',
                                'Aucune entité dans le cache. Lancez une synchronisation depuis l’onglet Statut.',
                            )}
                        </p>
                    ) : (
                        <>
                            <p className='text-xs text-muted-foreground'>
                                {t(
                                    'sap.browser.count',
                                    '{{shown}} / {{total}} entités',
                                    {
                                        shown: filtered.length,
                                        total: items.length,
                                    },
                                )}
                            </p>
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>
                                            {t(
                                                'sap.browser.col_name',
                                                'EntitySet',
                                            )}
                                        </TableHead>
                                        <TableHead>
                                            {t(
                                                'sap.browser.col_label',
                                                'Label',
                                            )}
                                        </TableHead>
                                        <TableHead className='max-w-md'>
                                            {t(
                                                'sap.browser.col_description',
                                                'Description',
                                            )}
                                        </TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {filtered.map((row) => (
                                        <TableRow
                                            key={row.entity_set_name}
                                            className='cursor-pointer hover:bg-accent/40'
                                            onClick={() =>
                                                void openDetail(row.entity_set_name)
                                            }
                                        >
                                            <TableCell className='font-mono text-xs'>
                                                {row.entity_set_name}
                                            </TableCell>
                                            <TableCell>{row.label ?? '—'}</TableCell>
                                            <TableCell className='max-w-md truncate text-xs text-muted-foreground'>
                                                {row.description ?? ''}
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </>
                    )}
                </CardContent>
            </Card>

            <Dialog
                open={detail !== null || detailLoading}
                onOpenChange={(open) => {
                    if (!open) setDetail(null)
                }}
            >
                <DialogContent className='max-w-3xl max-h-[80vh] overflow-y-auto'>
                    <DialogHeader>
                        <DialogTitle>
                            {detail?.entity_set_name ?? '…'}
                        </DialogTitle>
                    </DialogHeader>
                    {detailLoading && (
                        <p className='text-sm text-muted-foreground'>
                            {t('sap.browser.detail_loading', 'Chargement…')}
                        </p>
                    )}
                    {detail && <EntityDetailView detail={detail} />}
                </DialogContent>
            </Dialog>
        </div>
    )
}

function EntityDetailView({ detail }: { detail: EntityDetail }) {
    const { t } = useTranslation()
    const payload = detail.payload ?? {}
    const properties = payload.properties ?? []
    const navigations = payload.navigations ?? []

    return (
        <div className='space-y-4 text-sm'>
            <div className='flex gap-2 flex-wrap'>
                {payload.key?.map((k) => (
                    <Badge key={k} variant='secondary'>
                        key: {k}
                    </Badge>
                ))}
                {payload.entity_type && (
                    <Badge variant='outline' className='font-mono text-xs'>
                        {payload.entity_type}
                    </Badge>
                )}
            </div>

            {detail.description && (
                <p className='text-muted-foreground'>{detail.description}</p>
            )}

            <div>
                <h3 className='font-semibold mb-2'>
                    {t('sap.browser.detail_properties', 'Propriétés')}
                </h3>
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>
                                {t('sap.browser.detail_col_name', 'Nom')}
                            </TableHead>
                            <TableHead>
                                {t('sap.browser.detail_col_type', 'Type')}
                            </TableHead>
                            <TableHead>
                                {t('sap.browser.detail_col_label', 'SAP label')}
                            </TableHead>
                            <TableHead>
                                {t('sap.browser.detail_col_filter', 'Filtrable')}
                            </TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {properties.map((prop) => (
                            <TableRow key={prop.name}>
                                <TableCell className='font-mono text-xs'>
                                    {prop.name}
                                </TableCell>
                                <TableCell>{prop.type}</TableCell>
                                <TableCell>{prop.sap_label ?? '—'}</TableCell>
                                <TableCell>
                                    {prop.sap_filterable ? '✓' : '✗'}
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>

            {navigations.length > 0 && (
                <div>
                    <h3 className='font-semibold mb-2'>
                        {t('sap.browser.detail_navigations', 'Navigations')}
                    </h3>
                    <ul className='list-disc pl-5'>
                        {navigations.map((nav) => (
                            <li key={nav.name} className='text-xs'>
                                <span className='font-mono'>{nav.name}</span>
                                {nav.target_entity_type && (
                                    <span className='text-muted-foreground'>
                                        {' '}
                                        → {nav.target_entity_type}{' '}
                                        {nav.multiplicity &&
                                            `(${nav.multiplicity})`}
                                    </span>
                                )}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    )
}
