import dayjs from 'dayjs'
import { Tag } from '../../design'
import type { Audit } from '../../mock/types'

export const fmtTime = (iso: string): string => dayjs(iso).format('DD-MM-YYYY HH:mm')

/** Chỉ % đã chọn khi tạo audit; tooltip nói mức gợi ý trên thang 100 → 30 → 10. */
export function LevelText({ audit }: { audit: Audit }) {
  const suggested = audit.levels[audit.currentLevelIndex]
  const hint = audit.percent === suggested
    ? `Theo mức gợi ý (${audit.levels.join('% → ')}%)`
    : `Tự chọn; mức gợi ý là ${suggested}% (${audit.levels.join('% → ')}%)`
  return <span className="au-level-on" title={hint}>{audit.percent}%</span>
}

export function StatusTag({ status }: { status: Audit['status'] }) {
  if (status === 'passed') return <Tag tone="green">Đạt</Tag>
  if (status === 'failed') return <Tag tone="pink">Trượt</Tag>
  return <Tag tone="orange">Đang mở</Tag>
}

export function auditCounts(a: Audit) {
  const vals = Object.values(a.results)
  const passed = vals.filter((v) => v === 'passed').length
  const returned = vals.filter((v) => v === 'returned').length
  return { total: a.sampledJobIds.length, passed, returned, pending: a.sampledJobIds.length - passed - returned }
}
