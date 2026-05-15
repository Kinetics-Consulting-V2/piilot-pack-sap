import { type ReactNode } from 'react'

interface SelectProps {
    children?: ReactNode
    value?: string
    onValueChange?: (value: string) => void
}

export const Select = ({ children }: SelectProps) => <div>{children}</div>
export const SelectTrigger = ({ children }: { children?: ReactNode; className?: string }) => <div>{children}</div>
export const SelectValue = ({ placeholder }: { placeholder?: string }) => <span>{placeholder}</span>
export const SelectContent = ({ children }: { children?: ReactNode }) => <div>{children}</div>
export const SelectItem = ({ children, value }: { children?: ReactNode; value: string }) => (
    <div data-value={value}>{children}</div>
)
