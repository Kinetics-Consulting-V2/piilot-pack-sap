// Minimal stubs of shadcn Tabs — enough for tests to mount without
// pulling Radix.
import { type ReactNode } from 'react'

export const Tabs = ({ children }: { children: ReactNode; value?: string; onValueChange?: (v: string) => void }) => <div>{children}</div>
export const TabsList = ({ children }: { children: ReactNode }) => <div role='tablist'>{children}</div>
export const TabsTrigger = ({ children, value }: { children: ReactNode; value: string }) => (
    <button role='tab' data-value={value}>{children}</button>
)
export const TabsContent = ({ children, value }: { children: ReactNode; value: string }) => (
    <div role='tabpanel' data-value={value}>{children}</div>
)
