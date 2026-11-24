import { Clock } from '@untitledui/icons'
import { useState } from 'react'
import { Link } from 'react-router'
import { Tabs } from '@/components/application/tabs/tabs'
import { getErrorMessage } from '../../../shared/api/errors'
import MetricCard from '../../../shared/components/ui/MetricCard'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import StatCard from '../../../shared/components/ui/StatCard'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime, formatRelative } from '../../../shared/utils/format'
import { useProject } from '../../projects/projectContext'
import { getAnnotatorDashboard } from '../api'
import JobStatusBadge from '../components/JobStatusBadge'

type Period = 'day' | 'week' | 'month'
const PERIOD_LABELS: Record<Period, string> = { day: 'Ngày', week: 'Tuần', month: 'Tháng' }

/** Tổng quan cá nhân của Annotator: khối lượng công việc, rework, KPI và job sắp đến hạn. */
export default function AnnotatorDashboardPage() {
  const { projectId, project } = useProject()
  const [period, setPeriod] = useState<Period>('week')
  const { data, error, isLoading, retry } = useRequest(`annotator-dashboard:${projectId}:${period}`, () =>
    getAnnotatorDashboard(projectId, period),
  )

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Tổng quan Annotator</h1>
          <p className="mt-1 text-sm text-tertiary">Tiến độ và chất lượng gán nhãn của bạn · {project.name}</p>
        </div>
        <Tabs selectedKey={period} onSelectionChange={(k) => setPeriod(k as Period)} className="w-auto">
          <Tabs.List type="button-border" size="sm" aria-label="Kỳ">
            {(Object.keys(PERIOD_LABELS) as Period[]).map((p) => (
              <Tabs.Item key={p} id={p} label={PERIOD_LABELS[p]} />
            ))}
          </Tabs.List>
        </Tabs>
      </header>

      {error != null ? (
        <SectionCard><PageState kind="error" description={getErrorMessage(error)} onRetry={retry} /></SectionCard>
      ) : isLoading || !data ? (
        <SectionCard><PageState kind="loading" /></SectionCard>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard value={data.counts.pending_annotation + data.counts.annotating} label="Cần làm / Đang annotate" />
            <StatCard value={data.counts.rework} label="Cần sửa Rework" tone={data.counts.rework > 0 ? 'error' : undefined} />
            <StatCard value={data.counts.waiting_review} label="Đang chờ QC" />
            <StatCard value={data.counts.done} label={`Đã hoàn tất / ${data.counts.total} job`} />
          </div>

          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <MetricCard metric={data.submitted_in_period} label={`Đã nộp (${PERIOD_LABELS[period].toLowerCase()} này)`} />
            <MetricCard metric={data.first_pass_yield} label="Đạt lần đầu (FPY)" suffix="%" />
            <MetricCard metric={data.rework_rate} label="Tỷ lệ rework" suffix="%" />
            <StatCard
              value={data.kpi_target ? `${data.objects_done} / ${data.kpi_target}` : data.objects_done}
              label={data.kpi_target ? 'Object xong (mục tiêu/ngày)' : 'Tổng object đã hoàn tất'}
            />
          </div>

          {(data.counts.overdue > 0 || data.counts.escalated > 0) && (
            <div className="grid grid-cols-2 gap-3">
              <StatCard value={data.counts.overdue} label="Job đang quá hạn" tone={data.counts.overdue > 0 ? 'error' : undefined} />
              <StatCard value={data.counts.escalated} label="Job Escalated (chờ PM)" tone={data.counts.escalated > 0 ? 'error' : undefined} />
            </div>
          )}

          <div className="grid gap-5 lg:grid-cols-5">
            <SectionCard
              title="Job sắp đến deadline"
              description="Job đang mở của bạn có deadline trong 24 giờ tới hoặc đã quá hạn."
              actions={
                <Link to={`/projects/${projectId}/annotator/jobs`} className="text-sm font-semibold text-brand-secondary hover:underline">
                  Mở danh sách job
                </Link>
              }
              className="lg:col-span-3"
              bodyClassName="p-0"
            >
              {data.due_soon.length === 0 ? (
                <PageState kind="empty" title="Không có job nào sắp đến hạn" />
              ) : (
                <ul>
                  {data.due_soon.map((j) => (
                    <li key={j.id} className="flex flex-wrap items-center gap-3 border-t border-secondary px-5 py-3 first:border-0">
                      <Clock className={`size-5 shrink-0 ${j.is_overdue ? 'text-fg-error-primary' : 'text-fg-warning-primary'}`} />
                      <div className="min-w-40 flex-1">
                        <div className="font-medium text-primary">{j.name}</div>
                        <div className="text-xs text-tertiary">{j.batch_name}</div>
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

            <SectionCard
              title="Lỗi hay gặp"
              description="Các lỗi QC1 / QC2 từng ghi nhận trên job của bạn."
              className="lg:col-span-2"
            >
              {data.errors_by_category.length === 0 ? (
                <PageState kind="empty" title="Chưa có lỗi nào được ghi nhận" />
              ) : (
                <ul className="flex flex-col gap-3">
                  {data.errors_by_category.map((c) => {
                    const top = data.errors_by_category[0].count
                    return (
                      <li key={c.category}>
                        <div className="mb-1 flex justify-between text-sm">
                          <span className="text-secondary">{c.category}</span>
                          <span className="font-medium text-primary tabular-nums">{c.count}</span>
                        </div>
                        <div className="h-2 rounded-full bg-secondary">
                          <div className="h-full rounded-full bg-brand-solid" style={{ width: `${(c.count * 100) / top}%` }} />
                        </div>
                      </li>
                    )
                  })}
                </ul>
              )}
            </SectionCard>
          </div>
        </>
      )}
    </div>
  )
}
