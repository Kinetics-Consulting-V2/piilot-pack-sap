import { type LabelHTMLAttributes, type ReactNode } from 'react'

interface Props extends LabelHTMLAttributes<HTMLLabelElement> {
    children?: ReactNode
}

export const Label = ({ children, ...rest }: Props) => <label {...rest}>{children}</label>
