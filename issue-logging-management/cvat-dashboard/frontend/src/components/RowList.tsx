import { useEffect, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from 'react'
import { Pagination } from 'antd'

/** Màu vạch mép trái: ok = xanh, warn = cam, bad = hồng, idle = xám. */
export type RowTone = 'ok' | 'warn' | 'bad' | 'idle'

export interface ListRow {
  key: string
  tone: RowTone
  /** aria-label của cả dòng, vd "Mở audit au3". */
  label: string
  onOpen: () => void
  /** Cùng số phần tử với `heads`. Nút trong ô phải chặn nổi bọt (`stopRow`). */
  cells: ReactNode[]
}

export interface RowListProps {
  /** Tiêu đề cột (cùng số phần tử với `cells` của mỗi dòng). */
  heads: string[]
  /** CSS grid-template-columns cho màn rộng (chưa gồm cột mũi tên). */
  cols: string
  rows: ListRow[]
  emptyText: string
  /** Dòng phụ dưới `emptyText`; mặc định gợi ý bỏ bớt bộ lọc khi có `onClear`. */
  emptyHint?: string
  /** Có ⇒ trạng thái rỗng hiện nút "Xoá bộ lọc". */
  onClear?: () => void
  /** Đổi giá trị này (bộ lọc/sắp xếp) ⇒ về trang 1. */
  resetKey?: string
}

export const ROWLIST_PAGE_SIZE = 10

/** Dùng cho nút/ô thao tác bên trong dòng: bấm không mở dòng. */
export const stopRow = (e: MouseEvent) => e.stopPropagation()

/** Vạch màu theo KPI hôm nay: không có mục tiêu ⇒ xám, đạt ⇒ xanh, dưới 50% ⇒ hồng, còn lại cam. */
export function kpiTone(today: number, target: number): RowTone {
  if (!target) return 'idle'
  if (today >= target) return 'ok'
  return today * 2 < target ? 'bad' : 'warn'
}

/** Danh sách dòng-thẻ thay AntD Table cho danh sách điều hướng: bấm cả dòng để mở, vạch màu tình trạng, phân trang 10. */
export function RowList({ heads, cols, rows, emptyText, emptyHint, onClear, resetKey = '' }: RowListProps) {
  const [page, setPage] = useState(1)
  useEffect(() => { setPage(1) }, [resetKey])
  const last = Math.max(1, Math.ceil(rows.length / ROWLIST_PAGE_SIZE))
  const cur = Math.min(page, last)
  const view = rows.slice((cur - 1) * ROWLIST_PAGE_SIZE, cur * ROWLIST_PAGE_SIZE)

  if (rows.length === 0) {
    const hint = emptyHint ?? (onClear ? 'Thử bỏ bớt từ khoá hoặc chọn lại trạng thái.' : undefined)
    return (
      <div className="cvd-rowlist-empty">
        <p>{emptyText}</p>
        {hint && <span>{hint}</span>}
        {onClear && <button type="button" className="cvd-rowlist-linkbtn" onClick={onClear}>Xoá bộ lọc</button>}
      </div>
    )
  }
  const onKey = (r: ListRow) => (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget) return
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); r.onOpen() }
  }
  return (
    <div className="cvd-rowlist" style={{ ['--cvd-rowlist-cols' as string]: cols }}>
      <div className="cvd-rowlist-head" aria-hidden="true">
        {heads.map((h, i) => <span key={`${i}-${h}`}>{h}</span>)}
        <span />
      </div>
      {view.map((r, i) => (
        <div
          key={r.key} role="link" tabIndex={0} aria-label={r.label} className={`cvd-rowlist-row cvd-rowlist-${r.tone}`}
          style={{ animationDelay: `${i * 30}ms` }} onClick={r.onOpen} onKeyDown={onKey(r)}
        >
          {r.cells.map((c, j) => <div key={j} className={`cvd-rowlist-cell cvd-rowlist-cell-${j}`} data-label={heads[j]}>{c}</div>)}
          <span className="cvd-rowlist-chev" aria-hidden="true">›</span>
        </div>
      ))}
      {rows.length > ROWLIST_PAGE_SIZE && (
        <div className="cvd-rowlist-pager">
          <Pagination current={cur} pageSize={ROWLIST_PAGE_SIZE} total={rows.length} onChange={setPage} showSizeChanger={false} />
        </div>
      )}
    </div>
  )
}
