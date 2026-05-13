/**
 * piilot-pack-sap — frontend entry point.
 *
 * Exports a single ``register`` function the core calls at boot via
 * the Vite alias ``@plugin/sap`` (host-side ``loader.ts``). Wires the
 * SAP connector module view + i18n bundles into the core registry.
 *
 * The plugin contributes exactly **two** things to the host UI :
 *   1. A React component rendered inside ``ModuleViewShell`` when the
 *      user opens ``/modules/:slug`` matching ``sap.connector``.
 *   2. FR/EN translation keys merged under the ``sap`` namespace.
 *
 * Nothing else. Connection config, status panel, entity browser,
 * audit log — all live inside ``SAPConnectorView``. The host only
 * provides the shell.
 */

import type { PluginHostApi } from '@plugin-host/lib/pluginUI'

import SAPConnectorView from './SAPConnectorView'
import fr from './locales/fr.json'
import en from './locales/en.json'

// Single source of truth for this plugin's namespace. Used both for
// ``registerI18nBundle(NS, ...)`` AND for unwrapping the locale JSON's
// top-level ``{[NS]: {...}}`` envelope. Backend namespace
// (``[tool.piilot.plugin].namespace``) and frontend NS MUST match —
// see PLUGIN_DEV_WORKFLOW §4.4.
const NS = 'sap'

export function register(core: PluginHostApi): void {
    // Slug must match the ``module_slug`` seeded by the backend's
    // ``register_module(...)`` call in ``seeds.py``. Typos here
    // silently disable the plugin UI rather than crashing — the shell
    // falls back to the generic step runner.
    core.registerModuleView(`${NS}.connector`, SAPConnectorView)

    // Locale JSON files wrap their content under the namespace key to
    // match the TOML convention. Pass the inner payload to avoid
    // double-nesting when the host merges.
    const frKeys = (fr as Record<string, unknown>)[NS] ?? fr
    const enKeys = (en as Record<string, unknown>)[NS] ?? en
    core.registerI18nBundle(NS, 'fr', frKeys as Record<string, unknown>)
    core.registerI18nBundle(NS, 'en', enKeys as Record<string, unknown>)
}

export default { register }
