/**
 * Smoke test — ``register(core)`` wires the module view + i18n bundles.
 *
 * No React rendering here : we only check that ``register`` calls the
 * host primitives with the expected shape. Mount tests for
 * ``SAPConnectorView`` should live in their own file with
 * ``@testing-library/react``.
 */

import { describe, expect, it, vi } from 'vitest'

import { register } from '../src/index'

describe('register', () => {
    it('calls registerModuleView with the correct slug', () => {
        const registerModuleView = vi.fn()
        const registerI18nBundle = vi.fn()

        register({ registerModuleView, registerI18nBundle })

        expect(registerModuleView).toHaveBeenCalledTimes(1)
        expect(registerModuleView.mock.calls[0][0]).toBe('sap.connector')
    })

    it('registers FR + EN i18n bundles under the sap namespace', () => {
        const registerModuleView = vi.fn()
        const registerI18nBundle = vi.fn()

        register({ registerModuleView, registerI18nBundle })

        expect(registerI18nBundle).toHaveBeenCalledTimes(2)
        const namespaces = registerI18nBundle.mock.calls.map((c) => c[0])
        const langs = registerI18nBundle.mock.calls.map((c) => c[1])
        expect(namespaces).toEqual(['sap', 'sap'])
        expect(new Set(langs)).toEqual(new Set(['fr', 'en']))
    })
})
