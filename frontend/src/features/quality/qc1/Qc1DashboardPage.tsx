import { ArrowDown, ArrowUp, Download01 } from '@untitledui/icons'
import dayjs from 'dayjs'
import { useState } from 'react'
import { Tabs } from '@/components/application/tabs/tabs'
import { Button } from '@/components/base/buttons/button'
import { getErrorMessage } from '../../../shared/api/errors'
import BarChart from '../../../shared/components/ui/BarChart'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import StatCard from '../../../shared/components/ui/StatCard'
import { useRequest } from '../../../shared/hooks/useRequest'
import { useProject } from '../../projects/projectContext'
import { getQc1Summary } from '../api'
import type { Qc1Summary, Qc1Window } from '../types'

type Period = 'day' | 'week' | 'month'
const PERIOD_LABELS: Record<Period, string> = { day: 'Ngày', week: 'Tuần', month: 'Tháng' }

const KPI_ROWS: { key: keyof Qc1Window; label: string; format?: (v: number | null) => string }[] = [
  { key: 'reviewed', label: 'Job đã kiểm tra' },
  { key: 'passed', label: 'Pass → QC2' },
  { key: 'rejected', label: 'Reject → Rework' },
  { key: 'pass_rate', label: 'Tỷ lệ pass', format: (v) => (v == null ? '—' : `${v}%`) },
  { key: 'errors', label: 'Lỗi ghi nhận' },
]

/** Tổng quan Level 1 QC: KPI so sánh kỳ trước, xu hướng theo ngày, lỗi lọt sang QC2 và phân loại lỗi. */
export default function Qc1DashboardPage() {
  const { projectId, project, can } = useProject()
  const canViewProject = can('view_dashboard')
  const [period, setPeriod] = useState<Period>('week')
  const [scope, setScope] = useState<'mine' | 'project'>(canViewProject ? 'project' : 'mine')
  const { data, error, isLoading, retry } = useRequest(`qc1-summary:${projectId}:${period}:${scope}`, () =>
    getQc1Summary(projectId, period, scope === 'mine' ? 'mine' : undefined),
  )

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Tổng quan QC1</h1>
          <p className="mt-1 text-sm text-tertiary">
            {scope === 'mine' ? 'Số liệu kiểm tra QC1 của bạn' : 'Số liệu kiểm tra QC1 toàn dự án'} · {project.name}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {canViewProject && (
            <Tabs selectedKey={scope} onSelectionChange={(k) => setScope(k as typeof scope)} className="w-auto">
              <Tabs.List type="button-border" size="sm" aria-label="Phạm vi">
                <Tabs.Item id="project" label="Toàn dự án" />
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
            <StatCard value={data.stats.pending} label="Job chờ QC1" />
            <StatCard value={data.stats.reviewing} label="Đang kiểm tra QC1" />
            <StatCard value={data.pass_rate == null ? '—' : `${data.pass_rate}%`} label="Tỷ lệ pass (tích luỹ)" />
            <StatCard
              value={data.qc2_escape_errors}
              label="Lỗi lọt sang QC2"
              tone={data.qc2_escape_errors > 0 ? 'error' : undefined}
            />
          </div>

          <SectionCard
            title="Bảng KPI kiểm tra QC1"
            description={
              data.kpi_target
                ? `So sánh ${PERIOD_LABELS[period].toLowerCase()} này với kỳ trước · Mục tiêu: ${data.kpi_target} job/ngày.`
                : `So sánh ${PERIOD_LABELS[period].toLowerCase()} này với kỳ trước cùng độ dài.`
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
                    return (
                      <tr key={row.key} className="border-t border-secondary">
                        <td className="px-5 py-3 font-medium text-secondary">{row.label}</td>
                        <td className="px-5 py-3 text-right text-primary tabular-nums">{fmt(current)}</td>
                        <td className="px-5 py-3 text-right text-tertiary tabular-nums">{fmt(previous)}</td>
                        <td className="px-5 py-3 text-right">
                          <Delta current={current} previous={previous} unit={row.key === 'pass_rate' ? ' điểm %' : ''} />
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
                  label: dayjs(d.date).format('DD/MM'),
                  value: d.reviewed,
                  details: [`Đã kiểm tra: ${d.reviewed}`, `Reject: ${d.rejected}`, `Lỗi ghi nhận: ${d.errors}`],
                }))}
              />
            </SectionCard>
            <SectionCard title="Lỗi QC1 theo loại" description="Lỗi QC1 ghi nhận, nhiều nhất trước." className="lg:col-span-2">
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

function exportCsv(data: Qc1Summary, projectName: string, periodLabel: string) {
  const rows: (string | number)[][] = [
    ['Báo cáo QC1', projectName, `Kỳ: ${periodLabel}`, `Xuất lúc ${dayjs().format('DD/MM/YYYY HH:mm')}`],
    [],
    ['Chỉ số', 'Kỳ này', 'Kỳ trước'],
    ...KPI_ROWS.map((r) => [r.label, data.kpi.current[r.key] ?? '', data.kpi.previous[r.key] ?? '']),
    [],
    ['Ngày', 'Đã kiểm tra', 'Reject', 'Lỗi ghi nhận'],
    ...data.trend.map((d) => [d.date, d.reviewed, d.rejected, d.errors]),
  ]
  const csv = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\r\n')
  const url = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' }))
  const link = Object.assign(document.createElement('a'), { href: url, download: `bao-cao-qc1-${dayjs().format('YYYYMMDD')}.csv` })
  link.click()
  URL.revokeObjectURL(url)
}
