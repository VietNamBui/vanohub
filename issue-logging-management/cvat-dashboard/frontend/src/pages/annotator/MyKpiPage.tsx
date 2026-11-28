import dayjs from 'dayjs'
import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useStore } from '../../mock/store'
import { jobById, onTimeStats, teamById, userStats, visibleJobs } from '../../mock/selectors'
import {
  Badge, Card, DailyBars, DotMatrix, PageTitle, StatCard, StepLine, StripedBar, Tag, TabCard, fmt, pct,
} from '../../design'

/** KPI cá nhân (annotator: `/me`, lead: `/me/kpi`); danh sách job nằm ở Hàng đợi. */
export default function MyKpiPage() {
  const s = useStore()
  const uid = s.currentUser.id
  const st = useMemo(() => userStats(s, uid), [s, uid])
  const today = s.now.slice(0, 10)

  const daily = useMemo(() => {
    const t = dayjs(today)
    return Array.from({ length: 14 }, (_, i) => {
      const date = t.subtract(13 - i, 'day').format('YYYY-MM-DD')
      return { date, value: s.kpiDaily.find((k) => k.userId === uid && k.date === date)?.editedCuboids ?? 0 }
    })
  }, [s.kpiDaily, uid, today])

  const mine = useMemo(() => visibleJobs(s, s.currentUser).filter((j) => j.annotatorId === uid), [s, uid])
  const kpi = st.kpiTarget
  const done = st.kpiToday
  const missing = Math.max(0, kpi - done)
  const reworkCuboids = mine.filter((j) => j.stage === 'anno_in_progress' && j.reworkCount > 0).reduce((n, j) => n + j.editedCuboids, 0)

  const weeks = useMemo(() => {
    /** 0 = 7 ngày gần nhất, 1 = tuần trước… ; -1 nếu ở tương lai. */
    const weekOf = (iso: string) => {
      const diff = dayjs(today).endOf('day').diff(dayjs(iso), 'day')
      return diff < 0 ? -1 : Math.floor(diff / 7)
    }
    const submits = [0, 0, 0, 0]
    const returns = [0, 0, 0, 0]
    const completed = [0, 0, 0, 0]
    for (const e of s.events) {
      const w = weekOf(e.at)
      if (w < 0 || w > 3) continue
      if (e.type === 'submit' && e.actorId === uid) submits[w] += 1
      if (e.reworkAgainst?.includes(uid)) returns[w] += 1
    }
    for (const j of mine.filter((x) => x.stage === 'ready_to_deliver' || x.stage === 'delivered')) {
      const ev = s.events.filter((e) => e.jobId === j.id && e.toStage === 'ready_to_deliver').pop()
      const w = ev ? weekOf(ev.at) : 0
      if (w >= 0 && w <= 3) completed[w] += 1
    }
    return { submits, returns, completed }
  }, [s.events, mine, uid, today])

  const rateSteps = [3, 2, 1, 0].map((w) => ({
    label: w === 0 ? 'Tuần này' : `-${w} tuần`,
    value: weeks.submits[w] ? Math.min(1, weeks.returns[w] / weeks.submits[w]) : 0,
  }))
  const completedCols = [3, 2, 1, 0].map((w) => weeks.completed[w])
  const jobsCompleted = mine.filter((j) => j.stage === 'ready_to_deliver' || j.stage === 'delivered').length
  const compare = weeks.completed[0] - weeks.completed[1]
  const peak = completedCols.indexOf(Math.max(...completedCols))

  const rejected = useMemo(() => mine.filter((j) => j.stage === 'anno_in_progress' && j.reworkCount > 0), [mine])
  const lastReturn = useMemo(() => {
    const ids = new Set(rejected.map((j) => j.id))
    return [...s.events].reverse().find((e) => ids.has(e.jobId) && e.reworkAgainst?.includes(uid) && e.reason)
  }, [s.events, rejected, uid])

  const team = teamById(s, s.currentUser.teamIds[0])
  const rank = useMemo(() => {
    if (!team) return null
    const from = dayjs(today).subtract(6, 'day').format('YYYY-MM-DD')
    const totals = team.memberIds.map((id) => ({
      id, n: s.kpiDaily.filter((k) => k.userId === id && k.date >= from && k.date <= today).reduce((a, k) => a + k.editedCuboids, 0),
    })).sort((a, b) => b.n - a.n)
    const position = totals.findIndex((t) => t.id === uid) + 1
    return { position, of: totals.length, gap: position > 1 ? totals[position - 2].n - totals[position - 1].n : 0 }
  }, [team, s.kpiDaily, uid, today])

  const onTime = useMemo(
    () => onTimeStats(s, { userIds: [uid], step: 'annotate', from: dayjs(today).subtract(29, 'day').format('YYYY-MM-DD'), to: today }),
    [s, uid, today],
  )

  const workedDays = daily.filter((d) => d.date < today && d.value > 0)
  const perDay = workedDays.length ? Math.round(workedDays.reduce((n, d) => n + d.value, 0) / workedDays.length) : 0

  const slides = [
    {
      chip: 'Thứ hạng', value: rank && rank.position ? `#${rank.position}` : '—',
      title: rank && rank.position ? `Bạn xếp hạng ${rank.position}/${rank.of} trong ${team?.name ?? 'team'} (7 ngày).` : 'Chưa có dữ liệu xếp hạng.',
      text: rank && rank.position > 1 ? `Cách hạng ${rank.position - 1} khoảng ${fmt(rank.gap)} cuboid.` : 'Bạn đang dẫn đầu team, giữ vững phong độ.',
    },
    {
      chip: 'Dự báo', value: perDay ? fmt(perDay * 7) : '—',
      title: perDay ? `Giữ nhịp ${fmt(perDay)} cuboid/ngày, cuối tuần bạn đạt khoảng ${fmt(perDay * 7)} cuboid.` : 'Chưa đủ dữ liệu để dự báo.',
      text: perDay >= kpi ? 'Nhịp trung bình đang vượt KPI ngày.' : `Cần thêm ${fmt(Math.max(0, kpi - perDay))} cuboid/ngày để đạt KPI.`,
    },
    {
      chip: 'Mẹo', value: '+',
      title: 'Nộp job sớm để QC1 kiểm tra kịp trong ngày.',
      text: 'Lần nộp đầu được cộng KPI, nộp lại sau rework không cộng thêm — hãy sửa kỹ trước khi nộp.',
    },
  ]

  return (
    <>
      <PageTitle title="KPI của tôi" />

      <div className="cvd-grid cvd-row-stats">
        <StatCard label="KPI hôm nay" value={fmt(done)} suffix={`/ ${fmt(kpi)}`} progress={{ value: done, max: kpi, tone: done >= kpi ? 'green' : 'blue' }}
          foot={missing > 0 ? `còn thiếu ${fmt(missing)} cuboid` : 'đã đạt KPI'} />
        <StatCard label="Đúng hạn (30 ngày)" value={pct(onTime.rate)}
          foot={onTime.total ? `${onTime.onTime}/${onTime.total} job · ${onTime.late} nộp trễ` : 'chưa có job nộp trong 30 ngày'} />
        <StatCard label="Tỉ lệ bị trả lại" value={`${Math.round(st.reworkRate)}%`} foot={`${rejected.length} job đang cần làm lại`} />
        <StatCard label="Job hoàn thành" value={fmt(jobsCompleted)} foot={`${compare >= 0 ? '+' : ''}${compare} so với tuần trước`} />
      </div>

      <div className="cvd-grid cvd-row-main">
        <Card title="Cuboid đã sửa theo ngày">
          <DailyBars data={daily} target={kpi} today={today} unit="cuboid" />
        </Card>
        <Card title="Cơ cấu KPI hôm nay">
          <div className="cvd-progress-row">
            <div><span>Cuboid mới sửa</span><b>{fmt(done)}</b></div>
            <StripedBar value={done} max={kpi} tone="green" />
          </div>
          <div className="cvd-progress-row">
            <div><span>Làm lại do QC trả</span><b>{fmt(reworkCuboids)}</b></div>
            <StripedBar value={reworkCuboids} max={kpi} tone="pink" />
          </div>
          <div className="cvd-progress-row">
            <div><span>Còn thiếu để đạt KPI</span><b>{fmt(missing)}</b></div>
            <StripedBar value={missing} max={kpi} tone="blue" />
          </div>
        </Card>
      </div>

      <TabCard
        title="Chi tiết"
        tabs={[
          { key: 'rejected', label: `Làm lại (${rejected.length})`, content: (
            <div className="cvd-kv">
              <span className="cvd-mid cvd-danger">{rejected.length}</span>
              <div className="cvd-rejected-list">
                {rejected.length === 0 && <span className="cvd-muted">Không có job nào cần làm lại.</span>}
                {lastReturn && (
                  <Link to={`/jobs/${lastReturn.jobId}`} style={{ color: '#555' }}>
                    {`#${jobById(s, lastReturn.jobId)?.cvatJobId ?? lastReturn.jobId} · `}
                    {lastReturn.errorCategory && <Tag tone="pink">{lastReturn.errorCategory}</Tag>}
                    <div className="cvd-muted" style={{ marginTop: 4, whiteSpace: 'normal' }}>{lastReturn.reason}</div>
                  </Link>
                )}
              </div>
            </div>) },
          { key: 'rate', label: 'Tỉ lệ trả lại theo tuần', content: <StepLine points={rateSteps} /> },
          { key: 'done', label: `Job hoàn thành (${jobsCompleted})`, content: (
            <div className="cvd-kv">
              <span className="cvd-mid">{fmt(jobsCompleted)}</span>
              <div className="cvd-kv-chart">
                {completedCols.some(Boolean) && <Badge>Nhiều nhất:&nbsp;<b>{peak === 3 ? 'Tuần này' : `-${3 - peak} tuần`}</b></Badge>}
                <DotMatrix columns={completedCols} tone="green" />
              </div>
              <div className="cvd-kv-side">
                <span className="cvd-muted">so với tuần trước</span>
                <span className="cvd-side-value">{`${compare >= 0 ? '+' : ''}${compare}`}</span>
              </div>
            </div>) },
          { key: 'rank', label: 'Thứ hạng · dự báo', content: (
            <div style={{ display: 'grid', gap: 12 }}>
              {slides.map((x) => (
                <div key={x.chip} style={{ display: 'flex', gap: 12, alignItems: 'baseline', flexWrap: 'wrap' }}>
                  <Tag tone="blue">{x.chip}</Tag>
                  <b>{x.title}</b>
                  <span className="cvd-muted">{x.text}</span>
                </div>
              ))}
            </div>) },
        ]}
      />

    </>
  )
}
