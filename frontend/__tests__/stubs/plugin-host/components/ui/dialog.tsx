import { type ReactNode } from 'react'

interface DialogProps {
    children?: ReactNode
    open?: boolean
    onOpenChange?: (open: boolean) => void
}

export const Dialog = ({ children, open }: DialogProps) =>
    open ? <div role='dialog'>{children}</div> : null
export const DialogContent = ({ children }: { children?: ReactNode; className?: string }) => <div>{children}</div>
export const DialogHeader = ({ children }: { children?: ReactNode }) => <div>{children}</div>
export const DialogTitle = ({ children }: { children?: ReactNode }) => <h4>{children}</h4>
export const DialogFooter = ({ children }: { children?: ReactNode }) => <div>{children}</div>
