import { Clock, Download01 } from '@untitledui/icons'
import dayjs from 'dayjs'
import { useState } from 'react'
import { Link } from 'react-router'
import { Tabs } from '@/components/application/tabs/tabs'
import { Button } from '@/components/base/buttons/button'
import { getErrorMessage } from '../../../shared/api/errors'
import MetricCard from '../../../shared/components/ui/MetricCard'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import StatCard from '../../../shared/components/ui/StatCard'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime, formatRelative } from '../../../shared/utils/format'
import JobStatusBadge from '../../jobs/components/JobStatusBadge'
import { useProject } from '../../projects/projectContext'
import { getLeaderDashboard } from './api'
import NoTeamNotice from './NoTeamNotice'
import TeamPicker from './TeamPicker'
import type { LeaderDashboard } from './types'

type Period = 'day' | 'week' | 'month'
const PERIOD_LABELS: Record<Period, string> = { day: 'Ngày', week: 'Tuần', month: 'Tháng' }

/** TL-01 Tổng quan team: KPI, xếp hạng thành viên, tỷ lệ rework, job sắp đến deadline. */
export default function TeamOverviewPage() {
  const { projectId } = useProject()
  const [period, setPeriod] = useState<Period>('week')
  const [team, setTeam] = useState<number | null>(null)
  const { data, error, isLoading, retry } = useRequest(`leader-dashboard:${projectId}:${period}:${team ?? ''}`, () =>
    getLeaderDashboard(projectId, period, team ?? undefined),
  )
  const teamName = data?.teams.length === 1 ? data.teams[0].name : team ? data?.teams.find((t) => t.id === team)?.name : 'các team của bạn'

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Tổng quan team</h1>
          <p className="mt-1 text-sm text-tertiary">{data ? `Số liệu của ${teamName ?? 'team'}` : 'Đang tải…'}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {data && <TeamPicker teams={data.teams} value={team} onChange={setTeam} />}
          <Tabs selectedKey={period} onSelectionChange={(k) => setPeriod(k as Period)} className="w-auto">
            <Tabs.List type="button-border" size="sm" aria-label="Kỳ">
              {(Object.keys(PERIOD_LABELS) as Period[]).map((p) => <Tabs.Item key={p} id={p} label={PERIOD_LABELS[p]} />)}
            </Tabs.List>
          </Tabs>
          <Button color="secondary" size="sm" iconLeading={Download01} isDisabled={!data?.teams.length}
            onPress={() => data && exportCsv(data, PERIOD_LABELS[period])}>
            Xuất báo cáo team
          </Button>
        </div>
      </header>

      {error != null ? (
        <SectionCard><PageState kind="error" description={getErrorMessage(error)} onRetry={retry} /></SectionCard>
      ) : isLoading || !data ? (
        <SectionCard><PageState kind="loading" /></SectionCard>
      ) : data.teams.length === 0 ? (
        <NoTeamNotice />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <MetricCard metric={data.kpi_quota} label="KPI khoán (đạt / mục tiêu)" />
            <MetricCard metric={data.kpi_by_total} label="KPI theo tổng số job" suffix="%" />
            <MetricCard metric={data.rework_rate} label="Tỷ lệ bị rework của team" suffix="%" />
            <MetricCard metric={data.done_in_period} label={`Job xong (${PERIOD_LABELS[period].toLowerCase()} này)`} />
          </div>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
            <StatCard value={data.member_count} label="Thành viên" />
            <StatCard value={data.jobs_open} label="Job đang mở" />
            <StatCard value={data.due_soon.length} label="Job sắp đến deadline (24h)" tone={data.due_soon.length ? 'error' : undefined} />
          </div>

          <div className="grid gap-5 lg:grid-cols-5">
            <SectionCard title="Bảng xếp hạng thành viên" description="Theo số job đã xong (job annotate trong dự án)." className="lg:col-span-3" bodyClassName="p-0">
              <table className="w-full text-sm">
                <thead className="bg-secondary text-xs font-semibold text-quaternary">
                  <tr>
                    <th className="w-14 px-5 py-2.5 text-left">Hạng</th>
                    <th className="px-3 py-2.5 text-left">Thành viên</th>
                    <th className="px-3 py-2.5 text-right">Job xong</th>
                    <th className="px-3 py-2.5 text-right">Object xong</th>
                    <th className="px-5 py-2.5 text-right">Tỷ lệ rework</th>
                  </tr>
                </thead>
                <tbody>
                  {data.ranking.map((r, i) => (
                    <tr key={r.user.id} className="border-t border-secondary">
                      <td className="px-5 py-3 font-semibold text-tertiary tabular-nums">{i + 1}</td>
                      <td className="px-3 py-3">
                        <div className="font-medium text-primary">{r.user.full_name}</div>
                        <div className="text-xs text-tertiary">{r.user.username}</div>
                      </td>
                      <td className="px-3 py-3 text-right text-secondary tabular-nums">{r.jobs_done}/{r.jobs_total}</td>
                      <td className="px-3 py-3 text-right text-secondary tabular-nums">{r.objects_done}</td>
                      <td className="px-5 py-3 text-right text-secondary tabular-nums">{r.rework_rate == null ? '—' : `${r.rework_rate}%`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </SectionCard>

            <SectionCard title="Tỷ lệ bị rework theo thành viên" description="Job từng bị trả rework / tổng job (tạm tính)." className="lg:col-span-2">
              <ul className="flex flex-col gap-3">
                {[...data.ranking].sort((a, b) => (b.rework_rate ?? -1) - (a.rework_rate ?? -1)).map((r) => (
                  <li key={r.user.id}>
                    <div className="mb-1 flex justify-between text-sm">
                      <span className="text-secondary">{r.user.full_name}</span>
                      <span className="font-medium text-primary tabular-nums">{r.rework_rate == null ? '—' : `${r.rework_rate}%`}</span>
                    </div>
                    <div className="h-2 rounded-full bg-secondary">
                      <div className="h-full rounded-full bg-brand-solid" style={{ width: `${r.rework_rate ?? 0}%` }} />
                    </div>
                  </li>
                ))}
              </ul>
            </SectionCard>
          </div>

          <SectionCard
            title="Job sắp đến deadline"
            description="Job đang mở của team có deadline trong 24 giờ tới hoặc đã quá hạn."
            actions={<Link to={`/projects/${projectId}/leader/jobs`} className="text-sm font-semibold text-brand-secondary hover:underline">Xem danh sách job</Link>}
            bodyClassName="p-0"
          >
            {data.due_soon.length === 0 ? (
              <PageState kind="empty" title="Không có job nào sắp đến deadline" />
            ) : (
              <ul>
                {data.due_soon.map((j) => (
                  <li key={j.id} className="flex flex-wrap items-center gap-3 border-t border-secondary px-5 py-3 first:border-0">
                    <Clock className={`size-5 shrink-0 ${j.is_overdue ? 'text-fg-error-primary' : 'text-fg-warning-primary'}`} />
                    <div className="min-w-40 flex-1">
                      <div className="font-medium text-primary">{j.name}</div>
                      <div className="text-xs text-tertiary">{j.batch_name} · {j.annotator?.full_name ?? 'Chưa giao'}</div>
                    </div>
                    <JobStatusBadge status={j.status} overdue={j.is_overdue} />
                    <span className="w-36 text-right text-sm text-tertiary" title={formatDateTime(j.deadline)}>
                      {j.is_overdue ? 'Quá hạn ' : 'Hạn '}{formatRelative(j.deadline)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>
        </>
      )}
    </div>
  )
}

function exportCsv(data: LeaderDashboard, periodLabel: string) {
  const rows: (string | number)[][] = [
    ['Báo cáo team', data.teams.map((t) => t.name).join(' + '), `Kỳ: ${periodLabel}`, `Xuất lúc ${dayjs().format('DD/MM/YYYY HH:mm')}`],
    [],
    ['Hạng', 'Thành viên', 'Username', 'Job xong', 'Tổng job', 'Object xong', 'Tỷ lệ rework (%)'],
    ...data.ranking.map((r, i) => [i + 1, r.user.full_name, r.user.username, r.jobs_done, r.jobs_total, r.objects_done, r.rework_rate ?? '']),
    [],
    ['Job sắp deadline', 'Batch', 'Người làm', 'Deadline'],
    ...data.due_soon.map((j) => [j.name, j.batch_name, j.annotator?.full_name ?? '', formatDateTime(j.deadline)]),
  ]
  const csv = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\r\n')
  const url = URL.createObjectURL(new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' }))
  Object.assign(document.createElement('a'), { href: url, download: `bao-cao-team-${dayjs().format('YYYYMMDD')}.csv` }).click()
  URL.revokeObjectURL(url)
}
