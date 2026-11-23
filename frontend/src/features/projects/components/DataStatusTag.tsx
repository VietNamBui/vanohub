import { Tag } from 'antd'
import type { DataStatus } from '../types'

const LABELS: Record<DataStatus, [string, string]> = {
  active: ['Đang xử lý', 'processing'],
  locked: ['Đã khoá', 'default'],
  delivered: ['Đã bàn giao', 'success'],
}

export default function DataStatusTag({ status }: { status: DataStatus }) {
  const [label, color] = LABELS[status]
  return <Tag color={color}>{label}</Tag>
}
