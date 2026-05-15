/**
 * Connection panel — CRUD over SAP connections + live "Test" action.
 *
 * Lists every active SAP connection of the active tenant in a single
 * table. The "+ New connection" button opens a dialog with the
 * creation form (auth_mode toggle, base_url, credentials). Each row
 * has Test / Edit / Delete actions; selecting a row drives the
 * shared ``selectedConnectionId`` state so the Status / Browser /
 * Audit panels focus on the same connection.
 *
 * The form gates the credentials fields by ``auth_mode``:
 *   - ``basic`` → basic_username + basic_password
 *   - ``oauth_client_credentials`` → token_url + client_id + client_secret + scope
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
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
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@plugin-host/components/ui/dialog'
import { Input } from '@plugin-host/components/ui/input'
import { Label } from '@plugin-host/components/ui/label'
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
    type AuthMode,
    type ConnectionCreatePayload,
    type SAPConnection,
    createConnection,
    deleteConnection,
    listConnections,
    testConnection,
} from '../services/sapClient'

interface Props {
    selectedConnectionId: string | null
    onSelectConnection: (id: string | null) => void
}

const EMPTY_FORM: ConnectionCreatePayload = {
    label: '',
    base_url: '',
    auth_mode: 'basic',
    credentials: {},
}

export default function ConnectionPanel({
    selectedConnectionId,
    onSelectConnection,
}: Props) {
    const { t } = useTranslation()
    const [items, setItems] = useState<SAPConnection[]>([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [dialogOpen, setDialogOpen] = useState(false)

    const reload = useCallback(async () => {
        setLoading(true)
        setError(null)
        try {
            const data = await listConnections()
            setItems(data.items)
            if (data.items.length === 1 && !selectedConnectionId) {
                onSelectConnection(data.items[0].id)
            }
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err))
        } finally {
            setLoading(false)
        }
    }, [onSelectConnection, selectedConnectionId])

    useEffect(() => {
        void reload()
    }, [reload])

    return (
        <div className='space-y-4'>
            <div className='flex justify-between'>
                <p className='text-sm text-muted-foreground'>
                    {t(
                        'sap.connection.subtitle',
                        'Gérez les instances SAP S/4HANA Cloud accessibles depuis vos agents.',
                    )}
                </p>
                <Button onClick={() => setDialogOpen(true)}>
                    {t('sap.connection.new', '+ Nouvelle connexion')}
                </Button>
            </div>

            {error && (
                <Card className='border-destructive'>
                    <CardContent className='p-4 text-sm text-destructive'>
                        {error}
                    </CardContent>
                </Card>
            )}

            <Card>
                <CardHeader>
                    <CardTitle>
                        {t('sap.connection.list_title', 'Connexions enregistrées')}
                    </CardTitle>
                </CardHeader>
                <CardContent>
                    {loading && items.length === 0 ? (
                        <p className='text-sm text-muted-foreground'>
                            {t('sap.connection.loading', 'Chargement…')}
                        </p>
                    ) : items.length === 0 ? (
                        <p className='text-sm text-muted-foreground'>
                            {t(
                                'sap.connection.empty',
                                "Aucune connexion. Cliquez sur « + Nouvelle connexion » pour en créer une.",
                            )}
                        </p>
                    ) : (
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>
                                        {t('sap.connection.col_label', 'Label')}
                                    </TableHead>
                                    <TableHead>
                                        {t('sap.connection.col_base_url', 'URL')}
                                    </TableHead>
                                    <TableHead>
                                        {t('sap.connection.col_auth_mode', 'Auth')}
                                    </TableHead>
                                    <TableHead>
                                        {t('sap.connection.col_health', 'Santé')}
                                    </TableHead>
                                    <TableHead className='text-right'>
                                        {t('sap.connection.col_actions', 'Actions')}
                                    </TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {items.map((row) => (
                                    <ConnectionRow
                                        key={row.id}
                                        row={row}
                                        isSelected={row.id === selectedConnectionId}
                                        onSelect={() => onSelectConnection(row.id)}
                                        onAfterAction={reload}
                                    />
                                ))}
                            </TableBody>
                        </Table>
                    )}
                </CardContent>
            </Card>

            <CreateConnectionDialog
                open={dialogOpen}
                onClose={() => setDialogOpen(false)}
                onCreated={(connection) => {
                    onSelectConnection(connection.id)
                    setDialogOpen(false)
                    void reload()
                }}
            />
        </div>
    )
}

interface RowProps {
    row: SAPConnection
    isSelected: boolean
    onSelect: () => void
    onAfterAction: () => Promise<void>
}

function ConnectionRow({ row, isSelected, onSelect, onAfterAction }: RowProps) {
    const { t } = useTranslation()
    const [testing, setTesting] = useState(false)
    const [deleting, setDeleting] = useState(false)
    const [actionError, setActionError] = useState<string | null>(null)

    const handleTest = async () => {
        setTesting(true)
        setActionError(null)
        try {
            await testConnection(row.id)
            await onAfterAction()
        } catch (err) {
            setActionError(err instanceof Error ? err.message : String(err))
        } finally {
            setTesting(false)
        }
    }

    const handleDelete = async () => {
        if (!window.confirm(t('sap.connection.delete_confirm', 'Supprimer cette connexion ?'))) {
            return
        }
        setDeleting(true)
        setActionError(null)
        try {
            await deleteConnection(row.id)
            await onAfterAction()
        } catch (err) {
            setActionError(err instanceof Error ? err.message : String(err))
        } finally {
            setDeleting(false)
        }
    }

    return (
        <TableRow
            data-selected={isSelected ? 'true' : undefined}
            className={isSelected ? 'bg-accent/40' : undefined}
            onClick={onSelect}
        >
            <TableCell className='font-medium'>{row.label}</TableCell>
            <TableCell className='font-mono text-xs'>{row.base_url}</TableCell>
            <TableCell>
                <Badge variant='secondary'>{row.auth_mode}</Badge>
            </TableCell>
            <TableCell>
                <HealthBadge status={row.last_health_status} />
                {actionError && (
                    <p className='text-xs text-destructive'>{actionError}</p>
                )}
            </TableCell>
            <TableCell className='text-right space-x-2'>
                <Button
                    size='sm'
                    variant='outline'
                    disabled={testing}
                    onClick={(e) => {
                        e.stopPropagation()
                        void handleTest()
                    }}
                >
                    {testing
                        ? t('sap.connection.testing', 'Test…')
                        : t('sap.connection.test', 'Tester')}
                </Button>
                <Button
                    size='sm'
                    variant='ghost'
                    disabled={deleting}
                    onClick={(e) => {
                        e.stopPropagation()
                        void handleDelete()
                    }}
                >
                    {t('sap.connection.delete', 'Supprimer')}
                </Button>
            </TableCell>
        </TableRow>
    )
}

function HealthBadge({ status }: { status: string | null }) {
    const { t } = useTranslation()
    if (!status) {
        return (
            <Badge variant='outline'>
                {t('sap.connection.health_unknown', 'Non testé')}
            </Badge>
        )
    }
    if (status === 'ok') {
        return (
            <Badge className='bg-green-600 text-white'>
                {t('sap.connection.health_ok', 'OK')}
            </Badge>
        )
    }
    return (
        <Badge variant='destructive'>
            {t('sap.connection.health_error', 'Erreur')}
        </Badge>
    )
}

interface DialogProps {
    open: boolean
    onClose: () => void
    onCreated: (connection: SAPConnection) => void
}

function CreateConnectionDialog({ open, onClose, onCreated }: DialogProps) {
    const { t } = useTranslation()
    const [form, setForm] = useState<ConnectionCreatePayload>(EMPTY_FORM)
    const [submitting, setSubmitting] = useState(false)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        if (!open) {
            setForm(EMPTY_FORM)
            setError(null)
        }
    }, [open])

    const isBasic = form.auth_mode === 'basic'

    const credentialsValid = useMemo(() => {
        if (isBasic) {
            return Boolean(
                form.credentials.basic_username && form.credentials.basic_password,
            )
        }
        return Boolean(
            form.credentials.oauth_token_url &&
                form.credentials.oauth_client_id &&
                form.credentials.oauth_client_secret,
        )
    }, [form.auth_mode, form.credentials, isBasic])

    const canSubmit =
        form.label.trim().length > 0 &&
        form.base_url.trim().length > 0 &&
        credentialsValid &&
        !submitting

    const handleSubmit = async () => {
        setSubmitting(true)
        setError(null)
        try {
            const created = await createConnection({
                ...form,
                label: form.label.trim(),
                base_url: form.base_url.trim(),
            })
            onCreated(created)
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err))
        } finally {
            setSubmitting(false)
        }
    }

    return (
        <Dialog open={open} onOpenChange={(value) => !value && onClose()}>
            <DialogContent className='max-w-lg'>
                <DialogHeader>
                    <DialogTitle>
                        {t('sap.connection.dialog_title', 'Nouvelle connexion SAP')}
                    </DialogTitle>
                </DialogHeader>

                <div className='space-y-4'>
                    <div className='space-y-2'>
                        <Label htmlFor='label'>
                            {t('sap.connection.field_label', 'Nom de la connexion')}
                        </Label>
                        <Input
                            id='label'
                            value={form.label}
                            onChange={(e) =>
                                setForm({ ...form, label: e.target.value })
                            }
                            placeholder='Sandbox, Prod, QA…'
                        />
                    </div>

                    <div className='space-y-2'>
                        <Label htmlFor='base_url'>
                            {t('sap.connection.field_base_url', 'URL OData racine')}
                        </Label>
                        <Input
                            id='base_url'
                            value={form.base_url}
                            onChange={(e) =>
                                setForm({ ...form, base_url: e.target.value })
                            }
                            placeholder='https://my123456.s4hana.cloud.sap/sap/opu/odata/sap/API_BUSINESS_PARTNER'
                        />
                    </div>

                    <div className='space-y-2'>
                        <Label>
                            {t('sap.connection.field_auth_mode', "Mode d'authentification")}
                        </Label>
                        <Select
                            value={form.auth_mode}
                            onValueChange={(value: AuthMode) =>
                                setForm({
                                    ...form,
                                    auth_mode: value,
                                    credentials: {},
                                })
                            }
                        >
                            <SelectTrigger>
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value='basic'>Basic (user/password)</SelectItem>
                                <SelectItem value='oauth_client_credentials'>
                                    OAuth 2.0 client_credentials
                                </SelectItem>
                            </SelectContent>
                        </Select>
                    </div>

                    {isBasic ? (
                        <BasicAuthFields form={form} setForm={setForm} />
                    ) : (
                        <OauthFields form={form} setForm={setForm} />
                    )}

                    {error && (
                        <p className='text-sm text-destructive' role='alert'>
                            {error}
                        </p>
                    )}
                </div>

                <DialogFooter>
                    <Button variant='outline' onClick={onClose}>
                        {t('sap.connection.cancel', 'Annuler')}
                    </Button>
                    <Button
                        disabled={!canSubmit}
                        onClick={() => void handleSubmit()}
                    >
                        {submitting
                            ? t('sap.connection.submitting', 'Création…')
                            : t('sap.connection.submit', 'Créer')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

interface AuthFieldsProps {
    form: ConnectionCreatePayload
    setForm: (next: ConnectionCreatePayload) => void
}

function BasicAuthFields({ form, setForm }: AuthFieldsProps) {
    const { t } = useTranslation()
    return (
        <div className='space-y-3'>
            <div className='space-y-2'>
                <Label htmlFor='basic_username'>
                    {t('sap.connection.field_basic_username', "Nom d'utilisateur")}
                </Label>
                <Input
                    id='basic_username'
                    value={form.credentials.basic_username ?? ''}
                    onChange={(e) =>
                        setForm({
                            ...form,
                            credentials: {
                                ...form.credentials,
                                basic_username: e.target.value,
                            },
                        })
                    }
                />
            </div>
            <div className='space-y-2'>
                <Label htmlFor='basic_password'>
                    {t('sap.connection.field_basic_password', 'Mot de passe')}
                </Label>
                <Input
                    id='basic_password'
                    type='password'
                    value={form.credentials.basic_password ?? ''}
                    onChange={(e) =>
                        setForm({
                            ...form,
                            credentials: {
                                ...form.credentials,
                                basic_password: e.target.value,
                            },
                        })
                    }
                />
            </div>
        </div>
    )
}

function OauthFields({ form, setForm }: AuthFieldsProps) {
    const { t } = useTranslation()
    return (
        <div className='space-y-3'>
            <div className='space-y-2'>
                <Label htmlFor='oauth_token_url'>
                    {t('sap.connection.field_oauth_token_url', 'Token URL')}
                </Label>
                <Input
                    id='oauth_token_url'
                    value={form.credentials.oauth_token_url ?? ''}
                    onChange={(e) =>
                        setForm({
                            ...form,
                            credentials: {
                                ...form.credentials,
                                oauth_token_url: e.target.value,
                            },
                        })
                    }
                />
            </div>
            <div className='space-y-2'>
                <Label htmlFor='oauth_client_id'>
                    {t('sap.connection.field_oauth_client_id', 'Client ID')}
                </Label>
                <Input
                    id='oauth_client_id'
                    value={form.credentials.oauth_client_id ?? ''}
                    onChange={(e) =>
                        setForm({
                            ...form,
                            credentials: {
                                ...form.credentials,
                                oauth_client_id: e.target.value,
                            },
                        })
                    }
                />
            </div>
            <div className='space-y-2'>
                <Label htmlFor='oauth_client_secret'>
                    {t('sap.connection.field_oauth_client_secret', 'Client Secret')}
                </Label>
                <Input
                    id='oauth_client_secret'
                    type='password'
                    value={form.credentials.oauth_client_secret ?? ''}
                    onChange={(e) =>
                        setForm({
                            ...form,
                            credentials: {
                                ...form.credentials,
                                oauth_client_secret: e.target.value,
                            },
                        })
                    }
                />
            </div>
            <div className='space-y-2'>
                <Label htmlFor='oauth_scope'>
                    {t('sap.connection.field_oauth_scope', 'Scope (optionnel)')}
                </Label>
                <Input
                    id='oauth_scope'
                    value={form.credentials.oauth_scope ?? ''}
                    onChange={(e) =>
                        setForm({
                            ...form,
                            credentials: {
                                ...form.credentials,
                                oauth_scope: e.target.value,
                            },
                        })
                    }
                />
            </div>
        </div>
    )
}
