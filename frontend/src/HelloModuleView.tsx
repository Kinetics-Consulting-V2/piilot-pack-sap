import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'

import { Button } from '@plugin-host/components/ui/button'
import { Card, CardContent } from '@plugin-host/components/ui/card'
import type { ModuleViewProps } from '@plugin-host/lib/pluginUI'

/**
 * Minimum viable module view — replace with your real UX.
 *
 * URL-driven sub-routing via ``useSearchParams`` keeps the URL
 * ``/modules/<uuid>?view=detail`` copyable and back-button safe.
 * Don't add top-level app routes from inside a plugin — scope
 * everything under the module shell.
 *
 * Props documented in ``PLUGIN_DEVELOPMENT.md`` §20.
 */
export default function HelloModuleView({
    slug,
    companyId,
}: ModuleViewProps) {
    const { t } = useTranslation()
    const [searchParams, setSearchParams] = useSearchParams()
    const viewId = searchParams.get('view')

    return (
        <Card>
            <CardContent className='p-6 space-y-4'>
                <div>
                    <h1 className='text-xl font-semibold'>
                        {t('hello.module.title', 'Hello module')}
                    </h1>
                    <p className='text-sm text-muted-foreground'>
                        Slug: <code>{slug}</code> · Company:{' '}
                        <code>{companyId}</code>
                    </p>
                </div>

                {viewId === 'detail' ? (
                    <div className='space-y-2'>
                        <p>
                            {t(
                                'hello.module.detail.body',
                                'You are on the detail sub-view. Sub-routing is URL-backed.',
                            )}
                        </p>
                        <Button onClick={() => setSearchParams({})}>
                            {t('hello.module.detail.back', 'Back')}
                        </Button>
                    </div>
                ) : (
                    <Button
                        onClick={() => setSearchParams({ view: 'detail' })}
                    >
                        {t('hello.module.open', 'Open detail')}
                    </Button>
                )}
            </CardContent>
        </Card>
    )
}
