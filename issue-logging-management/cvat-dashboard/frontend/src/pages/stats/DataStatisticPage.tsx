import { useMemo, useState } from 'react'
import { Select } from 'antd'
import dayjs from 'dayjs'
import { useStore } from '../../mock/store'
import {
  batchById, dataTypeOfProject, keyMetrics, onTimeStats, projectTeamIds, statsByStage, visibleBatches, visibleProjects,
  type StatStage, type StageStatRow,
} from '../../mock/selectors'
import { DateRangePill, type DateRange } from '../../components'
import {
  Card, DailyBars, DashTable, PageTitle, Pill, Rank, Segmented, StatCard, StripedBar, Tag, Who, fmt, type DailyPoint,
} from '../../design'
import './stats.scss'

const ALL = '__all__'
const STAGE_TABS: { value: StatStage; label: string }[] = [
  { value: 'annotate', label: 'Gán nhãn' },
  { value: 'qc1', label: 'QC1' },
  { value: 'qc2', label: 'QC2 · Audit' },
]

type Preset = 'today' | '7d' | 'month'
const PRESETS: { value: Preset; label: string }[] = [
  { value: 'today', label: 'Hôm nay' },
  { value: '7d', label: '7 ngày' },
  { value: 'month', label: 'Tháng này' },
]

