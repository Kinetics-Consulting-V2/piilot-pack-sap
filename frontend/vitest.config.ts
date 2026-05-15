/// <reference types="vitest" />
import { fileURLToPath } from 'node:url'

import { defineConfig } from 'vitest/config'

// Vitest cannot reach the host's frontend in isolation, so we alias
// @plugin-host/* to a tiny local stub tree (see __tests__/stubs/). Real
// production resolution is handled by the host's vite.config.ts.
const pluginHostStub = fileURLToPath(
    new URL('./__tests__/stubs/plugin-host', import.meta.url),
)

export default defineConfig({
    resolve: {
        alias: {
            '@plugin-host': pluginHostStub,
        },
    },
    test: {
        globals: true,
        environment: 'jsdom',
        setupFiles: ['__tests__/setup.tsx'],
        include: ['__tests__/**/*.test.{ts,tsx}'],
    },
})
