import { useState, type ReactNode } from 'react'
import { Select } from 'antd'
import { StarFilled, StarOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { StripedBar, Tag, fmt } from '../../design'
import { FilterBar, type RowTone } from '../../components'
import { jobsOfBatch, visibleBatches } from '../../mock/selectors'
import { can } from '../../mock/policy'
import type { StoreValue } from '../../mock/store'
import type { Batch, Dataset, Job, User } from '../../mock/types'

// RowList chuyển sang components (W2-A); giữ re-export cho các cấp Hàng đợi.
export { RowList, type ListRow, type RowListProps, type RowTone } from '../../components'

/** Một cấp trong đường lui của Hàng đợi (dùng để tính nút ‹ quay lại). */
export interface Crumb { label: string; to?: string }

/** Hạn + đếm ngược theo ngày (so với `now` của store, không dùng đồng hồ máy). */
export function DueCell({ dueAt, now }: { dueAt: string | null; now: string }) {
  if (!dueAt) return <span className="cvd-muted">Chưa đặt hạn</span>
  const days = Math.ceil((new Date(dueAt).getTime() - new Date(now).getTime()) / 86_400_000)
  const tone = days < 0 ? 'pink' : days <= 7 ? 'orange' : 'gray'
  return (
    <span className="aq-due">
      <span>{dayjs(dueAt).format('DD/MM/YYYY')}</span>
      <Tag tone={tone}>{days < 0 ? `Trễ ${-days} ngày` : days === 0 ? 'Hôm nay' : `Còn ${days} ngày`}</Tag>
    </span>
  )
}

/** Thanh tiến độ + chữ "x/y" cho ô bảng. */
export function ProgressCell({ done, total, tone = 'blue' }: { done: number; total: number; tone?: 'blue' | 'green' | 'pink' }) {
  return (
    <div className="aq-progress">
      <StripedBar value={done} max={total} tone={tone} thin />
      <span className="cvd-muted">{fmt(done)}/{fmt(total)}</span>
    </div>
  )
}

export function PctBar({ value, tone = 'blue' }: { value: number; tone?: 'blue' | 'green' | 'pink' }) {
  return (
    <div className="aq-progress">
      <StripedBar value={value} max={100} tone={tone} thin />
      <span className="cvd-muted">{value}%</span>
    </div>
  )
}

/** ★ ưu tiên 1..5; bấm sao thứ n để đặt mức n, rê chuột xem trước mức. `onChange` thiếu ⇒ chỉ đọc. */
export function PriorityStars({ value, onChange }: { value: number; onChange?: (v: number) => void }) {
  const [hover, setHover] = useState(0)
  const shown = onChange && hover ? hover : value
  return (
    <span className="aq-stars" aria-label={`Ưu tiên ${value}/5`} onMouseLeave={() => setHover(0)}>
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n} type="button" className={n <= shown ? 'on' : ''} disabled={!onChange}
          aria-label={`Đặt ưu tiên ${n}`} onMouseEnter={() => setHover(n)} onFocus={() => setHover(n)} onBlur={() => setHover(0)}
          onClick={(e) => { e.stopPropagation(); onChange?.(n) }}
        >
          {n <= shown ? <StarFilled /> : <StarOutlined />}
        </button>
      ))}
    </span>
  )
}

/** Màu vạch mép trái theo hạn: không hạn/đã xong ⇒ xám, trễ ⇒ hồng, ≤7 ngày ⇒ cam, còn lại xanh. */
export function dueTone(dueAt: string | null, now: string, finished = false): RowTone {
  if (!dueAt || finished) return 'idle'
  const days = Math.ceil((new Date(dueAt).getTime() - new Date(now).getTime()) / 86_400_000)
  return days < 0 ? 'bad' : days <= 7 ? 'warn' : 'ok'
}

