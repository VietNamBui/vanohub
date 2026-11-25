import { ChevronRight } from '@untitledui/icons'
import { Link } from 'react-router'

export interface Crumb {
  label: string
  to?: string
}

/** Breadcrumb chuẩn thiết kế Annota: Home icon > cấp cha > trang hiện tại màu tím #6941C6. */
export default function AnnotatorBreadcrumb({ projectId, items }: { projectId: number | null; items: Crumb[] }) {
  const homeTo = projectId ? `/projects/${projectId}/annotator/dashboard` : '/projects'

  return (
    <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-2 text-sm">
      <Link
        to={homeTo}
        aria-label="Trang chủ"
        className="flex size-7 items-center justify-center rounded-md text-[#667085] transition hover:bg-[#F2F4F7] hover:text-[#344054]"
      >
        <svg className="size-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7">
          <path d="M3.5 9.2 10 3.5l6.5 5.7M5.5 7.8V16a1 1 0 0 0 1 1h7a1 1 0 0 0 1-1V7.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </Link>
      {items.map((item, idx) => {
        const isLast = idx === items.length - 1
        return (
          <span key={item.label} className="inline-flex items-center gap-2">
            <ChevronRight className="size-4 text-[#D0D5DD]" />
            {item.to && !isLast ? (
              <Link to={item.to} className="font-normal text-[#475467] hover:text-[#101828]">
                {item.label}
              </Link>
            ) : (
              <span className="font-semibold text-[#6941C6]">{item.label}</span>
            )}
          </span>
        )
      })}
    </nav>
  )
}
