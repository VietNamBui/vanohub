import dayjs from 'dayjs'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ForecastBadge, StageFunnel } from '../../components'
import { useStore } from '../../mock/store'
import { batchForecast, deadlineStatus, jobsByStage, onTimeStats, overdueJobs, projectById, projectStats, projectTeamIds, teamById, teamStats, topErrorCategories } from '../../mock/selectors'
import {
  Card, DailyBars, DashTable, Delta, fmt, PageTitle, Pill, Rank, StatCard, StepLine, StripedBar, TabCard, Tag, Who,
} from '../../design'
import { queueBatchPath } from '../queue/queueShared'
import { activeCount, dailySeries, NoData, ProjectSelect, reworkTone, useProjectsOfPm, weekOverWeek, weeklyRework } from './shared'

export default function ProjectOverviewPage() {
  const s = useStore()
  const nav = useNavigate()
  const projects = useProjectsOfPm()
  const [pid, setPid] = useState<string | undefined>()
  const project = projectById(s, pid ?? projects[0]?.id)

  if (!project) {
    return <><PageTitle title="Tổng quan dự án" /><Card><NoData text="Bạn chưa phụ trách dự án nào" /></Card></>
  }

  const memberIds = projectTeamIds(s, project.id).flatMap((id) => teamById(s, id)?.memberIds ?? [])
  const jobIds = new Set(s.jobs.filter((j) => j.projectId === project.id).map((j) => j.id))
  const st = projectStats(s, project.id)
  const kpi = s.dataTypes.find((d) => d.id === project.dataTypeId)?.kpiPerDay ?? 0
  const today = s.now.slice(0, 10)
  const counts = Object.fromEntries(Object.entries(jobsByStage(s, project.id)).map(([k, v]) => [k, v.length]))
  const errors = topErrorCategories(s, project.id, 5)
  const teamRows = projectTeamIds(s, project.id)
    .map((id) => ({ id, name: teamById(s, id)?.name ?? id, ...teamStats(s, id, project.id) }))
    .sort((a, b) => b.editedCuboids - a.editedCuboids)
  const maxCub = Math.max(1, ...teamRows.map((r) => r.editedCuboids))
  const wow = weekOverWeek(s, memberIds)
  const active = activeCount(s, memberIds)
  const daily = dailySeries(s, memberIds, 14)
  const errMax = Math.max(1, ...errors.map((e) => e.count))

  const doneJobs = (counts.ready_to_deliver ?? 0) + (counts.delivered ?? 0)
  const left = Math.max(0, st.totalJobs - doneJobs)
  const projectBatches = s.batches.filter((b) => b.projectId === project.id && (b.status === 'in_progress' || b.status === 'in_audit' || b.status === 'ready'))
  const late = overdueJobs(s, { projectId: project.id })
  const soonCount = s.jobs.filter((j) => j.projectId === project.id && deadlineStatus(s, j) === 'due_soon').length
  const onTime = onTimeStats(s, { projectId: project.id })
  const forecastRows = projectBatches
    .map((b) => ({ id: b.id, projectId: b.projectId, datasetId: b.datasetId, name: b.name, dueAt: b.dueAt, forecast: batchForecast(s, b.id) }))
    .sort((a, b) => (a.dueAt ?? '9999').localeCompare(b.dueAt ?? '9999'))
  const riskRows = forecastRows.filter((r) => r.forecast.verdict === 'at_risk' || r.forecast.verdict === 'late')
  const onTimePct = Math.round(onTime.rate * 100)

  const teamsTable = (
    <DashTable
      rowKey="id" dataSource={teamRows} pagination={false}
      onRow={(r) => ({ onClick: () => nav(`/pm/teams/${r.id}`) })}
      columns={[
        { title: '#', width: 56, render: (_, __, i) => <Rank n={i + 1} /> },
        { title: 'Team', dataIndex: 'name', render: (n: string, r) => <Who name={n} sub={`${r.memberCount} thành viên`} /> },
        {
          title: 'Cuboid đã sửa', dataIndex: 'editedCuboids', sorter: (a, b) => a.editedCuboids - b.editedCuboids,
          render: (v: number) => <div className="cvd-cell-progress"><StripedBar value={v} max={maxCub} tone="blue" /><b>{fmt(v)}</b></div>,
        },
        { title: 'Job xong', align: 'right', sorter: (a, b) => a.completionPct - b.completionPct, render: (_, r) => `${r.completionPct}% (${r.byStage.ready_to_deliver + r.byStage.delivered}/${r.assignedJobs})` },
        {
          title: 'Làm lại', align: 'right', dataIndex: 'reworkRate', sorter: (a, b) => a.reworkRate - b.reworkRate,
          render: (v: number, r) => <Tag tone={reworkTone(v)}>{v}% · {r.reworkCount}</Tag>,
        },
      ]}
    />
  )
  const forecastTable = forecastRows.length === 0 ? <NoData text="Không có batch đang chạy" /> : (
    <DashTable
      rowKey="id" dataSource={forecastRows} pagination={false}
      onRow={(r) => ({ onClick: () => nav(queueBatchPath(r)) })}
      columns={[
        { title: 'Batch', dataIndex: 'name' },
        { title: 'Hạn giao', render: (_, r) => (r.dueAt ? dayjs(r.dueAt).format('DD/MM/YYYY HH:mm') : <span className="cvd-muted">Chưa đặt</span>) },
        { title: 'ETA', render: (_, r) => (r.forecast.etaAt ? dayjs(r.forecast.etaAt).format('DD/MM/YYYY') : '—') },
        { title: 'Còn lại', align: 'right', render: (_, r) => `${fmt(r.forecast.remainingJobs)} job` },
        { title: 'Dự báo', render: (_, r) => <ForecastBadge forecast={r.forecast} /> },
      ]}
    />
  )
  const quality = (
    <div className="cvd-grid pm-quality">
      <div>
        <div className="cvd-stat-label">Tỉ lệ rework theo tuần</div>
        <StepLine points={weeklyRework(s, jobIds)} />
      </div>
      <div>
        <div className="cvd-stat-label">Top loại lỗi</div>
        {errors.length === 0 ? <NoData text="Chưa có lỗi nào được ghi nhận" /> : errors.map((e) => (
          <div className="cvd-progress-row" key={e.category} style={{ marginTop: 10 }}>
            <div><span>{e.category}</span><b>{fmt(e.count)}</b></div>
            <StripedBar value={e.count} max={errMax} tone="pink" thin />
          </div>
        ))}
      </div>
    </div>
  )

  return (
    <>
      <style>{`.cvd-grid.pm-quality { grid-template-columns: 1fr 1fr; margin-bottom: 0; } @media (max-width: 900px) { .cvd-grid.pm-quality { grid-template-columns: 1fr; } }`}</style>
      <PageTitle title="Tổng quan dự án" controls={<><ProjectSelect value={project.id} onChange={setPid} /><Pill disabled>Xuất CSV</Pill></>} />

      <div className="cvd-grid cvd-row-stats">
        <StatCard
          label="Tiến độ" value={st.completionPct} suffix="%" progress={{ value: st.completionPct, max: 100, tone: 'green' }}
          foot={`${fmt(doneJobs)}/${fmt(st.totalJobs)} job xong · ${fmt(left)} còn lại`}
        />
        <StatCard
          label="Cuboid đã sửa" value={fmt(st.editedCuboids)} badge={<Delta current={wow.current} previous={wow.previous} />}
          foot={`7 ngày qua ${fmt(wow.current)} · tuần trước ${fmt(wow.previous)}`}
        />
        <StatCard
          label="Tỷ lệ rework" value={st.reworkRate} suffix="%"
          foot={errors[0] ? `Lỗi nhiều nhất: ${errors[0].category} (${fmt(errors[0].count)})` : 'Lần trả về / job đã nộp'}
        />
        <StatCard
          label="Job trễ hạn" value={fmt(late.length)}
          badge={late.length > 0 ? <Tag tone="pink">Cần xử lý</Tag> : undefined}
          foot={`${fmt(soonCount)} sắp trễ · đúng hạn ${onTimePct}% · ${fmt(riskRows.length)} batch có nguy cơ`}
        />
      </div>

      <div className="cvd-grid cvd-row-main">
        <Card title="Cuboid đã sửa theo ngày">
          <DailyBars
            data={daily} target={kpi * active} today={today} unit="cuboid"
            targetLabel={`Mục tiêu ${fmt(kpi * active)} (KPI ${fmt(kpi)} × ${active} annotator)`}
          />
        </Card>
        <Card title="Job theo bước">
          <StageFunnel
            counts={counts}
            onStageClick={(stage) => { if (stage === 'qc2_pending' || stage === 'qc2_in_progress' || stage === 'ready_to_deliver') nav('/audits') }}
          />
        </Card>
      </div>

      <TabCard
        title="Chi tiết dự án"
        tabs={[
          { key: 'teams', label: `Các team (${teamRows.length})`, content: teamsTable },
          { key: 'forecast', label: riskRows.length > 0 ? `Dự báo giao hàng · ${riskRows.length} nguy cơ` : 'Dự báo giao hàng', content: forecastTable },
          { key: 'quality', label: 'Chất lượng', content: quality },
        ]}
      />
    </>
  )
}
