import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'

dayjs.extend(relativeTime)

export const formatDateTime = (value?: string | null) => (value ? dayjs(value).format('DD/MM/YYYY HH:mm') : '—')
export const formatDate = (value?: string | null) => (value ? dayjs(value).format('DD/MM/YYYY') : '—')
export const formatPercent = (value?: number | null) => (value == null ? '—' : `${value}%`)
export const formatNumber = (value?: number | null) => (value == null ? '—' : value.toLocaleString('vi-VN'))
/** "5 phút trước", "2 ngày trước"... (locale vi đã bật ở main.tsx). */
export const formatRelative = (value?: string | null) => (value ? dayjs(value).fromNow() : '—')
