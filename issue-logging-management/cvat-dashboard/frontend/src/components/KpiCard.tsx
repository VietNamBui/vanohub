import { Delta, StatCard, fmt } from '../design'

export interface KpiCardProps {
  title: string
  value: number | string
  suffix?: string
  /** Chỉ tiêu: có `target` (số) và `value` là số thì hiện thanh tiến độ. */
  target?: number
  /** Xu hướng %, dương = tăng. */
  trend?: number
}

export function KpiCard({ title, value, suffix, target, trend }: KpiCardProps) {
  const numeric = typeof value === 'number'
  return (
    <StatCard
      label={title}
      value={numeric ? fmt(value) : value}
      suffix={suffix ?? (target !== undefined ? `/ ${fmt(target)}` : undefined)}
      badge={trend !== undefined ? <Delta current={100 + trend} previous={100} /> : undefined}
      progress={numeric && target ? { value, max: target, tone: value >= target ? 'green' : 'blue' } : undefined}
      foot={target !== undefined ? `Chỉ tiêu: ${fmt(target)}` : undefined}
    />
  )
}
