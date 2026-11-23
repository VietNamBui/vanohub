import type { ReactNode } from 'react'
import { cx } from '@/utils/cx'

/** Ô số liệu nhỏ: con số lớn + nhãn bên dưới. */
export default function StatCard({ value, label, tone, bordered = true }: {
  value: ReactNode
  label: string
  /** "error" → tô đỏ con số khi cần gây chú ý (vd. số người quá tải > 0). */
  tone?: 'error'
  bordered?: boolean
}) {
  return (
    <div className={cx('flex flex-col gap-1 rounded-xl bg-primary p-4', bordered && 'shadow-xs ring-1 ring-secondary')}>
      <span className={cx('text-display-xs font-semibold', tone === 'error' ? 'text-error-primary' : 'text-primary')}>{value}</span>
      <span className="text-sm text-tertiary">{label}</span>
    </div>
  )
}
