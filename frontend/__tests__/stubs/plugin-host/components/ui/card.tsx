import { type HTMLAttributes, type ReactNode } from 'react'

interface Props extends HTMLAttributes<HTMLDivElement> {
    children?: ReactNode
}

export const Card = ({ children, ...rest }: Props) => <div {...rest}>{children}</div>
export const CardHeader = ({ children, ...rest }: Props) => <div {...rest}>{children}</div>
export const CardTitle = ({ children, ...rest }: Props) => <h3 {...rest}>{children}</h3>
export const CardContent = ({ children, ...rest }: Props) => <div {...rest}>{children}</div>