export interface ListControlsProps<S extends string> {
  search: string
  onSearch: (v: string) => void
  placeholder: string
  status: string
  onStatus: (v: string) => void
  statusOptions: { value: string; label: string }[]
  sort: S
  onSort: (v: S) => void
  sortOptions: { value: S; label: string }[]
  extra?: ReactNode
}

/** Hàng ô tìm + lọc trạng thái + sắp xếp dùng chung cho cả 4 cấp. */
export function ListControls<S extends string>(p: ListControlsProps<S>) {
  return (
    <FilterBar search={p.search} onSearch={p.onSearch} placeholder={p.placeholder} extra={p.extra}>
      <Select value={p.status} onChange={p.onStatus} style={{ width: 190 }} options={p.statusOptions} />
      <Select<S> value={p.sort} onChange={p.onSort} style={{ width: 210 }} options={p.sortOptions} />
    </FilterBar>
  )
}

export const PAGE_SIZE = 10
export const pagination = { pageSize: PAGE_SIZE, hideOnSinglePage: true, showSizeChanger: false } as const

export const QUEUE_ROOT = '/queue'
/** URL cấp Job của Hàng đợi cho một batch (đích của `/batches/:batchId` cũ). */
export const queueBatchPath = (b: Pick<Batch, 'id' | 'projectId' | 'datasetId'>): string => `${QUEUE_ROOT}/${b.projectId}/${b.datasetId}/${b.id}`
/** Đích của nút quay lại: đường dẫn cấp trên + tên cấp trên (cho aria-label). */
export interface BackLink { to: string; label: string }

// ---------- Phạm vi theo vai trò (Q-I1) ----------
/** admin/pm thấy mọi job của batch/dự án mình thấy; lead chỉ job thuộc team của mình. */
export const jobInScope = (user: User) => (j: Job): boolean =>
  user.role !== 'lead' || (j.teamId !== null && user.teamIds.includes(j.teamId))
export const scopedJobsOfBatch = (s: StoreValue, batchId: string): Job[] => jobsOfBatch(s, batchId).filter(jobInScope(s.currentUser))
/** Dataset của dự án mà user thấy: admin/pm tất cả; lead chỉ dataset có batch trong phạm vi của mình. */
export function datasetsInScope(s: StoreValue, projectId: string): Dataset[] {
  const all = s.datasets.filter((d) => d.projectId === projectId)
  if (s.currentUser.role !== 'lead') return all
  const ids = new Set(visibleBatches(s, s.currentUser).map((b) => b.datasetId))
  return all.filter((d) => ids.has(d.id))
}
/** Batch của dataset mà user thấy. */
export const batchesInScope = (s: StoreValue, datasetId: string): Batch[] => visibleBatches(s, s.currentUser).filter((b) => b.datasetId === datasetId)
/** Chỉ pm của dự án / admin đổi ★ (R9 — `can({kind:'manageBatch', op:'priority'})`); batch release thì khoá. */
export function canSetPriority(s: StoreValue, batch: Batch): boolean {
  if (batch.status === 'released') return false
  return can(s, s.currentUser, { kind: 'manageBatch', batchId: batch.id, op: 'priority' }).ok
}

/** Thẻ danh sách: tiêu đề + phần phụ + (tuỳ chọn) nút quay lại thay chỗ nút ⋯. Cấp Dự án không truyền `backLabel`. */
export function ListCard({ title, extra, backLabel, onBack, children }: { title: string; extra?: ReactNode; backLabel?: string; onBack?: () => void; children: ReactNode }) {
  return (
    <div className="cvd-card">
      <div className="cvd-card-header">
        <h3>{title}</h3>
        <div className="cvd-card-extra">
          {extra}
          {onBack && (
            <button type="button" className="cvd-dots aq-back" onClick={onBack} aria-label={`Quay lại ${backLabel ?? ''}`.trim()}>‹</button>
          )}
        </div>
      </div>
      {children}
    </div>
  )
}
