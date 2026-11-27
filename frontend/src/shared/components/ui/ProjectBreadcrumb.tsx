import { ChevronRight, HomeLine } from '@untitledui/icons'
import { Link } from 'react-router'

export interface BreadcrumbItem {
  label: string
  to?: string
}

/** Breadcrumb dùng chung trong organization: nút Home dẫn về trang chủ theo vai trò (/projects/:id). */
export default function ProjectBreadcrumb({ projectId, items }: { projectId: number | null; items: BreadcrumbItem[] }) {
  const homeTo = projectId ? `/projects/${projectId}` : '/projects'

  return (
    <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-2 text-sm">
      <Link
        to={homeTo}
        aria-label="Trang chủ"
        className="flex size-7 items-center justify-center rounded-md text-quaternary transition hover:bg-primary_hover hover:text-secondary"
      >
        <HomeLine className="size-4" />
      </Link>
      {items.map((item, idx) => {
        const isLast = idx === items.length - 1
        return (
          <span key={`${item.label}-${idx}`} className="inline-flex items-center gap-2">
            <ChevronRight className="size-4 text-quaternary" />
            {item.to && !isLast ? (
              <Link to={item.to} className="font-normal text-tertiary transition hover:text-primary">
                {item.label}
              </Link>
            ) : (
              <span className="font-semibold text-brand-secondary">{item.label}</span>
            )}
          </span>
        )
      })}
    </nav>
  )
}
