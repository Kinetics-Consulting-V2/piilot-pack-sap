// Stub of @plugin-host/lib/pluginUI.
export interface ModuleViewProps {
    moduleId: string
    slug: string
    companyId: string
    module: Record<string, unknown>
}

export interface PluginHostApi {
    registerModuleView: (slug: string, Component: unknown) => void
    registerI18nBundle: (
        namespace: string,
        lang: 'fr' | 'en',
        keys: Record<string, unknown>,
    ) => void
}
