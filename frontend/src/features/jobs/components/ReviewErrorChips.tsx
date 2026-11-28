import { Badge } from '@/components/base/badges/badges'
import { hasStructuredErrorMeta } from '../jobHelpers'
import type { JobErrorBrief } from '../types'

interface Props {
  err: Pick<JobErrorBrief, 'frame_number' | 'cvat_object_id' | 'is_missing_object' | 'verdict' | 'is_voided'>
  className?: string
}

/** Nhãn cấu trúc của ReviewError: Frame, CVAT Object ID, Thiếu đối tượng, Kết luận Fail/Edge, Đã huỷ lỗi. */
export default function ReviewErrorChips({ err, className = 'mt-1 flex flex-wrap gap-1' }: Props) {
  if (!hasStructuredErrorMeta(err)) return null
  return (
    <div className={className}>
      {err.frame_number != null && (
        <Badge size="sm" type="pill-color" color="gray">
          Frame #{err.frame_number}
        </Badge>
      )}
      {err.cvat_object_id != null && (
        <Badge size="sm" type="pill-color" color="blue">
          Object #{err.cvat_object_id}
        </Badge>
      )}
      {err.is_missing_object && (
        <Badge size="sm" type="pill-color" color="orange">
          Thiếu đối tượng
        </Badge>
      )}
      {err.verdict === 'edge' && (
        <Badge size="sm" type="pill-color" color="warning">
          Cận biên
        </Badge>
      )}
      {err.verdict === 'fail' && (
        <Badge size="sm" type="pill-color" color="error">
          Lỗi
        </Badge>
      )}
      {err.is_voided && (
        <Badge size="sm" type="pill-color" color="gray">
          Đã huỷ lỗi
        </Badge>
      )}
    </div>
  )
}
