import { type HTMLAttributes, type ReactNode } from 'react'

interface Props extends HTMLAttributes<HTMLSpanElement> {
    children?: ReactNode
    variant?: 'default' | 'secondary' | 'outline' | 'destructive'
}

export const Badge = ({ children, ...rest }: Props) => <span {...rest}>{children}</span>
