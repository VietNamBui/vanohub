import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { Table } from 'antd'
import type { TableProps } from 'antd'
import { MoreOutlined } from '@ant-design/icons'
import './dashboard.scss'

export const fmt = (n: number): string => n.toLocaleString('vi-VN')
/** rate là tỉ lệ 0–1 → "12%". */
export const pct = (rate: number): string => `${Math.round(rate * 100)}%`

export type Tone = 'blue' | 'pink' | 'gray' | 'green' | 'orange' | 'purple'

/* ---------- Card ---------- */
export interface CardProps {
  title?: ReactNode
  extra?: ReactNode
  className?: string
  children: ReactNode
  /** Có truyền ⇒ vẽ nút "⋯" bấm được; không truyền ⇒ không vẽ nút. */
  onMore?: () => void
}

/** Biểu đồ cột mini một dòng (cao 24px) cho ô bảng: mỗi cột một giá trị, xanh khi đạt mục tiêu, hồng khi chưa. */
export function MiniBars({ values, target, title }: { values: number[]; target: number; title?: (v: number, i: number) => string }) {
  const max = Math.max(target, ...values, 1)
  return (
    <span className="cvd-minibars" aria-label="Biểu đồ mini">
      {values.map((v, i) => (
        <i
          key={i} title={title?.(v, i) ?? fmt(v)}
          className={target > 0 && v >= target ? 'met' : 'missed'}
          style={{ height: `${Math.max(8, (v / max) * 100)}%` }}
        />
      ))}
    </span>
  )
}

/**
 * Một thẻ chứa nhiều nội dung thay phiên bằng tab (Segmented ở góc phải tiêu đề) — dùng để gom các khối
 * phụ của trang thay vì xếp chồng nhiều thẻ làm trang dài. Tab chưa chọn không render.
 */
export interface TabCardTab { key: string; label: ReactNode; content: ReactNode }
export function TabCard({ title, tabs, defaultKey, className }: { title: ReactNode; tabs: TabCardTab[]; defaultKey?: string; className?: string }) {
  const [active, setActive] = useState(defaultKey ?? tabs[0]?.key)
  const current = tabs.find((t) => t.key === active) ?? tabs[0]
  return (
    <Card
      title={title} className={`cvd-tabcard ${className ?? ''}`}
      extra={tabs.length > 1 ? <Segmented options={tabs.map((t) => ({ value: t.key, label: t.label }))} value={current?.key ?? ''} onChange={setActive} /> : undefined}
    >
      {current?.content}
    </Card>
  )
}

export function Card({ title, extra, className, children, onMore }: CardProps) {
  return (
    <div className={`cvd-card ${className ?? ''}`}>
      {title !== undefined && (
        <div className="cvd-card-header">
          <h3>{title}</h3>
          <div className="cvd-card-extra">
            {extra}
            {onMore && (
              <button type="button" className="cvd-dots" aria-label="Thêm" onClick={onMore} style={{ background: 'transparent', cursor: 'pointer' }}>
                <MoreOutlined rotate={90} />
              </button>
            )}
          </div>
        </div>
      )}
      {children}
    </div>
  )
}

/* ---------- Badge / Delta ---------- */
export function Badge({ children, tone = 'plain' }: { children: ReactNode; tone?: 'up' | 'down' | 'plain' }) {
  return (
    <span className={`cvd-badge cvd-badge-${tone}`}>
      {tone === 'up' && <b>▲</b>}
      {tone === 'down' && <b>▼</b>}
      {children}
    </span>
  )
}

export function Delta({ current, previous }: { current: number; previous: number }) {
  if (!previous) return null
  const change = (current - previous) / previous
  return <Badge tone={change >= 0 ? 'up' : 'down'}>{pct(Math.abs(change))}</Badge>
}

/* ---------- StripedBar ---------- */
export function StripedBar({ value, max, tone, thin }: { value: number; max: number; tone: 'blue' | 'green' | 'pink'; thin?: boolean }) {
  const width = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <div className={`cvd-track ${thin ? 'cvd-track-thin' : ''}`}>
      <div className={`cvd-fill cvd-stripes-${tone}`} style={{ width: `${width}%` }} />
    </div>
  )
}

