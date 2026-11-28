import { Select } from 'antd'
import dayjs from 'dayjs'
import { useStore } from '../../mock/store'
import { visibleProjects } from '../../mock/selectors'
import type { DashboardState } from '../../mock/types'
import { Pill, type DailyPoint, type Tone } from '../../design'

export function NoData({ text = 'Chưa có dữ liệu' }: { text?: string }) {
  return <div className="cvd-empty">{text}</div>
}

/** Dự án mà PM hiện tại nhìn thấy. */
export function useProjectsOfPm() {
  const s = useStore()
  return visibleProjects(s, s.currentUser)
}

/** Chọn dự án, bọc trong Pill kiểu CVAT. */
export function ProjectSelect({ value, onChange }: { value?: string; onChange: (id: string) => void }) {
  const projects = useProjectsOfPm()
  return (
    <Pill>
      <Select
        variant="borderless" style={{ minWidth: 200, maxWidth: '100%' }} value={value} onChange={onChange} placeholder="Chọn dự án"
        options={projects.map((p) => ({ value: p.id, label: p.name }))}
      />
    </Pill>
  )
}

/** Tag rework: xanh ≤10%, hồng >20%, cam ở giữa. `rate` là 0–100. */
export function reworkTone(rate: number): Tone {
  return rate <= 10 ? 'green' : rate > 20 ? 'pink' : 'orange'
}

/** Tổng cuboid đã sửa mỗi ngày (cũ → mới) của một nhóm user, `days` ngày kết thúc ở hôm nay. */
export function dailySeries(s: DashboardState, userIds: string[], days = 14): DailyPoint[] {
  const today = s.now.slice(0, 10)
  const set = new Set(userIds)
  return Array.from({ length: days }, (_, i) => {
    const date = dayjs(today).subtract(days - 1 - i, 'day').format('YYYY-MM-DD')
    const value = s.kpiDaily.filter((k) => k.date === date && set.has(k.userId)).reduce((n, k) => n + k.editedCuboids, 0)
    return { date, value }
  })
}

/** Số user trong nhóm có phát sinh cuboid trong `days` ngày gần nhất (tối thiểu 1). */
export function activeCount(s: DashboardState, userIds: string[], days = 14): number {
  const from = dayjs(s.now.slice(0, 10)).subtract(days - 1, 'day').format('YYYY-MM-DD')
  const set = new Set(userIds)
  const active = new Set(s.kpiDaily.filter((k) => k.date >= from && set.has(k.userId) && k.editedCuboids > 0).map((k) => k.userId))
  return Math.max(1, active.size)
}

/** Tỉ lệ rework theo tuần (0–1): sự kiện rework / lượt nộp lần đầu trong tuần. `jobIds` null = mọi job. */
export function weeklyRework(s: DashboardState, jobIds: Set<string> | null, userId?: string, weeks = 5): { label: string; value: number }[] {
  const end = dayjs(s.now)
  return Array.from({ length: weeks }, (_, i) => {
    const to = end.subtract((weeks - 1 - i) * 7, 'day')
    const from = to.subtract(7, 'day')
    const inWeek = (at: string) => { const t = dayjs(at); return t.isAfter(from) && !t.isAfter(to) }
    const scoped = s.events.filter((e) => (!jobIds || jobIds.has(e.jobId)) && inWeek(e.at))
    const reworks = scoped.filter((e) => e.reworkAgainst?.length && (!userId || e.reworkAgainst.includes(userId))).length
    const submits = scoped.filter((e) => e.type === 'submit' && (!userId || e.actorId === userId)).length
    return { label: to.format('DD/MM'), value: submits ? Math.min(1, reworks / submits) : 0 }
  })
}

/** Tổng cuboid của nhóm user trong 7 ngày gần nhất và 7 ngày trước đó. */
export function weekOverWeek(s: DashboardState, userIds: string[]): { current: number; previous: number } {
  const d = dailySeries(s, userIds, 14)
  const sum = (a: DailyPoint[]) => a.reduce((n, p) => n + p.value, 0)
  return { previous: sum(d.slice(0, 7)), current: sum(d.slice(7)) }
}
