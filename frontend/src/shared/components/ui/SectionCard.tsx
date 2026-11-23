import type { ReactNode } from 'react'
import { cx } from '@/utils/cx'

/** Khối nội dung có tiêu đề (+ mô tả, nút bên phải) — khung chung cho các trang Untitled UI. */
export default function SectionCard({ title, description, actions, children, className, bodyClassName }: {
  title?: ReactNode
  description?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <section className={cx('flex flex-col rounded-2xl bg-primary shadow-xs ring-1 ring-secondary', className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-secondary px-5 py-4">
          <div>
            {title && <h2 className="text-md font-semibold text-primary">{title}</h2>}
            {description && <p className="mt-0.5 text-sm text-tertiary">{description}</p>}
          </div>
          {actions}
        </header>
      )}
      <div className={cx('flex-1 p-5', bodyClassName)}>{children}</div>
    </section>
  )
}
