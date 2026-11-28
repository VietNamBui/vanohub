import { formatNumber } from '../../shared/utils/format'
import type { AnnotatorAnalytics } from '../jobs/types'

export interface PlottedPoint<T> {
  x: number
  y: number
  value: number
  item: T
}

/** Tóm tắt tử số / mẫu số khớp đúng với `avg_productivity.objects_per_hour` (measured_objects ÷ total_hours, D06). */
export function formatAvgProductivitySubtitle(avg: AnnotatorAnalytics['avg_productivity']): string {
  if (avg.objects_per_hour == null) {
    return 'Chưa có phiên nộp đủ dữ liệu giờ phiên ước tính'
  }
  const hoursText = avg.total_hours.toFixed(1).replace('.', ',')
  const measuredText = formatNumber(avg.measured_objects)
  if (avg.total_objects > avg.measured_objects || avg.unsubmitted_cvat_objects > 0) {
    const extra =
      avg.unsubmitted_cvat_objects > 0
        ? ` (tổng kỳ ${formatNumber(avg.total_objects)}, gồm ${formatNumber(avg.unsubmitted_cvat_objects)} chưa nộp CVAT)`
        : ` (tổng kỳ ${formatNumber(avg.total_objects)})`
    return `${measuredText} cuboid thuộc phiên đã đo ÷ ${hoursText} giờ ước tính${extra}`
  }
  return `${measuredText} cuboid ÷ ${hoursText} giờ ước tính`
}

/** Tách chuỗi điểm thành các đoạn liên tục có giá trị khác null để không vẽ 0 tại ngày thiếu dữ liệu. */
export function buildContiguousRateRuns<T>(
  points: T[],
  getValue: (item: T) => number | null,
  xOf: (idx: number) => number,
  yOf: (val: number) => number,
): PlottedPoint<T>[][] {
  const runs: PlottedPoint<T>[][] = []
  let current: PlottedPoint<T>[] = []
  points.forEach((item, idx) => {
    const value = getValue(item)
    if (value == null) {
      if (current.length > 0) {
        runs.push(current)
        current = []
      }
    } else {
      current.push({ x: xOf(idx), y: yOf(value), value, item })
    }
  })
  if (current.length > 0) runs.push(current)
  return runs
}
