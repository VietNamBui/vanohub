import { ArrowDown, ArrowUp, Download01 } from '@untitledui/icons'
import { useState } from 'react'
import { Tabs } from '@/components/application/tabs/tabs'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { ProgressBar } from '@/components/base/progress-indicators/progress-indicators'
import { getErrorMessage } from '../../../shared/api/errors'
import BarChart from '../../../shared/components/ui/BarChart'
import MetricCard from '../../../shared/components/ui/MetricCard'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import StatCard from '../../../shared/components/ui/StatCard'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatCsvFileDate, formatCsvTimestamp, formatShortDate } from '../../../shared/utils/format'
import { useProject } from '../../projects/projectContext'
import { getQc2Summary } from '../api'
import { SEVERITY_LABELS } from '../constants'
import type { Qc2Summary, Qc2Window, Severity } from '../types'

type Period = 'day' | 'week' | 'month'
const PERIOD_LABELS: Record<Period, string> = { day: 'Ngày', week: 'Tuần', month: 'Tháng' }
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

const KPI_ROWS: { key: keyof Qc2Window; label: string; format?: (v: number | null) => string }[] = [
  { key: 'audited', label: 'Job đã audit' },
  { key: 'passed', label: 'Pass' },
  { key: 'rejected', label: 'Reject' },
  { key: 'pass_rate', label: 'Tỷ lệ pass', format: (v) => (v == null ? '—' : `${v}%`) },
  { key: 'errors', label: 'Lỗi ghi nhận' },
]

/**
 * Tổng quan QC2. QC2 chuyên trách xem số liệu của mình; PM (kiêm QC2) chọn được "Toàn organization".
 * "Lỗi QC1 bỏ sót" = mọi lỗi QC2 ghi nhận (job đã qua QC1). % lỗi trong job, tốc độ audit: chưa chốt công thức.
 */
