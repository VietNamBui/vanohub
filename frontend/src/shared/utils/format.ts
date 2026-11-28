export const APP_TIME_ZONE = 'Asia/Ho_Chi_Minh'
export const VN_TIME_ZONE = APP_TIME_ZONE

const ISO_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/
const LOCAL_DATETIME_RE = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})(?::(\d{2}))?$/
const RELATIVE_TIME_FORMAT = new Intl.RelativeTimeFormat('vi', { numeric: 'auto' })
const WALL_CLOCK_FORMAT = new Intl.DateTimeFormat('en-CA', {
  timeZone: APP_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
})

interface WallClockParts {
  year: string
  month: string
  day: string
  hour: string
  minute: string
}

function parseIsoDateOnly(value: string): { year: string; month: string; day: string } | null {
  const match = ISO_DATE_RE.exec(value.trim())
  if (!match) return null
  const [, year, month, day] = match
  const y = Number(year)
  const m = Number(month)
  const d = Number(day)
  const check = new Date(Date.UTC(y, m - 1, d))
  if (check.getUTCFullYear() !== y || check.getUTCMonth() !== m - 1 || check.getUTCDate() !== d) {
    return null
  }
  return { year, month, day }
}

function parseTimestamp(value?: string | Date | null): Date | null {
  if (!value) return null
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  const text = value.trim()
  if (!text) return null
  const parsed = new Date(text)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function getVnParts(date: Date): WallClockParts {
  const map: Record<string, string> = {}
  for (const part of WALL_CLOCK_FORMAT.formatToParts(date)) {
    if (part.type !== 'literal') map[part.type] = part.value
  }
  return {
    year: map.year ?? '0000',
    month: map.month ?? '01',
    day: map.day ?? '01',
    hour: map.hour === '24' ? '00' : (map.hour ?? '00'),
    minute: map.minute ?? '00',
  }
}

export function getCurrentHourVN(at: Date = new Date()): number {
  return Number(getVnParts(at).hour)
}

/** DD/MM/YYYY HH:mm (cố định múi giờ Việt Nam UTC+7). */
export function formatDateTime(value?: string | null): string {
  const date = parseTimestamp(value)
  if (!date) return '—'
  const p = getVnParts(date)
  return `${p.day}/${p.month}/${p.year} ${p.hour}:${p.minute}`
}

/** DD/MM/YYYY (cố định múi giờ Việt Nam UTC+7). */
export function formatDate(value?: string | null): string {
  if (!value) return '—'
  if (ISO_DATE_RE.test(value.trim())) {
    const dateOnly = parseIsoDateOnly(value)
    return dateOnly ? `${dateOnly.day}/${dateOnly.month}/${dateOnly.year}` : '—'
  }
  const date = parseTimestamp(value)
  if (!date) return '—'
  const p = getVnParts(date)
  return `${p.day}/${p.month}/${p.year}`
}

/** DD/MM (cố định múi giờ Việt Nam UTC+7). */
export function formatShortDate(value?: string | null): string {
  if (!value) return '—'
  if (ISO_DATE_RE.test(value.trim())) {
    const dateOnly = parseIsoDateOnly(value)
    return dateOnly ? `${dateOnly.day}/${dateOnly.month}` : '—'
  }
  const date = parseTimestamp(value)
  if (!date) return '—'
  const p = getVnParts(date)
  return `${p.day}/${p.month}`
}

/** DD/MM HH:mm (cố định múi giờ Việt Nam UTC+7). */
export function formatShortDateTime(value?: string | null): string {
  const date = parseTimestamp(value)
  if (!date) return '—'
  const p = getVnParts(date)
  return `${p.day}/${p.month} ${p.hour}:${p.minute}`
}

/** HH:mm · DD/MM/YYYY (cố định múi giờ Việt Nam UTC+7). */
export function formatTimeFirstDateTime(value?: string | null): string {
  const date = parseTimestamp(value)
  if (!date) return '—'
  const p = getVnParts(date)
  return `${p.hour}:${p.minute} · ${p.day}/${p.month}/${p.year}`
}

/** Xuất chuỗi YYYY-MM-DDTHH:mm theo giờ Việt Nam (UTC+7) cho input datetime-local. */
export function formatDateTimeLocalVN(iso?: string | null): string {
  const date = parseTimestamp(iso)
  if (!date) return ''
  const p = getVnParts(date)
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`
}

/** Diễn giải chuỗi YYYY-MM-DDTHH:mm là giờ Việt Nam (+07:00) và trả về UTC ISO string. */
export function parseDateTimeLocalVN(localStr?: string | null): string | null {
  if (!localStr) return null
  const trimmed = localStr.trim()
  if (!trimmed) return null
  const match = LOCAL_DATETIME_RE.exec(trimmed)
  if (!match) return null
  const seconds = match[3] ?? '00'
  const date = new Date(`${match[1]}T${match[2]}:${seconds}+07:00`)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

export function formatCsvTimestamp(at: Date = new Date()): string {
  const p = getVnParts(at)
  return `${p.day}/${p.month}/${p.year} ${p.hour}:${p.minute} (UTC+7)`
}

export function formatCsvFileDate(at: Date = new Date()): string {
  const p = getVnParts(at)
  return `${p.year}${p.month}${p.day}`
}

export const formatPercent = (value?: number | null) => (value == null ? '—' : `${value}%`)
export const formatViPercent = (value?: number | null) =>
  value == null ? '—' : `${new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 1 }).format(value)}%`
export const formatNumber = (value?: number | null) => (value == null ? '—' : value.toLocaleString('vi-VN'))

/** "5 phút trước", "2 ngày trước"... dùng Native Intl.RelativeTimeFormat('vi'). */
export function formatRelative(value?: string | null): string {
  const date = parseTimestamp(value)
  if (!date) return '—'
  const diffSec = Math.round((date.getTime() - Date.now()) / 1000)
  const absSec = Math.abs(diffSec)
  if (absSec < 45) return RELATIVE_TIME_FORMAT.format(diffSec, 'second')
  const diffMin = Math.round(diffSec / 60)
  if (Math.abs(diffMin) < 60) return RELATIVE_TIME_FORMAT.format(diffMin, 'minute')
  const diffHour = Math.round(diffSec / 3600)
  if (Math.abs(diffHour) < 24) return RELATIVE_TIME_FORMAT.format(diffHour, 'hour')
  const diffDay = Math.round(diffSec / 86_400)
  if (Math.abs(diffDay) < 30) return RELATIVE_TIME_FORMAT.format(diffDay, 'day')
  const diffMonth = Math.round(diffSec / 2_592_000)
  if (Math.abs(diffMonth) < 12) return RELATIVE_TIME_FORMAT.format(diffMonth, 'month')
  return RELATIVE_TIME_FORMAT.format(Math.round(diffSec / 31_536_000), 'year')
}
