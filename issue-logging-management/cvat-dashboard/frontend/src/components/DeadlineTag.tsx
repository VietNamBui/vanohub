import dayjs from 'dayjs'
import { Tooltip } from 'antd'
import type { DeadlineStatus } from '../mock/types'
import type { Tone } from '../design'

export interface DeadlineTagProps {
  status: DeadlineStatus
  /** ISO hạn hiệu lực của bước hiện tại. */
  dueAt: string | null
  /** Giờ còn lại (âm khi trễ) — lấy từ `hoursLeft(state, job)`. */
  hoursLeft: number | null
  /** Pill nhỏ, chữ gọn ("Trễ 5g"). */
  compact?: boolean
  /** Nguồn hạn (`jobDeadline(...).source`) — hiện trong tooltip. */
  source?: 'job' | 'batch'
}

const TONE: Record<Exclude<DeadlineStatus, 'none'>, Tone> = { overdue: 'pink', due_soon: 'orange', on_track: 'gray' }
const SOURCE_LABEL = { job: 'Hạn riêng của job', batch: 'Theo hạn batch' }

/** "Trễ 5 giờ" / "Trễ 2 ngày" / "Còn 6 giờ" / "Hạn 26/11". */
export function deadlineText(status: DeadlineStatus, dueAt: string | null, hoursLeft: number | null, compact = false): string {
  const h = compact ? 'g' : ' giờ'
  const d = compact ? 'n' : ' ngày'
  const sp = ' '
  const abs = Math.abs(hoursLeft ?? 0)
  if (status === 'overdue') return abs < 24 ? `Trễ${sp}${Math.max(1, Math.floor(abs))}${h}` : `Trễ${sp}${Math.floor(abs / 24)}${d}`
  if (status === 'due_soon') return `Còn${sp}${Math.max(1, Math.ceil(abs))}${h}`
  return dueAt ? (compact ? dayjs(dueAt).format('DD/MM') : `Hạn ${dayjs(dueAt).format('DD/MM')}`) : ''
}

export function DeadlineTag({ status, dueAt, hoursLeft, compact = false, source }: DeadlineTagProps) {
  if (status === 'none') return null
  const full = dueAt ? dayjs(dueAt).format('DD/MM/YYYY HH:mm') : ''
  const tip = (
    <>
      <div>{full}</div>
      {source && <div>{SOURCE_LABEL[source]}</div>}
    </>
  )
  return (
    <Tooltip title={tip}>
      <span className={`cvd-tag cvd-tag-${TONE[status]} cvd-deadline ${compact ? 'cvd-deadline-compact' : ''}`}>
        {deadlineText(status, dueAt, hoursLeft, compact)}
      </span>
    </Tooltip>
  )
}