export default function Qc2DashboardPage() {
  const { projectId, project, can } = useProject()
  const isManager = can('manage_audits')
  const [period, setPeriod] = useState<Period>('week')
  const [scope, setScope] = useState<'mine' | 'project'>(isManager ? 'project' : 'mine')
  const { data, error, isLoading, retry } = useRequest(`qc2-summary:${projectId}:${period}:${scope}`, () =>
    getQc2Summary(projectId, period, scope === 'mine' ? 'mine' : undefined),
  )

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Tổng quan QC2</h1>
          <p className="mt-1 text-sm text-tertiary">
            {scope === 'mine' ? 'Số liệu audit của bạn' : 'Số liệu audit toàn organization'} · {project.name}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {isManager && (
            <Tabs selectedKey={scope} onSelectionChange={(k) => setScope(k as typeof scope)} className="w-auto">
              <Tabs.List type="button-border" size="sm" aria-label="Phạm vi">
                <Tabs.Item id="project" label="Toàn organization" />
                <Tabs.Item id="mine" label="Của tôi" />
              </Tabs.List>
            </Tabs>
          )}
          <Tabs selectedKey={period} onSelectionChange={(k) => setPeriod(k as Period)} className="w-auto">
            <Tabs.List type="button-border" size="sm" aria-label="Kỳ">
              {(Object.keys(PERIOD_LABELS) as Period[]).map((p) => <Tabs.Item key={p} id={p} label={PERIOD_LABELS[p]} />)}
            </Tabs.List>
          </Tabs>
          <Button color="secondary" size="sm" iconLeading={Download01} isDisabled={!data}
            onPress={() => data && exportCsv(data, project.name, PERIOD_LABELS[period])}>
            Xuất báo cáo
          </Button>
        </div>
      </header>

      {error != null ? (
        <SectionCard><PageState kind="error" description={getErrorMessage(error)} onRetry={retry} /></SectionCard>
      ) : isLoading || !data ? (
        <SectionCard><PageState kind="loading" /></SectionCard>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard value={data.stats.pending} label="Mẫu chờ audit" />
            <StatCard value={data.kpi.current.audited} label={`Đã audit (${PERIOD_LABELS[period].toLowerCase()} này)`} />
            <StatCard value={data.pass_rate == null ? '—' : `${data.pass_rate}%`} label="Tỷ lệ pass (tích luỹ)" />
            <StatCard value={data.qc1_missed_errors} label="Lỗi QC1 bỏ sót" />
          </div>

          <SectionCard title="Bảng KPI audit QC2" description={`So sánh ${PERIOD_LABELS[period].toLowerCase()} này với kỳ trước cùng độ dài.`} bodyClassName="p-0">
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
                    return (
                      <tr key={row.key} className="border-t border-secondary">
                        <td className="px-5 py-3 font-medium text-secondary">{row.label}</td>
                        <td className="px-5 py-3 text-right text-primary tabular-nums">{fmt(current)}</td>
                        <td className="px-5 py-3 text-right text-tertiary tabular-nums">{fmt(previous)}</td>
                        <td className="px-5 py-3 text-right"><Delta current={current} previous={previous} unit={row.key === 'pass_rate' ? ' điểm %' : ''} /></td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </SectionCard>

          <div className="grid gap-5 lg:grid-cols-2">
            <SectionCard title="Tiến độ QC2 theo task" description="Mẫu đã có kết quả / tổng mẫu được giao.">
              {data.progress_by_batch.length === 0 ? (
                <PageState kind="empty" title="Chưa có mẫu audit" />
              ) : (
                <ul className="flex flex-col gap-4">
                  {data.progress_by_batch.map((b, idx) => (
                    <li key={b.batch_id ?? `${b.batch}-${idx}`}>
                      <div className="mb-1.5 flex justify-between text-sm">
                        <span className="font-medium text-secondary">
                          {b.dataset_name ? `${b.dataset_name} / ${b.batch}` : b.batch}
                        </span>
                        <span className="text-tertiary tabular-nums">{b.done}/{b.total} mẫu</span>
                      </div>
                      <ProgressBar value={b.total ? (b.done * 100) / b.total : 0} />
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>

            <SectionCard title="Thông số rework sau audit">
              <div className="grid grid-cols-2 gap-3">
                <StatCard value={data.reworked_after_audit} label="Số job trả rework" />
                <StatCard value={data.qc1_missed_errors} label="Lỗi QC1 bỏ sót (phát hiện ở QC2)" />
                <MetricCard metric={data.error_percent_in_job} label="% lỗi trong job" suffix="%" />
                <MetricCard metric={data.audit_speed} label="Tốc độ audit (job / giờ)" />
              </div>
            </SectionCard>
          </div>

          <div className="grid gap-5 lg:grid-cols-5">
            <SectionCard title="Xu hướng job bị reject" description={`Số job trả rework mỗi ngày, ${data.trend.length} ngày gần nhất. Rê chuột để xem chi tiết.`} className="lg:col-span-3">
              <BarChart
                ariaLabel="Số job bị reject theo ngày"
                data={data.trend.map((d) => ({
                  label: formatShortDate(d.date),
                  value: d.rejected,
                  details: [`Reject: ${d.rejected}`, `Đã audit: ${d.audited}`, `Lỗi ghi nhận: ${d.errors}`],
                }))}
              />
            </SectionCard>
            <div className="flex flex-col gap-5 lg:col-span-2">
              <SectionCard title="Lỗi QC2 theo mức độ" description="Chỉ tính lỗi chưa bị huỷ.">
                {(() => {
                  const severityCounts = data.errors_by_severity
                  const severityTotal = severityCounts
                    ? SEVERITY_ORDER.reduce((sum, s) => sum + (severityCounts[s] ?? 0), 0)
                    : 0
                  if (severityTotal === 0) {
                    return <p className="text-sm text-tertiary">Chưa ghi nhận lỗi QC2 nào.</p>
                  }
                  return (
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
                  )
                })()}
              </SectionCard>

              <SectionCard title="Lỗi theo loại" description="Lỗi QC2 ghi nhận, nhiều nhất trước.">
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
                            <div className="h-full rounded-full bg-brand-solid" style={{ width: `${(c.count * 100) / top}%` }} />
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

function Delta({ current, previous, unit }: { current: number | null; previous: number | null; unit: string }) {
  if (current == null || previous == null) return <span className="text-quaternary">—</span>
  const diff = Math.round((current - previous) * 10) / 10
  if (diff === 0) return <span className="text-tertiary">0</span>
  const Icon = diff > 0 ? ArrowUp : ArrowDown
  return (
    <span className="inline-flex items-center gap-1 font-medium text-secondary tabular-nums">
      <Icon className="size-3.5 text-fg-quaternary" />
      {diff > 0 ? '+' : ''}{diff}{unit}
    </span>
  )
}

/** Xuất bảng KPI + xu hướng ra CSV (mở được bằng Excel). */
function exportCsv(data: Qc2Summary, projectName: string, periodLabel: string) {
  const rows: (string | number)[][] = [
    ['Báo cáo QC2', projectName, `Kỳ: ${periodLabel}`, `Xuất lúc ${formatCsvTimestamp()}`],
    [],
    ['Chỉ số', 'Kỳ này', 'Kỳ trước'],
    ...KPI_ROWS.map((r) => [r.label, data.kpi.current[r.key] ?? '', data.kpi.previous[r.key] ?? '']),
    [],
    ['Ngày', 'Đã audit', 'Reject', 'Lỗi ghi nhận'],
    ...data.trend.map((d) => [d.date, d.audited, d.rejected, d.errors]),
    [],
    ['Task', 'Lượt đã có kết quả', 'Tổng lượt QC2'],
    ...data.progress_by_batch.map((b) => [b.batch, b.done, b.total]),
  ]
  const csv = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\r\n')
  const url = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' }))
  const link = Object.assign(document.createElement('a'), { href: url, download: `bao-cao-qc2-${formatCsvFileDate()}.csv` })
  link.click()
  URL.revokeObjectURL(url)
}
