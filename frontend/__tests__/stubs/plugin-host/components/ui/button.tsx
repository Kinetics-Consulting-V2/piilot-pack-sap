import { type ButtonHTMLAttributes, type ReactNode } from 'react'

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
    children?: ReactNode
    variant?: 'default' | 'outline' | 'ghost' | 'secondary' | 'destructive'
    size?: 'default' | 'sm' | 'lg' | 'icon'
}

export const Button = ({ children, ...rest }: Props) => <button {...rest}>{children}</button>
