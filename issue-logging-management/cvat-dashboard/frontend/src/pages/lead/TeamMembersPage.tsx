import { Select } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { RowList, kpiTone, type ListRow } from '../../components'
import { Card, DailyBars, MiniBars, PageTitle, Pill, Rank, StatCard, StripedBar, Tag, Who, fmt } from '../../design'
import { useStore } from '../../mock/store'
import { onTimeStats, overdueJobs, teamById, userStats, visibleTeams, type UserStats } from '../../mock/selectors'
import type { User } from '../../mock/types'

type Row = { user: User; st: UserStats; inHand: number; kpiPct: number; onTime: { total: number; rate: number }; late: number }

export default function TeamMembersPage() {
  const s = useStore()
  const nav = useNavigate()
  const teams = visibleTeams(s, s.currentUser)
  const [teamId, setTeamId] = useState<string | undefined>()
  const activeId = teamId && teams.some((t) => t.id === teamId) ? teamId : teams[0]?.id
  const team = teamById(s, activeId)
  if (!team) {
    return (
      <>
        <PageTitle title="Thành viên team" />
        <Card><div className="cvd-empty">Bạn chưa thuộc team nào.</div></Card>
      </>
    )
  }

  const thirtyAgo = new Date(new Date(s.now).getTime() - 30 * 86400000).toISOString()
  const rows: Row[] = s.users.filter((u) => team.memberIds.includes(u.id)).map((user) => {
    const st = userStats(s, user.id)
    return {
      user, st,
      inHand: s.jobs.filter((j) => j.annotatorId === user.id && j.stage === 'anno_in_progress').length,
      onTime: onTimeStats(s, { userIds: [user.id], from: thirtyAgo, to: s.now, step: 'annotate' }),
      late: overdueJobs(s, { userId: user.id }).length,
      kpiPct: st.kpiTarget ? Math.round((st.kpiToday / st.kpiTarget) * 100) : 0,
    }
  }).sort((a, b) => b.st.kpiToday - a.st.kpiToday)

  const totalToday = rows.reduce((a, r) => a + r.st.kpiToday, 0)
  const totalTarget = rows.reduce((a, r) => a + r.st.kpiTarget, 0)
  const metCount = rows.filter((r) => r.st.kpiTarget > 0 && r.st.kpiToday >= r.st.kpiTarget).length
  const avgRework = rows.length ? Math.round(rows.reduce((a, r) => a + r.st.reworkRate, 0) / rows.length) : 0
  const belowHalf = rows.filter((r) => r.kpiPct < 50).length
  const lateTotal = rows.reduce((a, r) => a + r.late, 0)
  const top = rows[0]
  const holding = rows.reduce((a, r) => a + r.inHand, 0)
  const today = s.now.slice(0, 10)
  const daily = (rows[0]?.st.kpiWeek ?? []).map((d, i) => ({
    date: d.date,
    value: rows.reduce((a, r) => a + r.st.kpiWeek[i].editedCuboids, 0),
  }))

  const listRows: ListRow[] = rows.map((r, i) => ({
    key: r.user.id, tone: kpiTone(r.st.kpiToday, r.st.kpiTarget), label: `Mở ${r.user.name}`,
    onOpen: () => nav(`/pm/users/${r.user.id}`),
    cells: [
      <Rank n={i + 1} />,
      <span className="cvd-rowlist-inline">
        <Who name={r.user.name} />
        {r.user.id === s.currentUser.id && <Tag tone="gray">Bạn</Tag>}
        {r.user.role === 'lead' && <Tag tone="blue">Team lead</Tag>}
        {r.user.isQc && <Tag tone="purple">QC</Tag>}
      </span>,
      <div className="cvd-cell-progress">
        <StripedBar value={r.st.kpiToday} max={r.st.kpiTarget} tone={r.kpiPct >= 100 ? 'green' : 'blue'} thin />
        <span>{fmt(r.st.kpiToday)} <span className="cvd-muted">/ {fmt(r.st.kpiTarget)}</span></span>
      </div>,
      <MiniBars
        values={r.st.kpiWeek.map((d) => d.editedCuboids)} target={r.st.kpiTarget}
        title={(v, k) => `${r.st.kpiWeek[k].date.slice(8)}/${r.st.kpiWeek[k].date.slice(5, 7)}: ${fmt(v)} cuboid`}
      />,
      `${r.st.completionPct}%`,
      <Tag tone={r.st.reworkRate >= 15 ? 'pink' : 'green'}>{r.st.reworkRate}%</Tag>,
      fmt(r.inHand),
      r.onTime.total === 0
        ? <span className="cvd-muted">—</span>
        : <Tag tone={r.onTime.rate >= 0.9 ? 'green' : r.onTime.rate >= 0.7 ? 'orange' : 'pink'}>{Math.round(r.onTime.rate * 100)}%</Tag>,
      r.late > 0 ? <Tag tone="pink">{fmt(r.late)}</Tag> : <span className="cvd-muted">0</span>,
    ],
  }))

  return (
    <>
      <PageTitle
        title={`Thành viên team ${team.name}`}
        controls={teams.length > 1 ? (
          <Pill>
            <Select variant="borderless" value={team.id} style={{ minWidth: 140 }} onChange={setTeamId}
              options={teams.map((t) => ({ value: t.id, label: `Team ${t.name}` }))} />
          </Pill>
        ) : undefined}
      />

      <div className="cvd-grid cvd-row-stats">
        <StatCard label="Thành viên" value={fmt(rows.length)} foot={`${fmt(metCount)} người đạt KPI hôm nay`} />
        <StatCard label="KPI hôm nay" value={fmt(totalToday)} suffix={`/ ${fmt(totalTarget)}`} progress={{ value: totalToday, max: totalTarget, tone: totalToday >= totalTarget ? 'green' : 'blue' }} />
        <StatCard label="Làm lại trung bình" value={`${avgRework}%`} foot="trên job đã nộp" />
        <StatCard label="Job đang giữ" value={fmt(holding)} foot="Annotator đang làm" />
      </div>

      <div className="cvd-grid cvd-row-main">
        <Card title="Tổng cuboid của team theo ngày">
          <DailyBars data={daily} target={totalTarget} today={today} unit="cuboid"
            targetLabel={`KPI ${fmt(totalTarget)} (${rows.length} người)`} />
        </Card>
        <Card title="Tóm tắt hôm nay">
          <div className="cvd-progress-row">
            <div><span>Đạt KPI</span><b>{fmt(metCount)} / {fmt(rows.length)}</b></div>
            <StripedBar value={metCount} max={Math.max(1, rows.length)} tone="green" />
          </div>
          <div className="cvd-progress-row">
            <div><span>Dưới 50% KPI</span><b>{fmt(belowHalf)}</b></div>
            <StripedBar value={belowHalf} max={Math.max(1, rows.length)} tone="pink" />
          </div>
          <div className="cvd-progress-row">
            <div><span>Job trễ đang giữ</span><b>{fmt(lateTotal)}</b></div>
            <StripedBar value={lateTotal} max={Math.max(1, holding)} tone="pink" />
          </div>
          <div className="cvd-separator" />
          <div className="cvd-muted">{top ? `Dẫn đầu: ${top.user.name} (${fmt(top.st.kpiToday)} cuboid)` : 'Chưa có dữ liệu'}</div>
        </Card>
      </div>

      <Card title={`Bảng xếp hạng (${rows.length})`}>
        <RowList
          heads={['#', 'Thành viên', 'KPI hôm nay', '7 ngày', '% hoàn thành', 'Làm lại', 'Job đang giữ', 'Đúng hạn', 'Job trễ đang giữ']}
          cols="40px minmax(0,2fr) minmax(0,1.6fr) minmax(0,1fr) minmax(0,0.8fr) minmax(0,0.7fr) minmax(0,0.8fr) minmax(0,0.7fr) minmax(0,0.9fr)"
          rows={listRows} emptyText="Team chưa có thành viên." resetKey={team.id}
        />
      </Card>
    </>
  )
}
