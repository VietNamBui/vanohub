import dayjs from 'dayjs'
import { useStore } from '../mock/store'
import { STAGE_LABEL, userById } from '../mock/selectors'
import type { JobEvent } from '../mock/types'
import { Tag } from '../design'
import { StageTag } from './StageTag'

export interface JobTimelineProps {
  /** Sự kiện của MỘT job (dùng `eventsOfJob(state, jobId)` để lấy, đã sắp cũ → mới). */
  events: JobEvent[]
  /** Hiện mới nhất trước. Mặc định false. */
  reverse?: boolean
}

export function JobTimeline({ events, reverse = false }: JobTimelineProps) {
  const s = useStore()
  if (events.length === 0) return <div className="cvd-empty">Chưa có sự kiện</div>
  const list = reverse ? [...events].reverse() : events
  return (
    <div className="cvd-timeline">
      {list.map((e) => (
        <div key={e.id} className={`cvd-timeline-item ${e.reworkAgainst?.length ? 'rework' : e.toStage === 'delivered' ? 'done' : ''}`}>
          <div className="cvd-timeline-head">
            <strong>{userById(s, e.actorId)?.name ?? e.actorId}</strong>
            <span className="cvd-muted">{dayjs(e.at).format('DD/MM/YYYY HH:mm')}</span>
          </div>
          <div className="cvd-timeline-body">
            {e.type === 'due_override' ? (
              <div className="cvd-timeline-flow">
                <Tag tone="blue">Đổi hạn</Tag>
                {e.toStage && <StageTag stage={e.toStage} />}
              </div>
            ) : (
            <div className="cvd-timeline-flow">
              {e.fromStage ? <StageTag stage={e.fromStage} /> : <span className="cvd-muted">{STAGE_LABEL.unassigned_pool}</span>}
              <span className="cvd-muted">→</span>
              <StageTag stage={e.toStage} />
            </div>
            )}
            {e.errorCategory && <div><span className="cvd-muted">Loại lỗi: </span><strong>{e.errorCategory}</strong></div>}
            {e.reason && (e.type === 'due_override'
              ? <div>{e.reason}</div>
              : <div><span className="cvd-muted">Lý do: </span>{e.reason}</div>)}
            {e.reworkAgainst?.length ? (
              <div><span className="cvd-muted">Làm lại: </span>{e.reworkAgainst.map((id) => userById(s, id)?.name ?? id).join(', ')}</div>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  )
}
