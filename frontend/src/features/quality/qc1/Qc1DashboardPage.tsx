import { ArrowDown, ArrowUp, Download01 } from '@untitledui/icons'
import { useState } from 'react'
import { Link } from 'react-router'
import { Tabs } from '@/components/application/tabs/tabs'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { getErrorMessage } from '../../../shared/api/errors'
import BarChart from '../../../shared/components/ui/BarChart'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import StatCard from '../../../shared/components/ui/StatCard'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatCsvFileDate, formatCsvTimestamp, formatDateTime, formatShortDate, formatViPercent } from '../../../shared/utils/format'
import ReviewErrorChips from '../../jobs/components/ReviewErrorChips'
import { formatKpiDeltaText } from '../../jobs/jobHelpers'
import { useProject } from '../../projects/projectContext'
import { getQc1Summary } from '../api'
import { SEVERITY_LABELS } from '../constants'
import type { MetricDelta, Qc1Summary, Qc1Window, Severity } from '../types'

type Period = 'day' | 'week' | 'month'
const PERIOD_LABELS: Record<Period, string> = { day: 'Ngày', week: 'Tuần', month: 'Tháng' }
const PERIOD_COMPARISON_DESCRIPTIONS: Record<Period, string> = {
  day: 'So sánh hôm nay với hôm qua',
  week: 'So sánh tuần này với 7 ngày trước đó',
  month: 'So sánh 30 ngày gần nhất với kỳ trước cùng độ dài',
}

const KPI_ROWS: {
  key: keyof Qc1Window
  label: string
  comparisonKey?: 'reviewed' | 'passed' | 'rejected' | 'errors'
  format?: (v: number | null) => string
}[] = [
  { key: 'reviewed', label: 'Job đã kiểm tra', comparisonKey: 'reviewed' },
  { key: 'passed', label: 'Đạt QC1', comparisonKey: 'passed' },
  { key: 'rejected', label: 'Reject → Rework', comparisonKey: 'rejected' },
  { key: 'pass_rate', label: 'Tỷ lệ đạt QC1', format: (v) => formatViPercent(v) },
  { key: 'errors', label: 'Lỗi ghi nhận', comparisonKey: 'errors' },
]

const SEVERITY_ORDER: Severity[] = ['critical', 'major', 'minor']
const SEVERITY_BADGE_COLORS: Record<Severity, 'error' | 'warning' | 'gray'> = {
  critical: 'error',
  major: 'warning',
  minor: 'gray',
}
const SEVERITY_BAR_COLORS: Record<Severity, string> = {
  critical: 'bg-fg-error-primary',
  major: 'bg-fg-warning-primary',
  minor: 'bg-fg-quaternary',
}

