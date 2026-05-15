/**
 * Vitest setup: globally mock react-i18next + react-router-dom so each
 * component test can mount without wiring real providers.
 *
 * Tests that need to override the mock can do so via vi.mocked(...)
 * or by re-mocking inside the test file.
 */

// Extends ``expect`` with DOM matchers (toBeInTheDocument,
// toHaveTextContent, etc.). Without this import the assertions throw
// "Invalid Chai property: toBeInTheDocument".
import '@testing-library/jest-dom/vitest'

import { vi } from 'vitest'

// react-i18next — t(key, fallback) returns fallback (or key) so the
// tests don't need a real i18n init.
vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string, fallback?: string | object, options?: object) => {
            if (typeof fallback === 'string') {
                // Crude interpolation: replace {{var}} from options.
                if (options && typeof options === 'object') {
                    return Object.entries(options).reduce(
                        (acc, [k, v]) => acc.replace(`{{${k}}}`, String(v)),
                        fallback,
                    )
                }
                return fallback
            }
            return key
        },
        i18n: { language: 'fr' },
    }),
}))

// react-router-dom — useSearchParams returns a controllable mock.
// Tests can override by re-mocking the module with vi.mock at the
// top of their file.
vi.mock('react-router-dom', () => {
    let params = new URLSearchParams()
    const setParams = vi.fn((next: URLSearchParams) => {
        params = next
    })
    return {
        useSearchParams: () => [params, setParams],
    }
})

// Avoid jsdom warning on window.confirm — return true by default.
// Tests can override per-case.
Object.defineProperty(globalThis, 'confirm', {
    value: vi.fn(() => true),
    writable: true,
})
