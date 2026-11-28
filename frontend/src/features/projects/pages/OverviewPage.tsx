import { AlertCircle, AlertTriangle, ArrowRight, InfoCircle } from '@untitledui/icons'
import { useState } from 'react'
import { Link } from 'react-router'
import { Tabs } from '@/components/application/tabs/tabs'
import { Badge } from '@/components/base/badges/badges'
import { ProgressBarBase } from '@/components/base/progress-indicators/progress-indicators'
import { getErrorMessage } from '../../../shared/api/errors'
import RoleBadges from '../../../shared/components/RoleBadges'
import BarChart from '../../../shared/components/ui/BarChart'
import MetricCard from '../../../shared/components/ui/MetricCard'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import StatCard from '../../../shared/components/ui/StatCard'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import { STAGE_LABELS } from '../../jobs/constants'
import { getOverview } from '../api'
import { useProject } from '../projectContext'

type Period = 'day' | 'week' | 'month'

const PERIODS: { id: Period; label: string }[] = [
  { id: 'day', label: 'Ngày' },
  { id: 'week', label: 'Tuần' },
  { id: 'month', label: 'Tháng' },
]

const STAGES = ['annotation', 'qc1', 'qc2', 'done'] as const

/** Tổng quan organization: KPI, tiến độ theo stage, quy mô và cảnh báo vận hành. */
export default function OverviewPage() {
  const { project, projectId } = useProject()
  const [period, setPeriod] = useState<Period>('week')
  const { data, error, isLoading, retry } = useRequest(`overview:${projectId}:${period}`, () => getOverview(projectId, period))

  const hasErrorAlert = data?.alerts.some((a) => a.level === 'error')
  const hasWarningAlert = data?.alerts.some((a) => a.level === 'warning')

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">{project.name}</h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-sm text-tertiary">
            <span>Vai trò của bạn:</span>
            <RoleBadges roles={project.my_roles} />
            {project.cvat_synced_at ? (
              <span className="text-xs text-tertiary">
                · Đồng bộ CVAT gần nhất: {formatDateTime(project.cvat_synced_at)}
              </span>
            ) : project.cvat_org_id != null ? (
              <span className="text-xs text-tertiary">· Chưa đồng bộ CVAT</span>
            ) : null}
          </div>
        </div>
        <Tabs selectedKey={period} onSelectionChange={(k) => setPeriod(k as Period)} className="w-auto">
          <Tabs.List type="button-border" size="sm" aria-label="Chọn kỳ thống kê">
            {PERIODS.map((p) => (
              <Tabs.Item key={p.id} id={p.id} label={p.label} />
            ))}
          </Tabs.List>
        </Tabs>
      </header>

      {error != null ? (
        <SectionCard>
          <PageState kind="error" description={getErrorMessage(error)} onRetry={retry} />
        </SectionCard>
      ) : isLoading && !data ? (
        <SectionCard>
          <PageState kind="loading" />
        </SectionCard>
      ) : data ? (
        <>
          {data.counts.jobs === 0 && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-brand-primary_alt p-4 ring-1 ring-brand ring-inset">
              <div className="flex items-start gap-3">
                <InfoCircle className="mt-0.5 size-5 shrink-0 text-fg-brand-primary" />
                <p className="text-sm text-secondary">
                  Organization chưa có job. Tạo project và task trên CVAT, rồi bấm Đồng bộ CVAT ở trang Projects.
                </p>
              </div>
              <Link
                to="../datasets"
                relative="path"
                className="inline-flex items-center gap-1 text-sm font-semibold text-brand-secondary hover:underline"
              >
                Đến Projects <ArrowRight className="size-4" />
              </Link>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <MetricCard label="Tổng số object" metric={data.metrics.total_objects} />
            <MetricCard label="Quality CL" metric={data.metrics.quality_cl} suffix="%" />
            <MetricCard label="Rework rate" metric={data.metrics.rework_rate} suffix="%" />
            <MetricCard label="Delivery readiness" metric={data.metrics.delivery_readiness} suffix="%" />
          </div>

          {(data.thresholds.quality_cl != null || data.thresholds.defect_error_rate != null) && (
            <div className="flex flex-wrap items-center gap-2 rounded-xl bg-primary px-4 py-3 text-sm text-tertiary ring-1 ring-secondary">
              <span className="font-medium text-secondary">Ngưỡng mục tiêu:</span>
              {data.thresholds.quality_cl != null && (
                <Badge type="pill-color" size="sm" color="brand">
                  Quality CL ≥ {data.thresholds.quality_cl}%
                </Badge>
              )}
              {data.thresholds.defect_error_rate != null && (
                <Badge type="pill-color" size="sm" color="gray">
                  Defect error rate ≤ {data.thresholds.defect_error_rate}%
                </Badge>
              )}
              <Link to="../settings" relative="path" className="ml-auto text-xs font-semibold text-brand-secondary hover:underline">
                Điều chỉnh cấu hình
              </Link>
            </div>
          )}

          {(() => {
            const decisions = data.pending_decisions
            const batchesReady = decisions.batches_ready_for_qc2_confirm ?? decisions.batches_ready_for_qc2 ?? 0
            const pendingIssueRulings = decisions.pending_issue_rulings ?? 0
            const escalatedJobs = decisions.escalated_jobs ?? decisions.escalated ?? 0
            const totalDecisions =
              decisions.total ??
              batchesReady +
                decisions.pending_qc2_samples +
                decisions.pending_requests +
                pendingIssueRulings +
                escalatedJobs
            const decisionRows = [
              {
                key: 'qc2-confirm',
                label: 'Task sẵn sàng xác nhận QC2',
                count: batchesReady,
                to: '../batches',
                action: 'Mở Tasks',
                tone: batchesReady > 0 ? ('brand' as const) : ('gray' as const),
              },
              {
                key: 'qc2-samples',
                label: 'Mẫu QC2 chờ kiểm tra',
                count: decisions.pending_qc2_samples,
                to: '../qc2/work',
                action: 'Kiểm tra QC2',
                tone: decisions.pending_qc2_samples > 0 ? ('warning' as const) : ('gray' as const),
              },
              {
                key: 'requests',
                label: 'Yêu cầu từ Annotator',
                count: decisions.pending_requests,
                to: '../annotator/requests',
                action: 'Xử lý yêu cầu',
                tone: decisions.pending_requests > 0 ? ('warning' as const) : ('gray' as const),
              },
              ...(decisions.pending_issue_rulings !== undefined
                ? [
                    {
                      key: 'issue-rulings',
                      label: 'Issue chờ PM phán quyết',
                      count: pendingIssueRulings,
                      to: '../jobs',
                      action: 'Mở Jobs',
                      tone: pendingIssueRulings > 0 ? ('warning' as const) : ('gray' as const),
                    },
                  ]
                : []),
              {
                key: 'escalated',
                label: 'Job bị Escalated',
                count: escalatedJobs,
                to: '../jobs?escalated=1',
                action: 'Xem job',
                tone: escalatedJobs > 0 ? ('error' as const) : ('gray' as const),
              },
            ]
            return (
              <SectionCard
                title={
                  <span className="inline-flex items-center gap-2">
                    Việc cần quyết định (TD13)
                    <Badge
                      type="pill-color"
                      size="sm"
                      color={escalatedJobs > 0 ? 'error' : totalDecisions > 0 ? 'warning' : 'gray'}
                    >
                      {totalDecisions}
                    </Badge>
                  </span>
                }
              >
                <div
                  className={`grid grid-cols-1 gap-3 sm:grid-cols-2 ${
                    decisionRows.length >= 5 ? 'lg:grid-cols-5' : 'lg:grid-cols-4'
                  }`}
                >
                  {decisionRows.map((item) => (
                    <Link
                      key={item.key}
                      to={item.to}
                      relative="path"
                      className="group flex flex-col justify-between gap-2 rounded-xl bg-secondary p-4 ring-1 ring-secondary transition hover:bg-primary_hover hover:ring-brand"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-display-xs font-semibold text-primary tabular-nums">{item.count}</span>
                        <Badge type="pill-color" size="sm" color={item.tone}>
                          {item.count > 0 ? 'Cần xử lý' : 'Ổn định'}
                        </Badge>
                      </div>
                      <span className="text-sm font-medium text-secondary">{item.label}</span>
                      <span className="inline-flex items-center gap-1 text-xs font-semibold text-brand-secondary group-hover:underline">
                        {item.action} <ArrowRight className="size-3.5" />
                      </span>
                    </Link>
                  ))}
                </div>
              </SectionCard>
            )
          })()}

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
            <SectionCard title="Tiến độ theo stage" className="lg:col-span-7">
              <div className="flex flex-col gap-4">
                {STAGES.map((stage) => {
                  const count = data.by_stage[stage]
                  const percent = data.counts.jobs ? Math.round((count * 100) / data.counts.jobs) : 0
                  return (
                    <div key={stage}>
                      <div className="mb-1.5 flex items-center justify-between text-sm">
                        <span className="font-medium text-secondary">{STAGE_LABELS[stage]}</span>
                        <span className="text-tertiary tabular-nums">
                          {count} job ({percent}%)
                        </span>
                      </div>
                      <ProgressBarBase
                        value={percent}
                        progressClassName={stage === 'done' ? 'bg-fg-success-primary' : undefined}
                      />
                    </div>
                  )
                })}
              </div>

              <div className="mt-5 border-t border-secondary pt-4">
                <BarChart
                  height={140}
                  ariaLabel="Phân bổ số job theo stage"
                  data={STAGES.map((stage) => {
                    const count = data.by_stage[stage]
                    const percent = data.counts.jobs ? Math.round((count * 100) / data.counts.jobs) : 0
                    return {
                      label: STAGE_LABELS[stage],
                      value: count,
                      details: [`${count} job`, `${percent}% tổng số job`],
                    }
                  })}
                />
              </div>

              <p className="mt-3 text-xs text-tertiary">
                Ước tính hoàn thành: chưa chốt cách tính. Tiến độ kế hoạch chưa có dữ liệu kế hoạch để so sánh.
              </p>
            </SectionCard>

            <SectionCard title="Quy mô organization" className="lg:col-span-5">
              <div className="grid grid-cols-3 gap-3">
                <StatCard value={data.counts.datasets} label="Project" />
                <StatCard value={data.counts.batches} label="Task" />
                <StatCard value={data.counts.jobs} label="Job" />
              </div>
              <div className="mt-3 grid grid-cols-3 gap-3">
                <StatCard
                  value={data.counts.escalated}
                  label="Escalated"
                  tone={data.counts.escalated > 0 ? 'error' : undefined}
                />
                <StatCard
                  value={data.counts.overdue}
                  label="Job quá hạn"
                  tone={data.counts.overdue > 0 ? 'error' : undefined}
                />
                <StatCard
                  value={data.counts.overdue_batches}
                  label="Task quá hạn"
                  tone={data.counts.overdue_batches > 0 ? 'error' : undefined}
                />
              </div>
              <p className="mt-3 text-xs text-tertiary">
                Task sẵn sàng bàn giao: {data.counts.ready_batches} · Đã bàn giao: {data.counts.delivered_batches} · Job còn lại: {data.counts.remaining_jobs}
              </p>
            </SectionCard>
          </div>

          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <MetricCard label="Job nộp trong kỳ" metric={data.metrics.submitted_in_period} />
            <MetricCard label="Thành viên đang hoạt động" metric={data.metrics.active_members} />
            <MetricCard label="First pass yield" metric={data.metrics.first_pass_yield} suffix="%" />
            <MetricCard label="QC2 pass rate" metric={data.metrics.qc2_pass_rate} suffix="%" />
            <MetricCard label="Bàn giao đúng hạn (DH07)" metric={data.metrics.delivery_on_time_rate} suffix="%" />
            <MetricCard label="Defect error rate" metric={data.metrics.defect_error_rate} suffix="%" />
            <MetricCard label="Tỷ lệ đảo ngược khiếu nại" metric={data.metrics.dispute_overturn_rate} suffix="%" />
            <MetricCard label="Ước tính hoàn thành" metric={data.metrics.estimated_completion} />
          </div>

          {(data.errors_by_category.length > 0 ||
            data.errors_by_severity.minor + data.errors_by_severity.major + data.errors_by_severity.critical > 0) && (
            <SectionCard title="Phân bố lỗi QC (CL04)">
              <div className="flex flex-wrap items-center gap-2">
                <Badge type="pill-color" size="sm" color="error">
                  Nghiêm trọng: {data.errors_by_severity.critical}
                </Badge>
                <Badge type="pill-color" size="sm" color="warning">
                  Trung bình: {data.errors_by_severity.major}
                </Badge>
                <Badge type="pill-color" size="sm" color="gray">
                  Nhẹ: {data.errors_by_severity.minor}
                </Badge>
              </div>
              {data.errors_by_category.length > 0 && (
                <ul className="mt-3 flex flex-wrap gap-2">
                  {data.errors_by_category.map((item) => (
                    <li
                      key={item.category}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-secondary px-3 py-1.5 text-sm text-secondary"
                    >
                      <span>{item.category}</span>
                      <span className="font-semibold text-primary tabular-nums">{item.count}</span>
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>
          )}

          <SectionCard
            title={
              <span className="inline-flex items-center gap-2">
                Cảnh báo organization
                <Badge
                  type="pill-color"
                  size="sm"
                  color={hasErrorAlert ? 'error' : hasWarningAlert ? 'warning' : 'gray'}
                >
                  {data.alerts.length}
                </Badge>
              </span>
            }
            bodyClassName="p-0"
          >
            {data.alerts.length === 0 ? (
              <PageState kind="empty" title="Không có cảnh báo" description="Không có job quá hạn, sắp hạn hoặc escalated." />
            ) : (
              <ul className="divide-y divide-secondary">
                {data.alerts.map((alert) => {
                  const query =
                    alert.type === 'escalated'
                      ? 'escalated=1'
                      : alert.type === 'due_soon'
                        ? 'due_soon=1'
                        : 'overdue=1'
                  const Icon =
                    alert.level === 'error'
                      ? AlertCircle
                      : alert.level === 'warning'
                        ? AlertTriangle
                        : InfoCircle
                  const iconTone =
                    alert.level === 'error'
                      ? 'text-fg-error-primary'
                      : alert.level === 'warning'
                        ? 'text-fg-warning-primary'
                        : 'text-fg-brand-primary'
                  return (
                    <li key={`${alert.type}-${alert.job}`} className="flex items-center justify-between gap-4 px-5 py-3.5">
                      <div className="flex items-center gap-3 text-sm text-secondary">
                        <Icon className={`size-4 shrink-0 ${iconTone}`} />
                        <span>{alert.message}</span>
                      </div>
                      <Link
                        to={`../jobs?${query}`}
                        relative="path"
                        className="inline-flex shrink-0 items-center gap-1 text-sm font-medium text-brand-secondary hover:underline"
                      >
                        Xem <ArrowRight className="size-3.5" />
                      </Link>
                    </li>
                  )
                })}
              </ul>
            )}
          </SectionCard>
        </>
      ) : null}
    </div>
  )
}