/** Tổng quan Level 1 QC: hàng chờ, KPI ngày & so sánh kỳ, đúng hạn DH06, FPY CL01, lỗi bỏ sót CL06/CL07 và phân bố lỗi CL04. */
export default function Qc1DashboardPage() {
  const { projectId, project, can } = useProject()
  const canViewProject = can('view_dashboard')
  const canPerformQc1 = can('perform_qc1')
  const canViewJobs = can('view_jobs')
  const [period, setPeriod] = useState<Period>('week')
  const [scope, setScope] = useState<'mine' | 'project'>(canViewProject ? 'project' : 'mine')
  const { data, error, isLoading, retry } = useRequest(`qc1-summary:${projectId}:${period}:${scope}`, () =>
    getQc1Summary(projectId, period, scope === 'mine' ? 'mine' : undefined),
  )

  const kpiSummary = data?.kpi_summary
  const kpiCardValue =
    kpiSummary?.target != null && kpiSummary.target > 0
      ? `${kpiSummary.actual} / ${kpiSummary.target}`
      : String(kpiSummary?.actual ?? data?.stats.reviewed_today ?? data?.kpi.current.reviewed ?? 0)
  const kpiCardNote =
    kpiSummary?.target != null && kpiSummary.target > 0
      ? `Đạt ${formatViPercent(kpiSummary.achievement_pct ?? 0)} · ${formatKpiDeltaText(kpiSummary.shortfall, kpiSummary.surplus, 'job')}`
      : 'Chưa đặt chỉ tiêu QC1/ngày'

  const poolPending = data?.stats.pool_pending ?? 0
  const qc1PassedCount = data?.stats.qc1_passed ?? 0
  const overdueCount = data?.stats.overdue ?? 0
  const dueSoonCount = data?.stats.due_soon ?? 0
  const queueLink = canPerformQc1
    ? {
        base: `/projects/${projectId}/qc1/work`,
        overdue: `/projects/${projectId}/qc1/work?overdue=1`,
        dueSoon: `/projects/${projectId}/qc1/work?due_soon=1`,
        label: 'Mở hàng chờ QC1 →',
      }
    : canViewJobs
      ? {
          base: `/projects/${projectId}/jobs?stage=qc1`,
          overdue: `/projects/${projectId}/jobs?stage=qc1&overdue=1`,
          dueSoon: `/projects/${projectId}/jobs?stage=qc1&due_soon=1`,
          label: 'Xem job giai đoạn QC1 →',
        }
      : null
  const escapedJobsCount = data?.escaped_jobs_count ?? data?.escaped_jobs ?? 0
  const escapeErrors = data?.escape_errors ?? []
  const severityCounts = data?.errors_by_severity
  const severityTotal = severityCounts
    ? SEVERITY_ORDER.reduce((sum, s) => sum + (severityCounts[s] ?? 0), 0)
    : 0

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Tổng quan QC1</h1>
          <p className="mt-1 text-sm text-tertiary">
            {scope === 'mine' ? 'Số liệu kiểm tra QC1 của bạn' : 'Số liệu kiểm tra QC1 toàn organization'} · {project.name}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {canViewProject && (
            <Tabs selectedKey={scope} onSelectionChange={(k) => setScope(k as typeof scope)} className="w-auto">
              <Tabs.List type="button-border" size="sm" aria-label="Phạm vi">
                <Tabs.Item id="project" label="Toàn organization" />
                <Tabs.Item id="mine" label="Của tôi" />
              </Tabs.List>
            </Tabs>
          )}
          <Tabs selectedKey={period} onSelectionChange={(k) => setPeriod(k as Period)} className="w-auto">
            <Tabs.List type="button-border" size="sm" aria-label="Kỳ">
              {(Object.keys(PERIOD_LABELS) as Period[]).map((p) => (
                <Tabs.Item key={p} id={p} label={PERIOD_LABELS[p]} />
              ))}
            </Tabs.List>
          </Tabs>
          <Button
            color="secondary"
            size="sm"
            iconLeading={Download01}
            isDisabled={!data}
            onPress={() => data && exportCsv(data, project.name, PERIOD_LABELS[period])}
          >
            Xuất báo cáo
          </Button>
        </div>
      </header>

      {error != null ? (
        <SectionCard>
          <PageState kind="error" description={getErrorMessage(error)} onRetry={retry} />
        </SectionCard>
      ) : isLoading || !data ? (
        <SectionCard>
          <PageState kind="loading" />
        </SectionCard>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="flex flex-col justify-between rounded-xl bg-primary p-4 ring-1 ring-secondary ring-inset">
              <div>
                <p className="text-xs font-medium text-tertiary">Job chờ QC1</p>
                <p className="mt-1 text-display-xs font-semibold text-primary tabular-nums">{data.stats.pending}</p>
                <p className="mt-1 text-xs text-tertiary">
                  Pool chung: {poolPending} · Đang giữ: {data.stats.assigned}
                </p>
              </div>
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {overdueCount > 0 &&
                  (queueLink ? (
                    <Link to={queueLink.overdue}>
                      <Badge type="pill-color" size="sm" color="error">
                        {overdueCount} quá hạn
                      </Badge>
                    </Link>
                  ) : (
                    <Badge type="pill-color" size="sm" color="error">
                      {overdueCount} quá hạn
                    </Badge>
                  ))}
                {dueSoonCount > 0 &&
                  (queueLink ? (
                    <Link to={queueLink.dueSoon}>
                      <Badge type="pill-color" size="sm" color="warning">
                        {dueSoonCount} sắp hạn
                      </Badge>
                    </Link>
                  ) : (
                    <Badge type="pill-color" size="sm" color="warning">
                      {dueSoonCount} sắp hạn
                    </Badge>
                  ))}
                {overdueCount === 0 && dueSoonCount === 0 && queueLink && (
                  <Link to={queueLink.base} className="text-xs font-medium text-brand-secondary hover:underline">
                    {queueLink.label}
                  </Link>
                )}
              </div>
            </div>

            <div className="flex flex-col justify-between rounded-xl bg-primary p-4 ring-1 ring-secondary ring-inset">
              <div>
                <p className="text-xs font-medium text-tertiary">Đang kiểm tra QC1</p>
                <p className="mt-1 text-display-xs font-semibold text-primary tabular-nums">{data.stats.reviewing}</p>
                <p className="mt-1 text-xs text-tertiary">
                  Đạt QC1 (chờ xác nhận QC2): {qc1PassedCount} · Kỳ này: {data.stats.reviewed_in_period} job
                </p>
              </div>
              <p className="mt-2 text-xs text-tertiary">
                Tỷ lệ đạt tích luỹ: {formatViPercent(data.pass_rate)}
              </p>
            </div>

            <div className="flex flex-col justify-between rounded-xl bg-primary p-4 ring-1 ring-secondary ring-inset">
              <div>
                <p className="text-xs font-medium text-tertiary">Sản lượng hôm nay / chỉ tiêu</p>
                <p className="mt-1 text-display-xs font-semibold text-primary tabular-nums">{kpiCardValue}</p>
              </div>
              <p className="mt-2 text-xs text-tertiary">{kpiCardNote}</p>
            </div>

            <div className="flex flex-col justify-between rounded-xl bg-primary p-4 ring-1 ring-secondary ring-inset">
              <div>
                <p className="text-xs font-medium text-tertiary">Hoàn tất QC1 đúng hạn</p>
                <p className="mt-1 text-display-xs font-semibold text-primary tabular-nums">
                  {formatViPercent(data.on_time_pct)}
                </p>
              </div>
              <p className="mt-2 text-xs text-tertiary">
                {data.on_time_total
                  ? `${data.on_time_count ?? 0}/${data.on_time_total} lượt kiểm có deadline trong kỳ`
                  : data.on_time_pct == null
                    ? 'Chưa có lượt kiểm gắn deadline trong kỳ'
                    : 'Theo deadline từng lượt kiểm QC1 trong kỳ'}
              </p>
            </div>
          </div>

          <SectionCard
            title="Phản hồi chất lượng kiểm tra"
            description="Đối chiếu lỗi QC2 phát hiện trên job đã qua QC1 và tỷ lệ đạt lần đầu (FPY phản ánh đầu ra của Annotator)."
          >
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <StatCard
                value={data.qc2_escape_errors}
                label="Lỗi QC1 bỏ sót (phát hiện ở QC2)"
                tone={data.qc2_escape_errors > 0 ? 'error' : undefined}
              />
              <div className="rounded-xl bg-secondary p-4 ring-1 ring-secondary ring-inset">
                <p className="text-xs font-medium text-tertiary">Tỷ lệ job có lỗi QC1 bỏ sót</p>
                <p
                  className={`mt-1 text-display-xs font-semibold tabular-nums ${
                    escapedJobsCount > 0 ? 'text-error-primary' : 'text-primary'
                  }`}
                >
                  {formatViPercent(data.qc1_escape_job_rate)}
                </p>
                <p className="mt-1 text-xs text-tertiary">
                  {escapedJobsCount} / {data.audited_jobs_count ?? 0} job đã audit QC2 trong kỳ
                </p>
              </div>
              <div className="rounded-xl bg-secondary p-4 ring-1 ring-secondary ring-inset">
                <p className="text-xs font-medium text-tertiary">FPY nhóm job đã kiểm (đầu ra Annotator)</p>
                <p className="mt-1 text-display-xs font-semibold text-primary tabular-nums">
                  {formatViPercent(data.first_pass_yield?.value)}
                </p>
                <p className="mt-1 text-xs text-tertiary">
                  {data.first_pass_yield?.total
                    ? `${data.first_pass_yield.passed ?? 0} / ${data.first_pass_yield.total} job đạt QC1 ngay lần đầu`
                    : 'Chưa có job đủ dữ liệu FPY'}
                </p>
              </div>
            </div>

            {escapeErrors.length > 0 && (
              <div className="mt-4 overflow-hidden rounded-xl ring-1 ring-secondary">
                <div className="bg-secondary px-4 py-2.5 text-xs font-semibold text-quaternary">
                  Bằng chứng lỗi QC1 bỏ sót ({escapeErrors.length}
                  {data.qc2_escape_errors > escapeErrors.length ? ` / ${data.qc2_escape_errors}` : ''})
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[640px] text-left text-sm">
                    <thead className="border-t border-secondary bg-secondary text-xs font-semibold text-quaternary">
                      <tr>
                        <th className="px-4 py-2">Job / Task</th>
                        <th className="px-4 py-2">Lỗi QC2 phát hiện</th>
                        <th className="px-4 py-2">Mức độ</th>
                        <th className="px-4 py-2">Người audit · Thời điểm</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-secondary">
                      {escapeErrors.map((err) => {
                        const jobHref = canPerformQc1
                          ? `/projects/${projectId}/qc1/work?job=${err.job_id}`
                          : canViewJobs
                            ? `/projects/${projectId}/jobs?search=${encodeURIComponent(err.job_name)}`
                            : null
                        return (
                          <tr key={err.id}>
                            <td className="px-4 py-2.5 align-top">
                              {jobHref ? (
                                <Link
                                  to={jobHref}
                                  className="font-medium text-brand-secondary hover:underline"
                                >
                                  {err.job_name}
                                </Link>
                              ) : (
                                <span className="font-medium text-primary">{err.job_name}</span>
                              )}
                              <div className="text-xs text-tertiary">{err.batch_name}</div>
                            </td>
                            <td className="px-4 py-2.5 align-top">
                              <div className="font-medium text-primary">{err.category}</div>
                              <ReviewErrorChips err={err} />
                              {err.location && <div className="mt-1 text-xs text-secondary">{err.location}</div>}
                              {err.description && <div className="mt-0.5 text-xs text-tertiary">{err.description}</div>}
                            </td>
                            <td className="px-4 py-2.5 align-top">
                              <Badge type="pill-color" size="sm" color={SEVERITY_BADGE_COLORS[err.severity] ?? 'gray'}>
                                {SEVERITY_LABELS[err.severity] ?? err.severity}
                              </Badge>
                            </td>
                            <td className="px-4 py-2.5 align-top text-xs text-tertiary whitespace-nowrap">
                              <div className="font-medium text-secondary">{err.reported_by?.full_name ?? 'QC2'}</div>
                              <div>{formatDateTime(err.created_at)}</div>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </SectionCard>

          <SectionCard
            title="Bảng KPI kiểm tra QC1"
            description={
              data.kpi_target
                ? `${PERIOD_COMPARISON_DESCRIPTIONS[period]} · Chỉ tiêu: ${data.kpi_target} job/ngày.`
                : `${PERIOD_COMPARISON_DESCRIPTIONS[period]}.`
            }
            bodyClassName="p-0"
          >
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-secondary text-xs font-semibold text-quaternary">
                  <tr>
                    <th className="px-5 py-2.5 text-left">Chỉ số</th>
                    <th className="px-5 py-2.5 text-right">Kỳ này</th>
                    <th className="px-5 py-2.5 text-right">Kỳ trước</th>
                    <th className="px-5 py-2.5 text-right">Thay đổi</th>
                  </tr>
                </thead>
                <tbody>
                  {KPI_ROWS.map((row) => {
                    const fmt = row.format ?? ((v: number | null) => (v == null ? '—' : String(v)))
                    const current = data.kpi.current[row.key]
                    const previous = data.kpi.previous[row.key]
                    const comp = row.comparisonKey ? data.kpi.comparison?.[row.comparisonKey] : undefined
                    return (
                      <tr key={row.key} className="border-t border-secondary">
                        <td className="px-5 py-3 font-medium text-secondary">{row.label}</td>
                        <td className="px-5 py-3 text-right text-primary tabular-nums">{fmt(current)}</td>
                        <td className="px-5 py-3 text-right text-tertiary tabular-nums">{fmt(previous)}</td>
                        <td className="px-5 py-3 text-right">
                          <Delta
                            current={current}
                            previous={previous}
                            comparison={comp}
                            unit={row.key === 'pass_rate' ? ' điểm %' : ''}
                          />
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </SectionCard>

          <div className="grid gap-5 lg:grid-cols-5">
            <SectionCard
              title="Xu hướng kiểm tra QC1"
              description={`Số job đã kiểm tra mỗi ngày, ${data.trend.length} ngày gần nhất. Rê chuột để xem chi tiết.`}
              className="lg:col-span-3"
            >
              <BarChart
                ariaLabel="Số job đã kiểm tra QC1 theo ngày"
                data={data.trend.map((d) => ({
                  label: formatShortDate(d.date),
                  value: d.reviewed,
                  details: [`Đã kiểm tra: ${d.reviewed}`, `Reject: ${d.rejected}`, `Lỗi ghi nhận: ${d.errors}`],
                }))}
              />
            </SectionCard>

            <div className="flex flex-col gap-5 lg:col-span-2">
              <SectionCard title="Lỗi QC1 theo mức độ" description="Chỉ tính lỗi chưa bị huỷ.">
                {severityTotal === 0 ? (
                  <p className="text-sm text-tertiary">Chưa ghi nhận lỗi QC1 nào.</p>
                ) : (
                  <ul className="flex flex-col gap-3">
                    {SEVERITY_ORDER.map((sev) => {
                      const count = severityCounts?.[sev] ?? 0
                      const pct = severityTotal ? Math.round((count * 100) / severityTotal) : 0
                      return (
                        <li key={sev}>
                          <div className="mb-1 flex items-center justify-between text-sm">
                            <Badge type="pill-color" size="sm" color={SEVERITY_BADGE_COLORS[sev]}>
                              {SEVERITY_LABELS[sev]}
                            </Badge>
                            <span className="font-medium text-primary tabular-nums">
                              {count} ({pct}%)
                            </span>
                          </div>
                          <div className="h-2 rounded-full bg-secondary">
                            <div
                              className={`h-full rounded-full ${SEVERITY_BAR_COLORS[sev]}`}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                        </li>
                      )
                    })}
                  </ul>
                )}
              </SectionCard>

              <SectionCard title="Lỗi QC1 theo loại" description="Lỗi QC1 ghi nhận, nhiều nhất trước.">
                {data.errors_by_category.length === 0 ? (
                  <PageState kind="empty" title="Chưa ghi nhận lỗi nào" />
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
                            <div
                              className="h-full rounded-full bg-brand-solid"
                              style={{ width: `${(c.count * 100) / top}%` }}
                            />
                          </div>
                        </li>
                      )
                    })}
                  </ul>
                )}
              </SectionCard>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function Delta({
  current,
  previous,
  comparison,
  unit,
}: {
  current: number | null
  previous: number | null
  comparison?: MetricDelta
  unit: string
}) {
  if (current == null || previous == null) return <span className="text-quaternary">—</span>
  const diff = comparison ? comparison.delta : Math.round((current - previous) * 10) / 10
  if (diff === 0) return <span className="text-tertiary">0</span>
  const Icon = diff > 0 ? ArrowUp : ArrowDown
  const formattedDiff = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 1 }).format(Math.abs(diff))
  const pctSuffix =
    comparison?.pct_change != null
      ? ` (${comparison.pct_change > 0 ? '+' : comparison.pct_change < 0 ? '-' : ''}${formatViPercent(Math.abs(comparison.pct_change))})`
      : ''
  return (
    <span className="inline-flex items-center gap-1 font-medium text-secondary tabular-nums">
      <Icon className="size-3.5 text-fg-quaternary" />
      {diff > 0 ? '+' : '-'}
      {formattedDiff}
      {unit}
      {pctSuffix && <span className="text-xs font-normal text-tertiary">{pctSuffix}</span>}
    </span>
  )
}

function exportCsv(data: Qc1Summary, projectName: string, periodLabel: string) {
  const rows: (string | number)[][] = [
    ['Báo cáo QC1', projectName, `Kỳ: ${periodLabel}`, `Xuất lúc ${formatCsvTimestamp()}`],
    [],
    ['Chỉ số tổng hợp', 'Giá trị'],
    ['Hoàn tất QC1 đúng hạn (%)', data.on_time_pct ?? ''],
    ['Lỗi QC1 bỏ sót (QC2 phát hiện)', data.qc2_escape_errors],
    ['Tỷ lệ job có lỗi QC1 bỏ sót (%)', data.qc1_escape_job_rate ?? ''],
    ['FPY đầu ra Annotator (%)', data.first_pass_yield?.value ?? ''],
    ['Lỗi nghiêm trọng (Critical)', data.errors_by_severity?.critical ?? 0],
    ['Lỗi nặng (Major)', data.errors_by_severity?.major ?? 0],
    ['Lỗi nhẹ (Minor)', data.errors_by_severity?.minor ?? 0],
    [],
    ['Chỉ số', 'Kỳ này', 'Kỳ trước'],
    ...KPI_ROWS.map((r) => [r.label, data.kpi.current[r.key] ?? '', data.kpi.previous[r.key] ?? '']),
    [],
    ['Ngày', 'Đã kiểm tra', 'Reject', 'Lỗi ghi nhận'],
    ...data.trend.map((d) => [d.date, d.reviewed, d.rejected, d.errors]),
  ]
  const csv = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\r\n')
  const url = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' }))
  const link = Object.assign(document.createElement('a'), {
    href: url,
    download: `bao-cao-qc1-${formatCsvFileDate()}.csv`,
  })
  link.click()
  URL.revokeObjectURL(url)
}
