import { AlertCircle, AlertTriangle, Lock01 } from '@untitledui/icons'
import type { BadgeColors } from '@/components/base/badges/badge-types'
import { Badge } from '@/components/base/badges/badges'
import { Tooltip, TooltipTrigger } from '@/components/base/tooltip/tooltip'
import { JOB_STATUS_LABELS } from '../constants'
import type { JobStatus } from '../types'

interface Props {
  status: JobStatus
  escalated?: boolean
  locked?: boolean
  overdue?: boolean
  sourceMissing?: boolean
}

const COLORS: Record<JobStatus, BadgeColors> = {
  pending_annotation: 'gray',
  annotating: 'blue',
  pending_qc1: 'warning',
  qc1_reviewing: 'warning',
  qc1_passed: 'indigo',
  rework: 'orange',
  pending_qc2: 'purple',
  approved: 'success',
  delivered: 'sky',
}

export default function JobStatusTag({ status, escalated, locked, overdue, sourceMissing }: Props) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <Badge type="pill-color" size="sm" color={COLORS[status]}>
        {JOB_STATUS_LABELS[status]}
      </Badge>
      {escalated && (
        <Badge type="pill-color" size="sm" color="error">
          <AlertCircle className="mr-1 size-3" aria-hidden="true" />
          Escalated
        </Badge>
      )}
      {overdue && (
        <Badge type="pill-color" size="sm" color="warning">
          Quá hạn
        </Badge>
      )}
      {sourceMissing && (
        <Tooltip title="Không còn tìm thấy job nguồn trên CVAT ở lần đồng bộ gần nhất">
          <TooltipTrigger className="cursor-default">
            <Badge type="pill-color" size="sm" color="warning">
              <AlertTriangle className="mr-1 size-3" aria-hidden="true" />
              Thiếu nguồn CVAT
            </Badge>
          </TooltipTrigger>
        </Tooltip>
      )}
      {locked && (
        <Tooltip title="Job đang bị khoá">
          <TooltipTrigger className="cursor-default">
            <Badge type="pill-color" size="sm" color="gray">
              <Lock01 className="mr-1 size-3" aria-hidden="true" />
              Khoá
            </Badge>
          </TooltipTrigger>
        </Tooltip>
      )}
    </span>
  )
}
