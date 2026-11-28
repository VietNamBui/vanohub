import { useRef } from 'react'
import dayjs, { type Dayjs } from 'dayjs'
import { DatePicker, TimePicker } from 'antd'

export interface DueEditorProps {
  /** ISO hoặc null (chưa đặt). */
  value: string | null
  /** Trả ISO, hoặc null khi xoá. */
  onChange: (iso: string | null) => void
  allowClear?: boolean
}

const DEFAULT_HOUR = 17

/** Chọn ngày + giờ hạn. Chọn ngày trước (giờ mặc định 17:00); chọn giờ khi chưa có ngày bị khoá. */
export function DueEditor({ value, onChange, allowClear = false }: DueEditorProps) {
  const cur: Dayjs | null = value ? dayjs(value) : null
  // DatePicker có thể báo onChange hai lần liền cho cùng giá trị (gõ tay rồi Enter), lần hai đến trước khi
  // `value` kịp cập nhật ⇒ so với giá trị vừa phát (ref), không chỉ với `value`.
  const lastEmitted = useRef<string | null>(null)
  const emit = (d: Dayjs) => {
    const iso = d.second(0).millisecond(0).toISOString()
    if (iso === lastEmitted.current || (cur && cur.toISOString() === iso)) return
    lastEmitted.current = iso
    onChange(iso)
  }
  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      <DatePicker
        value={cur} format="DD/MM/YYYY" allowClear={allowClear} placeholder="Chọn ngày"
        onChange={(d) => {
          if (!d) { onChange(null); return }
          emit(d.hour(cur ? cur.hour() : DEFAULT_HOUR).minute(cur ? cur.minute() : 0))
        }}
      />
      <TimePicker
        value={cur} format="HH:mm" allowClear={false} placeholder="Giờ" disabled={!cur}
        onChange={(t) => { if (t && cur) emit(cur.hour(t.hour()).minute(t.minute())) }}
      />
    </div>
  )
}
