import dayjs from 'dayjs'
import { Tooltip } from 'antd'
import type { BatchForecast } from '../mock/deadline'
import type { Tone } from '../design'

const VIEW: Record<BatchForecast['verdict'], { tone: Tone; text: (f: BatchForecast) => string }> = {
  on_track: { tone: 'green', text: () => 'Kịp hạn' },
  at_risk: { tone: 'orange', text: () => 'Có nguy cơ trễ' },
  late: { tone: 'pink', text: (f) => `Trễ ${Math.max(1, f.daysLate)} ngày` },
  done: { tone: 'green', text: () => 'Đã xong' },
  no_due: { tone: 'gray', text: () => 'Chưa đặt hạn' },
}

export function ForecastBadge({ forecast }: { forecast: BatchForecast }) {
  const v = VIEW[forecast.verdict]
  const tip = (
    <>
      <div>ETA: {forecast.etaAt ? dayjs(forecast.etaAt).format('DD/MM/YYYY HH:mm') : '—'}</div>
      <div>Tốc độ: {(Math.round(forecast.throughputPerDay * 10) / 10).toLocaleString('vi-VN')} job/ngày</div>
      <div>Còn lại: {forecast.remainingJobs} job</div>
      {forecast.dueAt && <div>Hạn giao: {dayjs(forecast.dueAt).format('DD/MM/YYYY HH:mm')}</div>}
    </>
  )
  return (
    <Tooltip title={tip}>
      <span className={`cvd-tag cvd-tag-${v.tone}`}>{v.text(forecast)}</span>
    </Tooltip>
  )
}
