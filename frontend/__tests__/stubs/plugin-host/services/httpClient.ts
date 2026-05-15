// Stub of @plugin-host/services/httpClient used by vitest.
// Tests override this via vi.mock() — the stub just needs to exist so
// Vite's resolver doesn't fail at import time.
export async function apiFetch(_path: string, _options?: RequestInit): Promise<unknown> {
    throw new Error('apiFetch stub invoked — test must mock @plugin-host/services/httpClient')
}
