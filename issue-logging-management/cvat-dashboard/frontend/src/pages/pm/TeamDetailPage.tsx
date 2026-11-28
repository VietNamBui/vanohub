import { useNavigate, useParams } from 'react-router-dom'
import { RowList, StageFunnel, kpiTone, type ListRow } from '../../components'
import { useStore } from '../../mock/store'
import { onTimeStats, overdueJobs, teamById, teamStats, userById, userStats } from '../../mock/selectors'
import { Card, DailyBars, Delta, fmt, PageTitle, Pill, Rank, StatCard, StripedBar, TabCard, Tag, Who } from '../../design'
import { activeCount, dailySeries, NoData, reworkTone, weekOverWeek } from './shared'

export default function TeamDetailPage() {
  const s = useStore()
  const nav = useNavigate()
  const { teamId } = useParams()
  const team = teamById(s, teamId)
  if (!team) {
    return <><PageTitle title="Không tìm thấy team" controls={<Pill onClick={() => nav('/pm')}>Về tổng quan</Pill>} /><Card><NoData text="Team không tồn tại" /></Card></>
  }

  const st = teamStats(s, team.id)
  const lead = userById(s, team.leadId)
  const rows = team.memberIds
    .map((id) => ({ id, name: userById(s, id)?.name ?? id, isLead: id === team.leadId, ...userStats(s, id) }))
    .sort((a, b) => b.kpiToday - a.kpiToday)
  const kpi = rows.find((r) => r.kpiTarget)?.kpiTarget ?? 0
  const active = activeCount(s, team.memberIds)
  const wow = weekOverWeek(s, team.memberIds)
  const onTime = onTimeStats(s, { teamId: team.id })
  const lateCount = overdueJobs(s, { teamId: team.id }).length
  const memberRows: ListRow[] = rows.map((r, i) => {
    const o = onTimeStats(s, { userIds: [r.id] })
    const target = r.kpiTarget || 1200
    return {
      key: r.id, tone: kpiTone(r.kpiToday, r.kpiTarget), label: `Mở ${r.name}`, onOpen: () => nav(`/pm/users/${r.id}`),
      cells: [
        <Rank n={i + 1} />,
        <Who name={r.name} sub={r.isLead ? 'Team lead' : undefined} />,
        <div className="cvd-cell-progress">
          <StripedBar value={r.kpiToday} max={target} tone={r.kpiTarget && r.kpiToday >= r.kpiTarget ? 'green' : 'blue'} thin />
          <b>{fmt(r.kpiToday)}</b><span className="cvd-muted">/ {fmt(target)}</span>
        </div>,
        <Tag tone={reworkTone(r.reworkRate)}>{r.reworkRate}% · {r.reworkCount}</Tag>,
        o.total === 0 ? <span className="cvd-muted">—</span> : <Tag tone={o.rate >= 0.9 ? 'green' : 'pink'}>{Math.round(o.rate * 100)}%</Tag>,
        `${fmt(r.submittedJobs)}/${fmt(r.assignedJobs)}`,
      ],
    }
  })

  return (
    <>
      <PageTitle title={team.name} controls={<Pill onClick={() => nav('/pm')}>← Tổng quan</Pill>} />
      <div className="cvd-grid cvd-row-stats">
        <StatCard label="Tổng job" value={fmt(st.totalJobs)} foot={`Team lead: ${lead?.name ?? '—'} · ${st.memberCount} thành viên`} />
        <StatCard label="Hoàn thành" value={st.completionPct} suffix="%" progress={{ value: st.completionPct, max: 100, tone: 'green' }} />
        <StatCard label="Cuboid đã sửa" value={fmt(st.editedCuboids)} badge={<Delta current={wow.current} previous={wow.previous} />} foot={`7 ngày qua: ${fmt(wow.current)}`} />
        <StatCard
          label="Tỷ lệ làm lại" value={st.reworkRate} suffix="%"
          foot={`${st.reworkCount} lần trả về · đúng hạn ${Math.round(onTime.rate * 100)}% · ${lateCount} job trễ · ${onTime.late} lượt trễ`}
        />
      </div>

      <div className="cvd-grid cvd-row-main">
        <Card title="Cuboid đã sửa theo ngày">
          <DailyBars
            data={dailySeries(s, team.memberIds, 14)} target={kpi * active} today={s.now.slice(0, 10)} unit="cuboid"
            targetLabel={`Mục tiêu ${fmt(kpi * active)} (KPI ${fmt(kpi)} × ${active} thành viên)`}
          />
        </Card>
        <Card title="Job theo bước"><StageFunnel counts={st.byStage} /></Card>
      </div>

      <TabCard
        title="Chi tiết team"
        tabs={[{
          key: 'members', label: `Thành viên (${rows.length})`, content: (
          <RowList
            heads={['#', 'Họ tên', 'KPI hôm nay', 'Làm lại', 'Đúng hạn', 'Job đã nộp / được giao']}
            cols="40px minmax(0,2fr) minmax(0,2fr) minmax(0,1fr) minmax(0,0.8fr) minmax(0,1fr)"
            rows={memberRows} emptyText="Team chưa có thành viên." resetKey={team.id}
          />
          ),
        }]}
      />
    </>
  )
}