/* ---------- DailyBars ---------- */
export interface DailyPoint { date: string; value: number; secondary?: number }
export interface DailyBarsProps {
  data: DailyPoint[]
  /** Mức KPI/ngày (đường xanh đứt nét). */
  target: number
  /** 'YYYY-MM-DD' của hôm nay. */
  today: string
  /** Đơn vị giá trị chính, vd 'cuboid'. */
  unit?: string
  /** Đơn vị giá trị phụ (nếu có `secondary`), vd 'job'. */
  secondaryUnit?: string
  /** Nhãn chip KPI. Mặc định "KPI {target} / ngày". */
  targetLabel?: string
}

export function DailyBars({ data, target, today, unit = 'object', secondaryUnit = 'item', targetLabel }: DailyBarsProps) {
  const [hovered, setHovered] = useState<number | null>(null)
  const max = Math.max(target * 1.3, ...data.map((d) => d.value), 1)
  const ticks = [1, 0.75, 0.5, 0.25, 0].map((f) => Math.round(max * f))
  const todayIndex = data.findIndex((d) => d.date === today)
  const active = hovered ?? (todayIndex >= 0 ? todayIndex : null)
  const kind = (d: DailyPoint) => (d.date === today ? 'today' : d.date > today ? 'future' : d.value >= target ? 'met' : 'missed')

  return (
    <div className="cvd-daily">
      <div className="cvd-daily-plot">
        <div className="cvd-daily-yaxis">
          {ticks.map((t) => <span key={t}>{t >= 1000 ? `${(t / 1000).toFixed(1)}k` : t}</span>)}
        </div>
        <div className="cvd-daily-goal" style={{ bottom: `${(target / max) * 100}%` }}>
          <span>{targetLabel ?? `KPI ${fmt(target)} / ngày`}</span>
        </div>
        {data.map((d, i) => (
          <div key={d.date} className="cvd-daily-slot" onMouseEnter={() => setHovered(i)} onMouseLeave={() => setHovered(null)}>
            {active === i && <div className="cvd-daily-highlight" />}
            <div
              className={`cvd-daily-bar cvd-daily-bar-${kind(d)}`}
              style={{ height: `${Math.max(d.date > today ? 4 : 1.5, (d.value / max) * 100)}%` }}
            />
            {active === i && d.date <= today && (
              <div className={`cvd-tooltip ${i > data.length * 0.6 ? 'left' : ''}`} style={{ bottom: `${Math.min(80, (d.value / max) * 100 + 4)}%` }}>
                {d.date === today ? 'Hôm nay' : `Ngày ${Number(d.date.slice(8))}`}
                {' · '}<b>{fmt(d.value)}</b>{` ${unit}`}
                {d.secondary !== undefined && <>{' | '}<b>{fmt(d.secondary)}</b>{` ${secondaryUnit}`}</>}
                {d.value < target && <>{' | còn thiếu: '}<b>{fmt(target - d.value)}</b></>}
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="cvd-daily-xaxis">
        {data.map((d, i) => {
          const day = Number(d.date.slice(8))
          return <span key={d.date}>{day === 1 || day % 5 === 0 || i === todayIndex ? day : ''}</span>
        })}
      </div>
      <div className="cvd-legend">
        <span><i className="met" />Đạt KPI</span>
        <span><i className="missed" />Chưa đạt</span>
        <span><i className="today" />Hôm nay</span>
      </div>
    </div>
  )
}

/* ---------- StepLine ---------- */
export function StepLine({ points, format = pct }: { points: { label: string; value: number }[]; format?: (v: number) => string }) {
  const W = 320
  const H = 170
  const top = 20
  const max = Math.max(0.3, ...points.map((p) => p.value)) * 1.15
  const step = W / Math.max(1, points.length)
  const y = (v: number) => H - (v / max) * (H - top)
  let path = ''
  points.forEach((p, i) => { path += `${i === 0 ? 'M' : 'L'}${i * step} ${y(p.value)} H${(i + 1) * step} ` })
  const last = points[points.length - 1]
  return (
    <div className="cvd-stepline">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        <defs>
          <pattern id="cvd-vstripes" width="5" height="5" patternUnits="userSpaceOnUse"><rect width="2" height="5" fill="#f9c6dc" /></pattern>
        </defs>
        <path d={`${path} V${H} H0 Z`} fill="url(#cvd-vstripes)" opacity="0.75" />
        <path d={path} fill="none" stroke="#f0438a" strokeWidth="3" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        {last && <circle cx={W - step / 2} cy={y(last.value)} r="5" fill="#f0438a" stroke="#fff" strokeWidth="2" />}
      </svg>
      {last && <span className="cvd-badge cvd-badge-plain cvd-stepline-value">{format(last.value)}</span>}
      <div className="cvd-stepline-x">{points.map((p) => <span key={p.label}>{p.label}</span>)}</div>
    </div>
  )
}

/* ---------- DotMatrix ---------- */
export function DotMatrix({ columns, tone }: { columns: number[]; tone: 'green' | 'blue' }) {
  const peak = Math.max(...columns, 0)
  return (
    <div className={`cvd-dots-matrix cvd-dots-${tone}`}>
      {columns.map((n, i) => (
        <div key={i} className={`cvd-dots-col ${n === peak && n > 0 ? 'peak' : ''}`}>
          {Array.from({ length: Math.max(1, n) }).map((_, k) => <i key={k} className={n === 0 ? 'empty' : ''} />)}
        </div>
      ))}
    </div>
  )
}

/* ---------- InsightCard ---------- */
export interface InsightSlide { title: string; text?: string; value?: ReactNode; chip?: string }
export function InsightCard({ title, slides, intervalMs = 6000, className }: { title?: ReactNode; slides: InsightSlide[]; intervalMs?: number; className?: string }) {
  const [i, setI] = useState(0)
  const n = slides.length
  useEffect(() => {
    if (n < 2) return
    const t = setTimeout(() => setI((k) => (k + 1) % n), intervalMs)
    return () => clearTimeout(t)
  }, [i, n, intervalMs])
  const slide = slides[Math.min(i, n - 1)]
  if (!slide) return null
  return (
    <div className={`cvd-card cvd-insight ${className ?? ''}`}>
      {(slide.chip ?? title) !== undefined && <div className="cvd-chip">{slide.chip ?? title}</div>}
      <div className="cvd-insight-slide" key={i}>
        {slide.value !== undefined && <div className="cvd-insight-value">{slide.value}</div>}
        <h4>{slide.title}</h4>
        {slide.text && <p>{slide.text}</p>}
      </div>
      {n > 1 && (
        <div className="cvd-steps">
          {slides.map((s, k) => (
            <button key={s.title} type="button" aria-label={`Slide ${k + 1}`} className={k === i ? 'on' : ''} onClick={() => setI(k)}>
              <i style={k === i ? { animationDuration: `${intervalMs}ms` } : undefined} />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/* ---------- StatCard ---------- */
export interface StatCardProps {
  label: ReactNode
  value: ReactNode
  /** Phần mờ sau số, vd "/ 1.200". */
  suffix?: ReactNode
  foot?: ReactNode
  badge?: ReactNode
  /** Có ⇒ hiện thanh sọc tiến độ value/target (chỉ khi value là số). */
  progress?: { value: number; max: number; tone?: 'blue' | 'green' | 'pink' }
  className?: string
}
export function StatCard({ label, value, suffix, foot, badge, progress, className }: StatCardProps) {
  return (
    <div className={`cvd-card ${className ?? ''}`}>
      <div className="cvd-stat-label">{label}</div>
      <div className="cvd-stat-hero">
        <span className="cvd-mid">{value}</span>
        {suffix !== undefined && <span className="cvd-stat-suffix">{suffix}</span>}
        {badge}
      </div>
      {progress && <div style={{ marginTop: 14 }}><StripedBar value={progress.value} max={progress.max} tone={progress.tone ?? 'blue'} thin /></div>}
      {foot !== undefined && <div className="cvd-stat-foot">{foot}</div>}
    </div>
  )
}

/* ---------- Segmented / PageTitle / Pill ---------- */
export function Segmented<T extends string>({ options, value, onChange }: { options: { value: T; label: ReactNode }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="cvd-segmented" role="tablist">
      {options.map((o) => (
        <button key={o.value} type="button" role="tab" aria-selected={o.value === value} className={o.value === value ? 'on' : ''} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

export interface PageTitleProps<T extends string = string> {
  title: ReactNode
  tabs?: { options: { value: T; label: ReactNode }[]; value: T; onChange: (v: T) => void }
  /** Điều khiển bên phải (Pill, Select…). */
  controls?: ReactNode
}
/**
 * Tab con của khu (space) đang mở — AppLayout cung cấp, PageTitle vẽ ở bên phải hàng tiêu đề.
 * Trang nằm trong khu có ≥ 2 tab PHẢI dùng PageTitle, nếu không tab con sẽ không hiện.
 */
export const SpaceTabsContext = createContext<ReactNode>(null)

export function PageTitle<T extends string = string>({ title, tabs, controls }: PageTitleProps<T>) {
  const spaceTabs = useContext(SpaceTabsContext)
  return (
    <div className="cvd-title">
      <h1>{title}</h1>
      {tabs && <Segmented {...tabs} />}
      {(spaceTabs || controls) && (
        <div className="cvd-controls">
          {controls}
          {spaceTabs}
        </div>
      )}
    </div>
  )
}

/** Viên thuốc bo tròn; `disabled` ⇒ mờ, không bấm. Bọc AntD Select/DatePicker bên trong cũng được. */
export function Pill({ children, disabled, onClick, className }: { children: ReactNode; disabled?: boolean; onClick?: () => void; className?: string }) {
  return (
    <span
      className={`cvd-pill ${disabled ? 'cvd-pill-disabled' : ''} ${className ?? ''}`}
      onClick={disabled ? undefined : onClick}
      style={onClick && !disabled ? { cursor: 'pointer' } : undefined}
    >
      {children}
    </span>
  )
}

/* ---------- Tag / Rank / Who ---------- */
export function Tag({ tone = 'gray', solid, children }: { tone?: Tone; solid?: boolean; children: ReactNode }) {
  return <span className={`cvd-tag cvd-tag-${solid ? 'solid-' : ''}${tone}`}>{children}</span>
}

export function Rank({ n }: { n: number }) {
  return <span className={`cvd-rank ${n <= 3 ? `cvd-rank-${n}` : ''}`}>{n}</span>
}

const AVATAR_COLORS = ['#1d6ff2', '#2fae32', '#f0438a', '#e8780f', '#7c3aed', '#0ea5a4', '#d4a017', '#6366f1']
export function avatarColor(name: string): string {
  let h = 0
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0
  return AVATAR_COLORS[h % AVATAR_COLORS.length]
}
export function Who({ name, sub }: { name: string; sub?: ReactNode }) {
  return (
    <span className="cvd-who">
      <i style={{ background: avatarColor(name) }} />
      <span>{name}{sub !== undefined && <span className="cvd-muted" style={{ marginLeft: 8 }}>{sub}</span>}</span>
    </span>
  )
}

/* ---------- DashTable ---------- */
/** AntD Table với giao diện bảng CVAT. Dòng "tôi": `rowClassName={(r) => (r.id === me ? 'cvd-me' : '')}`. */
/**
 * Tiêu đề cột không xuống dòng; bảng `sticky` của AntD tách header ra bảng riêng và lấy độ rộng cột theo ô thân bảng,
 * nên cột có dữ liệu ngắn (vd "2") cắt mất tiêu đề. `min-width` trên <col> bị trình duyệt bỏ qua ⇒ đặt min-width vào
 * chính ô thân bảng. Chỉ áp cho cột tiêu đề chữ chưa đặt width (13px ≈ 7.5px/ký tự + padding 32px).
 */
function withHeaderMinWidth<T>(columns: TableProps<T>['columns']): TableProps<T>['columns'] {
  return columns?.map((c) => {
    if (typeof c.title !== 'string' || c.width != null) return c
    const minWidth = Math.ceil(c.title.length * 7.5) + 32
    return {
      ...c,
      onCell: (record: T, index?: number) => {
        const props = c.onCell?.(record, index) ?? {}
        return { ...props, style: { minWidth, ...props.style } }
      },
    }
  })
}

export function DashTable<T extends object>({ className, size = 'middle', pagination, columns, ...rest }: TableProps<T>) {
  const clickable = Boolean(rest.onRow)
  return (
    <Table<T>
      size={size}
      pagination={pagination ?? false}
      scroll={{ x: 'max-content', ...rest.scroll }}
      className={`cvd-table ${clickable ? 'cvd-table-click' : ''} ${className ?? ''}`}
      columns={withHeaderMinWidth(columns)}
      {...rest}
    />
  )
}

