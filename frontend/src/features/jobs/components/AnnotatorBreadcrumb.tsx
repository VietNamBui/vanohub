import { ChevronRight, HomeLine } from '@untitledui/icons'
import { Link } from 'react-router'

export interface Crumb {
  label: string
  to?: string
}

/** Breadcrumb điều hướng trong khu vực Annotator của VanoHub. */
export default function AnnotatorBreadcrumb({ projectId, items }: { projectId: number | null; items: Crumb[] }) {
  const homeTo = projectId ? `/projects/${projectId}` : '/projects'

  return (
    <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-2 text-sm">
      <Link
        to={homeTo}
        aria-label="Trang chủ"
        className="flex size-7 items-center justify-center rounded-md text-tertiary transition hover:bg-secondary_hover hover:text-secondary"
      >
        <HomeLine className="size-4" />
      </Link>
      {items.map((item, idx) => {
        const isLast = idx === items.length - 1
        return (
          <span key={item.label} className="inline-flex items-center gap-2">
            <ChevronRight className="size-4 text-fg-quaternary" />
            {item.to && !isLast ? (
              <Link to={item.to} className="font-normal text-tertiary transition hover:text-secondary">
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