export default function DataStatisticPage() {
  const s = useStore()
  const today = s.now.slice(0, 10)
  const projects = visibleProjects(s, s.currentUser)
  const [projectId, setProjectId] = useState<string>(ALL)
  const [batchId, setBatchId] = useState<string>(ALL)
  const [range, setRange] = useState<DateRange>({ from: dayjs(today).subtract(6, 'day').format('YYYY-MM-DD'), to: today })
  const [preset, setPreset] = useState<Preset | null>('7d')
  const [stage, setStage] = useState<StatStage>('annotate')

  const pickPreset = (p: Preset) => {
    setPreset(p)
    const t = dayjs(today)
    if (p === 'today') setRange({ from: today, to: today })
    else if (p === '7d') setRange({ from: t.subtract(6, 'day').format('YYYY-MM-DD'), to: today })
    else setRange({ from: t.startOf('month').format('YYYY-MM-DD'), to: today })
  }

  const batches = visibleBatches(s, s.currentUser).filter((b) => projectId === ALL || b.projectId === projectId)
  const activeBatch = batchId !== ALL && batches.some((b) => b.id === batchId) ? batchId : ALL
  const filter = {
    projectId: projectId === ALL ? undefined : projectId,
    batchId: activeBatch === ALL ? undefined : activeBatch,
    from: range.from,
    to: range.to,
  }

  const metrics = keyMetrics(s, filter)
  const rows = statsByStage(s, { ...filter, stage })
  const onTimeAll = onTimeStats(s, filter)
  const onTimeOf = (userId: string) => onTimeStats(s, { ...filter, userIds: [userId], step: stage })
  const maxCuboids = Math.max(1, ...rows.map((r) => r.cuboids))

  const scopedProjects = projectId === ALL ? projects : projects.filter((p) => p.id === projectId)
  const scopedProjectIds = new Set(scopedProjects.map((p) => p.id))
  const kpiPerDay = scopedProjects.reduce((n, p) => Math.max(n, dataTypeOfProject(s, p.id)?.kpiPerDay ?? 0), 0)

  // Cuboid đã sửa theo ngày, 14 ngày kết thúc ở "đến ngày".
  // Cả dự án: cùng nguồn KPI ngày với trang Tổng quan (kpiDaily). Một batch: cộng từ lần nộp đầu của job trong batch.
  const daily: { points: DailyPoint[]; annotators: number } = useMemo(() => {
    const end = dayjs(range.to)
    const dates = Array.from({ length: 14 }, (_, i) => end.subtract(13 - i, 'day').format('YYYY-MM-DD'))
    const inWindow = (d: string) => d >= dates[0] && d <= dates[13]
    const jobMap = new Map(s.jobs.map((j) => [j.id, j] as const))
    const jobsByDay = new Map<string, Set<string>>()
    const batchValue = new Map<string, number>()
    const batchAnnotators = new Set<string>()
    for (const e of s.events) {
      if (e.type !== 'submit') continue
      const j = jobMap.get(e.jobId)
      if (!j || !scopedProjectIds.has(j.projectId)) continue
      if (activeBatch !== ALL && j.batchId !== activeBatch) continue
      const d = e.at.slice(0, 10)
      const set = jobsByDay.get(d) ?? new Set<string>()
      if (!set.has(j.id)) { set.add(j.id); batchValue.set(d, (batchValue.get(d) ?? 0) + j.editedCuboids) }
      jobsByDay.set(d, set)
      if (inWindow(d)) batchAnnotators.add(e.actorId)
    }
    if (activeBatch !== ALL) {
      return {
        points: dates.map((date) => ({ date, value: batchValue.get(date) ?? 0, secondary: jobsByDay.get(date)?.size ?? 0 })),
        annotators: batchAnnotators.size,
      }
    }
    const teamIds = new Set(scopedProjects.flatMap((p) => projectTeamIds(s, p.id)))
    const scopedUsers = new Set(s.users.filter((u) => u.role === 'annotator' && u.teamIds.some((t) => teamIds.has(t))).map((u) => u.id))
    const kpiValue = new Map<string, number>()
    const active = new Set<string>()
    for (const k of s.kpiDaily) {
      if (!scopedUsers.has(k.userId) || !inWindow(k.date)) continue
      kpiValue.set(k.date, (kpiValue.get(k.date) ?? 0) + k.editedCuboids)
      if (k.editedCuboids > 0) active.add(k.userId)
    }
    return {
      points: dates.map((date) => ({ date, value: kpiValue.get(date) ?? 0, secondary: jobsByDay.get(date)?.size ?? 0 })),
      annotators: active.size,
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.events, s.jobs, s.kpiDaily, s.users, projectId, activeBatch, range.to])

  // Thống kê theo loại dữ liệu (frame).
  const typeRows = useMemo(() => {
    const out = new Map<string, { id: string; name: string; total: number; waiting: number; ready: number; delivered: number }>()
    for (const j of s.jobs) {
      if (!scopedProjectIds.has(j.projectId)) continue
      if (activeBatch !== ALL && j.batchId !== activeBatch) continue
      const dt = dataTypeOfProject(s, j.projectId)
      if (!dt) continue
      const r = out.get(dt.id) ?? { id: dt.id, name: dt.name, total: 0, waiting: 0, ready: 0, delivered: 0 }
      r.total += j.frames
      if (j.stage === 'delivered') r.delivered += j.frames
      else if (j.stage === 'ready_to_deliver') r.ready += j.frames
      else r.waiting += j.frames
      out.set(dt.id, r)
    }
    return [...out.values()]
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.jobs, projectId, activeBatch])

  const dateLabel = range.from === range.to ? dayjs(range.from).format('DD/MM/YYYY') : `${dayjs(range.from).format('DD/MM')} – ${dayjs(range.to).format('DD/MM/YYYY')}`

  const columns = [
    { title: '#', key: 'rank', width: 56, render: (_: unknown, __: StageStatRow, i: number) => <Rank n={i + 1} /> },
    { title: 'Người làm', key: 'who', render: (_: unknown, r: StageStatRow) => <Who name={r.user.name} sub={`ID ${r.user.employeeId}`} /> },
    { title: 'Tổng job', dataIndex: 'jobs', key: 'jobs', align: 'right' as const, render: (v: number) => fmt(v) },
    {
      title: 'Tổng cuboid', key: 'cuboids', width: 200,
      render: (_: unknown, r: StageStatRow) => (
        <div className="cvd-cell-progress"><b>{fmt(r.cuboids)}</b><StripedBar value={r.cuboids} max={maxCuboids} tone="blue" thin /></div>
      ),
    },
    { title: 'Cuboid/giờ', dataIndex: 'cuboidPerHour', key: 'cph', align: 'right' as const, render: (v: number) => fmt(Math.round(v)) },
    {
      title: 'FPY', dataIndex: 'fpy', key: 'fpy', align: 'right' as const,
      render: (v: number) => <Tag tone={v >= 90 ? 'green' : 'pink'}>{Math.round(v)}%</Tag>,
    },
    {
      title: 'Đúng hạn', key: 'ontime', align: 'right' as const,
      render: (_: unknown, r: StageStatRow) => {
        const o = onTimeOf(r.user.id)
        return o.total === 0 ? <span className="cvd-muted">—</span> : <Tag tone={o.rate >= 0.9 ? 'green' : 'pink'}>{Math.round(o.rate * 100)}% · {o.onTime}/{o.total}</Tag>
      },
    },
    { title: 'Job rework', dataIndex: 'reworkJobs', key: 'rw', align: 'right' as const, render: (v: number) => fmt(v) },
    { title: 'Thời gian sửa', dataIndex: 'repairTime', key: 'rt', align: 'right' as const, render: (v: number) => `${v.toFixed(1)} giờ` },
    { title: 'Sửa TB', dataIndex: 'avgRepairTime', key: 'art', align: 'right' as const, render: (v: number) => `${v.toFixed(1)} giờ` },
  ]

  return (
    <>
      <PageTitle title="Thống kê dữ liệu" />
      <div className="st-filters" role="toolbar" aria-label="Bộ lọc thống kê">
        <div className="st-filter-group">
          <Pill className="st-pill-select">
            <Select
              variant="borderless" value={projectId} onChange={(v) => { setProjectId(v); setBatchId(ALL) }} aria-label="Dự án"
              options={[{ value: ALL, label: 'Tất cả dự án' }, ...projects.map((p) => ({ value: p.id, label: p.name }))]}
            />
          </Pill>
          <Pill className="st-pill-select">
            <Select
              variant="borderless" value={activeBatch} onChange={setBatchId} aria-label="Batch"
              options={[{ value: ALL, label: 'Tất cả batch' }, ...batches.map((b) => ({ value: b.id, label: batchById(s, b.id)?.name ?? b.id }))]}
            />
          </Pill>
        </div>
        <div className="st-filter-group">
          <Segmented<string> options={PRESETS} value={preset ?? ''} onChange={(v) => pickPreset(v as Preset)} />
          <DateRangePill value={range} onChange={(r) => { setRange(r); setPreset(null) }} />
        </div>
        <span className="st-filter-end"><Pill disabled>Xuất dữ liệu</Pill></span>
      </div>
      <div className="cvd-grid cvd-row-stats">
        <StatCard label="Số người đang làm" value={fmt(metrics.activeWorkers)} foot={`Gán nhãn ${fmt(metrics.annotate.jobs)} job · ${fmt(metrics.annotate.cuboids)} cuboid`} />
        <StatCard
          label="Job qua QC1" value={fmt(metrics.qc1.jobs)}
          foot={`${fmt(metrics.qc1.cuboids)} cuboid · ${fmt(metrics.ready.jobs)} job sẵn sàng giao (${fmt(metrics.ready.cuboids)} cuboid)`}
        />
        <StatCard
          label="Tỷ lệ đúng hạn" value={onTimeAll.total === 0 ? '—' : `${Math.round(onTimeAll.rate * 100)}%`}
          progress={{ value: onTimeAll.rate * 100, max: 100, tone: onTimeAll.rate >= 0.9 ? 'green' : 'pink' }}
          foot={`${fmt(onTimeAll.onTime)}/${fmt(onTimeAll.total)} lượt hoàn thành bước`}
        />
        <StatCard
          label="Tỷ lệ rework" value={`${Math.round(metrics.reworkRate)}%`} progress={{ value: metrics.reworkRate, max: 100, tone: 'pink' }}
          foot={`Tỷ lệ lỗi ${Math.round(metrics.errorRate)}%`}
        />
      </div>

      <div className="cvd-grid cvd-row-main">
        <Card title={`Cuboid đã sửa theo ngày · ${dateLabel}`}>
          <DailyBars
            data={daily.points} target={kpiPerDay * Math.max(1, daily.annotators)} today={today} unit="cuboid" secondaryUnit="job"
            targetLabel={`Mục tiêu ${fmt(kpiPerDay * Math.max(1, daily.annotators))} (KPI ${fmt(kpiPerDay)} × ${daily.annotators} annotator)`}
          />
        </Card>
        <Card title="Theo loại dữ liệu (frame)">
          {typeRows.length === 0 ? <div className="cvd-empty">Không có dữ liệu</div> : typeRows.map((t) => (
            <div key={t.id} className="cvd-progress-row" style={{ marginTop: 6 }}>
              <div><span>{t.name}</span><b>{fmt(t.total)}</b></div>
              <StripedBar value={t.ready + t.delivered} max={Math.max(1, t.total)} tone="green" thin />
              <div className="cvd-muted" style={{ fontSize: 13, marginTop: 8, display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 4 }}>
                <span>Đang chờ<br /><b style={{ color: 'inherit' }}>{fmt(t.waiting)}</b></span>
                <span>Sẵn sàng giao<br /><b style={{ color: 'inherit' }}>{fmt(t.ready)}</b></span>
                <span>Đã giao<br /><b style={{ color: 'inherit' }}>{fmt(t.delivered)}</b></span>
              </div>
            </div>
          ))}
        </Card>
      </div>

      <div className="st-main">
          <Card title="Bảng năng suất" extra={<Segmented options={STAGE_TABS} value={stage} onChange={setStage} />}>
            <DashTable
              className="cvd-rowlist-table" sticky={{ offsetHeader: 48 }}
              rowKey={(r: StageStatRow) => r.user.id} dataSource={rows} columns={columns}
              rowClassName={(r: StageStatRow) => (r.user.id === s.currentUser.id ? 'cvd-me' : '')}
              pagination={{ pageSize: 10, hideOnSinglePage: true }}
              locale={{ emptyText: 'Không có dữ liệu trong khoảng này' }}
            />
          </Card>
        </div>
    </>
  )
}
