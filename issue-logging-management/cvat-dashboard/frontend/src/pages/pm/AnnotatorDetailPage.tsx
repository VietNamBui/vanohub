import dayjs from 'dayjs'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { JobTable } from '../../components'
import { useStore } from '../../mock/store'
import { onTimeStats, overdueJobs, qcStats, ROLE_LABEL, teamById, userById, userStats } from '../../mock/selectors'
import { Badge, Card, DailyBars, fmt, PageTitle, pct, Pill, StatCard, StepLine, StripedBar, TabCard, Tag } from '../../design'
import { dailySeries, NoData, weeklyRework } from './shared'

export default function AnnotatorDetailPage() {
  const s = useStore()
  const nav = useNavigate()
  const { userId } = useParams()
  const user = userById(s, userId)
  if (!user) {
    return <><PageTitle title="Không tìm thấy người dùng" controls={<Pill onClick={() => nav('/pm')}>Về tổng quan</Pill>} /><Card><NoData text="Người dùng không tồn tại" /></Card></>
  }

  const st = userStats(s, user.id)
  const today = s.now.slice(0, 10)
  const jobs = s.jobs.filter((j) => j.annotatorId === user.id)
  const reworks = s.events.filter((e) => e.reworkAgainst?.includes(user.id)).sort((a, b) => b.at.localeCompare(a.at))
  const qc = user.isQc ? qcStats(s, user.id) : undefined
  const kpi = st.kpiTarget
  const done = st.kpiToday
  const missing = Math.max(0, kpi - done)
  const redo = jobs.filter((j) => j.stage === 'anno_in_progress' && j.reworkCount > 0).reduce((n, j) => n + j.editedCuboids, 0)
  const onTime = onTimeStats(s, { userIds: [user.id] })
  const lateHeld = overdueJobs(s, { userId: user.id })
  const series = dailySeries(s, [user.id], 14)
  const teams = user.teamIds.map((t) => teamById(s, t)?.name).filter(Boolean).join(', ')

  return (
    <>
      <PageTitle title={user.name} controls={<Pill onClick={() => nav(-1)}>← Quay lại</Pill>} />
      <div className="cvd-muted" style={{ margin: '-16px 8px 20px' }}>
        {ROLE_LABEL[user.role]}{user.isQc && <> <Tag tone="purple">QC</Tag></>}{teams && ` · ${teams}`}
      </div>

      <div className="cvd-grid cvd-row-stats">
        <StatCard label="Job đã nộp / được giao" value={`${st.submittedJobs}/${st.assignedJobs}`} foot={`${st.completionPct}% đã qua QC2`} />
        <StatCard
          label="Tỷ lệ đúng hạn" value={onTime.total === 0 ? '—' : Math.round(onTime.rate * 100)} suffix={onTime.total === 0 ? undefined : '%'}
          foot={`${lateHeld.length} job trễ hạn đang giữ · ${onTime.onTime}/${onTime.total} lượt đúng hạn`}
        />
        <StatCard label="Tỷ lệ rework" value={st.reworkRate} suffix="%" foot={`${st.reworkCount} lần trả về`} />
        {qc ? (
          <StatCard label="Tỷ lệ lọt lỗi (QC)" value={qc.missRate} suffix="%" foot={`QC1 cho qua ${fmt(qc.qc1Passed)} · bị QC2 trả ${fmt(qc.qc2Returned)}`} />
        ) : (
          <StatCard label="Cuboid 14 ngày" value={fmt(series.reduce((n, p) => n + p.value, 0))} foot={`Hôm nay ${fmt(done)} / KPI ${fmt(kpi)}`} />
        )}
      </div>

      <div className="cvd-grid cvd-row-main">
        <Card title="Cuboid đã sửa 14 ngày">
          <DailyBars data={series} target={kpi} today={today} unit="cuboid" />
        </Card>
        <Card title="KPI hôm nay">
          <div className="cvd-stat-hero">
            <span className="cvd-big">{fmt(done)}</span>
            <Badge tone={kpi && done >= kpi ? 'up' : 'plain'}>{pct(kpi ? done / kpi : 0)}</Badge>
          </div>
          <div className="cvd-muted">{`/ ${fmt(kpi)} cuboid`}{missing > 0 ? ` · còn thiếu ${fmt(missing)}` : ' · đã đạt KPI'}</div>
          <div className="cvd-separator" />
          <div className="cvd-progress-row"><div><span>Cuboid mới</span><b>{fmt(done)}</b></div><StripedBar value={done} max={kpi} tone="green" /></div>
          <div className="cvd-progress-row"><div><span>Làm lại (QC trả)</span><b>{fmt(redo)}</b></div><StripedBar value={redo} max={kpi} tone="pink" /></div>
          <div className="cvd-progress-row"><div><span>Còn thiếu để đạt KPI</span><b>{fmt(missing)}</b></div><StripedBar value={missing} max={kpi} tone="blue" /></div>
        </Card>
      </div>

      <TabCard
        title="Chi tiết"
        tabs={[
          { key: 'jobs', label: `Job (${jobs.length})`, content: <JobTable jobs={jobs} columns={['job', 'task', 'stage', 'edited', 'rework']} pageSize={10} /> },
          {
            key: 'rework', label: `Lý do rework (${reworks.length})`, content: reworks.length === 0 ? <NoData text="Chưa có rework" /> : (
              <div style={{ maxHeight: 320, overflowY: 'auto' }}>
                {reworks.slice(0, 20).map((e, i) => (
                  <div key={e.id} className="cvd-progress-row" style={{ marginTop: i === 0 ? 0 : 12 }}>
                    <div>
                      <span><Link to={`/jobs/${e.jobId}`}>#{s.jobs.find((j) => j.id === e.jobId)?.cvatJobId ?? e.jobId}</Link>{e.errorCategory && <> <Tag tone="pink">{e.errorCategory}</Tag></>}</span>
                      <span className="cvd-muted">{dayjs(e.at).format('DD/MM HH:mm')}</span>
                    </div>
                    <div className="cvd-muted">{e.reason ?? '—'} · bởi {userById(s, e.actorId)?.name}</div>
                  </div>
                ))}
              </div>
            ),
          },
          {
            key: 'trend', label: 'Tỉ lệ bị trả lại', content: (
              <>
                <StepLine points={weeklyRework(s, null, user.id)} />
                <div className="cvd-muted" style={{ marginTop: 8 }}>Theo tuần · tổng {st.reworkRate}% ({st.reworkCount} lần)</div>
              </>
            ),
          },
          ...(qc ? [{
            key: 'qc', label: 'Thống kê QC', content: (
              <>
                <div className="cvd-progress-row"><div><span>QC1 đã cho qua</span><b>{fmt(qc.qc1Passed)}</b></div><StripedBar value={qc.qc1Passed} max={Math.max(1, qc.qc1Passed)} tone="green" /></div>
                <div className="cvd-progress-row"><div><span>Bị QC2 trả lại</span><b>{fmt(qc.qc2Returned)}</b></div><StripedBar value={qc.qc2Returned} max={Math.max(1, qc.qc1Passed)} tone="pink" /></div>
                <div className="cvd-muted" style={{ marginTop: 12 }}>Tỷ lệ lọt lỗi: <b className={qc.missRate > 20 ? 'cvd-danger' : ''}>{qc.missRate}%</b></div>
              </>
            ),
          }] : []),
        ]}
      />
    </>
  )
}
