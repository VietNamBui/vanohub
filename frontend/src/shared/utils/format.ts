import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'

dayjs.extend(relativeTime)

export const VN_TIME_ZONE = 'Asia/Ho_Chi_Minh'

function vnDateParts(value: string | Date): Record<string, string> | null {
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return null
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: VN_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date)
  const map: Record<string, string> = {}
  for (const part of parts) {
    if (part.type !== 'literal') map[part.type] = part.value
  }
  return map
}

/** DD/MM/YYYY HH:mm (cố định múi giờ Việt Nam UTC+7). */
export const formatDateTime = (value?: string | null) => {
  if (!value) return '—'
  const p = vnDateParts(value)
  return p ? `${p.day}/${p.month}/${p.year} ${p.hour}:${p.minute}` : '—'
}

/** DD/MM/YYYY (cố định múi giờ Việt Nam UTC+7). */
export const formatDate = (value?: string | null) => {
  if (!value) return '—'
  const p = vnDateParts(value)
  return p ? `${p.day}/${p.month}/${p.year}` : '—'
}

/** DD/MM (cố định múi giờ Việt Nam UTC+7). */
export const formatShortDate = (value?: string | null) => {
  if (!value) return '—'
  const p = vnDateParts(value)
  return p ? `${p.day}/${p.month}` : '—'
}

/** DD/MM HH:mm (cố định múi giờ Việt Nam UTC+7). */
export const formatShortDateTime = (value?: string | null) => {
  if (!value) return '—'
  const p = vnDateParts(value)
  return p ? `${p.day}/${p.month} ${p.hour}:${p.minute}` : '—'
}

/** Xuất chuỗi YYYY-MM-DDTHH:mm theo giờ Việt Nam (UTC+7) cho input datetime-local / picker. */
export const formatDateTimeLocalVN = (iso?: string | null) => {
  if (!iso) return ''
  const p = vnDateParts(iso)
  return p ? `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}` : ''
}

/** Diễn giải chuỗi YYYY-MM-DDTHH:mm là giờ Việt Nam (+07:00) và trả về UTC ISO string. */
export const parseDateTimeLocalVN = (localStr?: string | null): string | null => {
  if (!localStr) return null
  const trimmed = localStr.trim()
  if (!trimmed) return null
  const match = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})(?::(\d{2}))?$/.exec(trimmed)
  if (!match) return null
  const seconds = match[3] ?? '00'
  const date = new Date(`${match[1]}T${match[2]}:${seconds}+07:00`)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

export const formatPercent = (value?: number | null) => (value == null ? '—' : `${value}%`)
export const formatNumber = (value?: number | null) => (value == null ? '—' : value.toLocaleString('vi-VN'))
/** "5 phút trước", "2 ngày trước"... (locale vi đã bật ở main.tsx). */
export const formatRelative = (value?: string | null) => (value ? dayjs(value).fromNow() : '—')
