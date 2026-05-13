import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'

import { Card, CardContent } from '@plugin-host/components/ui/card'
import type { ModuleViewProps } from '@plugin-host/lib/pluginUI'

/**
 * SAP S/4HANA Cloud connector module view.
 *
 * v0.1.0 (Phase 0 scaffolding): renders an information banner only.
 * The real 4-tab UX (Connection / Status / Browser / Audit) lands in
 * Phase 3 — see the project's ``docs/docs_dev/suivi.md``.
 *
 * URL-driven sub-routing via ``useSearchParams`` keeps the URL
 * ``/modules/<uuid>?tab=status`` copyable and back-button safe.
 *
 * Props documented in PLUGIN_DEVELOPMENT.md §20.
 */
export default function SAPConnectorView({ slug, companyId }: ModuleViewProps) {
    const { t } = useTranslation()
    const [searchParams] = useSearchParams()
    const activeTab = searchParams.get('tab') ?? 'connection'

    return (
        <Card>
            <CardContent className='p-6 space-y-4'>
                <div>
                    <h1 className='text-xl font-semibold'>
                        {t('sap.modules.connector.title', 'SAP S/4HANA Cloud')}
                    </h1>
                    <p className='text-sm text-muted-foreground'>
                        {t(
                            'sap.modules.connector.description',
                            'Connect to your SAP S/4HANA Cloud instance via OData v4.',
                        )}
                    </p>
                </div>

                <div className='rounded-md bg-amber-50 border border-amber-200 p-4 text-sm text-amber-900 dark:bg-amber-950/40 dark:border-amber-900/60 dark:text-amber-100'>
                    <p className='font-medium'>
                        {t(
                            'sap.view.phase_banner',
                            'SAP plugin — v0.1.0 (Phase 0 scaffolding)',
                        )}
                    </p>
                    <p className='mt-2'>
                        {t(
                            'sap.view.phase_description',
                            'This module will host the SAP connection config, status, OData entity browser and audit log. Phases 1 to 5 incoming.',
                        )}
                    </p>
                </div>

                <div className='text-xs text-muted-foreground'>
                    Slug: <code>{slug}</code> · Company: <code>{companyId}</code>{' '}
                    · Tab placeholder: <code>{activeTab}</code>
                </div>
            </CardContent>
        </Card>
    )
}
