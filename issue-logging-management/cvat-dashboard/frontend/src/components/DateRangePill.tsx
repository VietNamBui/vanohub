import { DatePicker } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { Pill } from '../design'

export interface DateRange { from: string; to: string }

/** Chọn khoảng ngày dạng pill. Giá trị 'YYYY-MM-DD' (dùng thẳng cho `statsByStage`/`keyMetrics`). */
export function DateRangePill({ value, onChange }: { value: DateRange; onChange: (v: DateRange) => void }) {
  return (
    <Pill>
      <DatePicker.RangePicker
        variant="borderless" allowClear={false} format="DD/MM/YYYY" value={[dayjs(value.from), dayjs(value.to)]}
        onChange={(v) => {
          const [a, b] = (v ?? []) as (Dayjs | null)[]
          if (a && b) onChange({ from: a.format('YYYY-MM-DD'), to: b.format('YYYY-MM-DD') })
        }}
      />
    </Pill>
  )
}
