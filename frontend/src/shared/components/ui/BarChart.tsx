import { useState } from 'react'

export interface BarDatum {
  label: string
  value: number
  /** Các dòng hiện trong tooltip khi rê chuột. */
  details?: string[]
}

/**
 * Biểu đồ cột một chuỗi (không cần legend — tiêu đề khối nói rõ chuỗi là gì).
 * Cột mảnh bo 4px phía trên, khe 2px, lưới mờ, tooltip khi rê chuột; nhãn trục X thưa dần khi nhiều cột.
 */
export default function BarChart({ data, height = 180, ariaLabel }: { data: BarDatum[]; height?: number; ariaLabel: string }) {
  const [hover, setHover] = useState<number | null>(null)
  const max = Math.max(1, ...data.map((d) => d.value))
  const niceMax = Math.ceil(max / 4) * 4 || 4
  const labelEvery = Math.ceil(data.length / 8)

  return (
    <figure className="relative" aria-label={ariaLabel}>
      <div className="flex gap-2">
        <div className="flex flex-col justify-between pb-6 text-right text-xs text-quaternary tabular-nums" style={{ height }}>
          {[niceMax, niceMax / 2, 0].map((v) => <span key={v}>{v}</span>)}
        </div>
        <div className="relative flex-1">
          <div className="pointer-events-none absolute inset-x-0 top-0 flex flex-col justify-between" style={{ height: height - 24 }}>
            {[0, 1, 2].map((i) => <div key={i} className="h-px bg-border-secondary" />)}
          </div>
          <div className="relative flex items-end gap-0.5" style={{ height: height - 24 }} onMouseLeave={() => setHover(null)}>
            {data.map((d, i) => (
              <div key={d.label} className="flex h-full flex-1 items-end" onMouseEnter={() => setHover(i)}>
                <div
                  className={`w-full rounded-t-[4px] transition-colors ${hover === i ? 'bg-brand-solid_hover' : 'bg-brand-solid'}`}
                  style={{ height: `${(d.value / niceMax) * 100}%`, minHeight: d.value ? 2 : 0 }}
                />
              </div>
            ))}
          </div>
          <div className="mt-2 flex gap-0.5 text-xs text-quaternary">
            {data.map((d, i) => (
              <span key={d.label} className="flex-1 truncate text-center">{i % labelEvery === 0 ? d.label : ''}</span>
            ))}
          </div>
          {hover !== null && (
            <div
              className="pointer-events-none absolute top-0 z-10 -translate-x-1/2 rounded-lg bg-primary px-3 py-2 text-xs shadow-lg ring-1 ring-secondary_alt"
              style={{ left: `${((hover + 0.5) / data.length) * 100}%` }}
            >
              <p className="font-semibold text-primary">{data[hover].label}</p>
              {(data[hover].details ?? [String(data[hover].value)]).map((line) => (
                <p key={line} className="whitespace-nowrap text-tertiary">{line}</p>
              ))}
            </div>
          )}
        </div>
      </div>
      <table className="sr-only">
        <tbody>{data.map((d) => <tr key={d.label}><th>{d.label}</th><td>{d.value}</td></tr>)}</tbody>
      </table>
    </figure>
  )
}
