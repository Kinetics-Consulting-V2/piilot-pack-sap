import { type HTMLAttributes, type ReactNode } from 'react'

interface Props extends HTMLAttributes<HTMLElement> {
    children?: ReactNode
}

export const Table = ({ children, ...rest }: Props) => <table {...rest}>{children}</table>
export const TableHeader = ({ children, ...rest }: Props) => <thead {...rest}>{children}</thead>
export const TableBody = ({ children, ...rest }: Props) => <tbody {...rest}>{children}</tbody>
export const TableRow = ({ children, ...rest }: Props) => <tr {...rest}>{children}</tr>
export const TableHead = ({ children, ...rest }: Props) => <th {...rest}>{children}</th>
export const TableCell = ({ children, ...rest }: Props) => <td {...rest}>{children}</td>
