import { Badge } from '@/components/base/badges/badges'
import { JOB_STATUS_LABELS } from '../constants'
import type { JobStatus } from '../types'

const COLORS = {
  pending_annotation: 'gray',
  annotating: 'blue',
  pending_qc1: 'warning',
  qc1_reviewing: 'warning',
  rework: 'orange',
  pending_qc2: 'purple',
  approved: 'success',
  delivered: 'sky',
} as const

/** Trạng thái job (Untitled UI) + cờ phụ. Luôn có nhãn chữ, không chỉ dựa vào màu. */
export default function JobStatusBadge({ status, escalated, overdue, locked }: {
  status: JobStatus
  escalated?: boolean
  overdue?: boolean
  locked?: boolean
}) {
  return (
    <span className="inline-flex flex-wrap gap-1">
      <Badge type="pill-color" size="sm" color={COLORS[status]}>{JOB_STATUS_LABELS[status]}</Badge>
      {escalated && <Badge type="pill-color" size="sm" color="error">Escalated</Badge>}
      {overdue && <Badge type="pill-color" size="sm" color="warning">Quá hạn</Badge>}
      {locked && <Badge type="pill-color" size="sm" color="gray">Khoá</Badge>}
    </span>
  )
}
