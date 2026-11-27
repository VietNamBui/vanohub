import { Badge } from '@/components/base/badges/badges'
import type { DataStatus } from '../types'

const LABELS: Record<DataStatus, { label: string; color: 'brand' | 'gray' | 'success' }> = {
  active: { label: 'Đang xử lý', color: 'brand' },
  locked: { label: 'Đã khoá', color: 'gray' },
  delivered: { label: 'Đã bàn giao', color: 'success' },
}

/** Trạng thái dataset / batch (bản Untitled UI của DataStatusTag). */
export default function DataStatusBadge({ status }: { status: DataStatus }) {
  const { label, color } = LABELS[status]
  return <Badge type="pill-color" size="sm" color={color}>{label}</Badge>
}
