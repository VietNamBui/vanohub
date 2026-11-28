import { ArrowLeft, BarChart02, Clock, InfoCircle, TrendUp01 } from '@untitledui/icons'
import type { FC } from 'react'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { Tabs } from '@/components/application/tabs/tabs'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { FeaturedIcon } from '@/components/foundations/featured-icon/featured-icon'
import { getErrorMessage } from '../../shared/api/errors'
import PageState from '../../shared/components/ui/PageState'
import SectionCard from '../../shared/components/ui/SectionCard'
import { useRequest } from '../../shared/hooks/useRequest'
import { formatNumber } from '../../shared/utils/format'
import { getAnnotatorAnalytics } from '../jobs/api'
import AnnotatorBreadcrumb from '../jobs/components/AnnotatorBreadcrumb'
import type { AnnotatorAnalytics, AnnotatorAnalyticsRange } from '../jobs/types'
import { useProject } from '../projects/projectContext'
import { buildContiguousRateRuns, formatAvgProductivitySubtitle } from './analyticsHelpers'

/** Phân tích cá nhân của Annotator: năng suất, dự báo sản lượng và xếp hạng cá nhân. */
export default function AnnotatorAnalyticsPage() {
  const { projectId } = useProject()
  const navigate = useNavigate()
  const [range, setRange] = useState<AnnotatorAnalyticsRange>('7d')

  const { data, error, isLoading, retry } = useRequest(`annotator-analytics:${projectId}:${range}`, () =>
    getAnnotatorAnalytics(projectId, range),
  )

  const weekLabel = data?.week_label ?? 'Tuần này'

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 md:p-6">
      <AnnotatorBreadcrumb
        projectId={projectId}
        items={[
          { label: 'Dashboard', to: `/projects/${projectId}/annotator/dashboard` },
          { label: 'Phân tích cá nhân' },
        ]}
      />

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Phân tích cá nhân</h1>
          <p className="mt-1 text-sm text-tertiary">
            Năng suất, dự báo sản lượng và thứ hạng của bạn · chỉ hiển thị dữ liệu của bạn
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Tabs selectedKey={range} onSelectionChange={(k) => setRange(k as AnnotatorAnalyticsRange)} className="w-auto">
            <Tabs.List type="button-border" size="sm" aria-label="Khoảng thời gian">
              <Tabs.Item id="7d" label="7 ngày" />
              <Tabs.Item id="30d" label="30 ngày" />
              <Tabs.Item id="week" label={weekLabel} />
            </Tabs.List>
          </Tabs>
          <Button
            color="secondary"
            size="sm"
            iconLeading={ArrowLeft}
            onPress={() => navigate(`/projects/${projectId}/annotator/dashboard`)}
          >
            Về tổng quan
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
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <AnalyticsKpiCard
              title="Năng suất trung bình (ước tính)"
              value={
                data.avg_productivity.objects_per_hour != null
                  ? `${formatNumber(data.avg_productivity.objects_per_hour)} / giờ`
                  : '—'
              }
              subtitle={formatAvgProductivitySubtitle(data.avg_productivity)}
              icon={TrendUp01}
            />

            <AnalyticsKpiCard
              title="Sản lượng dự báo · Ước tính"
              value={`≈ ${formatNumber(data.forecast.estimated_objects)}`}
              subtitle={`${formatNumber(data.forecast.avg_daily_objects)} / ngày × ${data.forecast.remaining_workdays} ngày công còn lại`}
              icon={Clock}
            />

            <AnalyticsKpiCard
              title="Xếp hạng sản lượng"
              value={`Hạng ${data.ranking.rank} / ${data.ranking.total_annotators}`}
              subtitle={`trong ${data.ranking.total_annotators} Annotator · ${
                data.ranking.previous_rank != null ? `kỳ trước hạng ${data.ranking.previous_rank}` : 'kỳ trước chưa có dữ liệu'
              }`}
              icon={BarChart02}
            />
          </div>

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
            <SectionCard
              className="lg:col-span-6"
              bodyClassName="flex flex-col justify-between"
              title="Năng suất theo ngày"
              description="Cuboid / giờ phiên ước tính (ANNOTATING → Chờ QC1), tách lần đầu / rework"
            >
              <div>
                <div className="flex items-center gap-5 text-xs text-tertiary">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="size-3 rounded-[3px] bg-brand-solid" />
                    Lần đầu
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="size-3 rounded-[3px] bg-warning-solid" />
                    Rework
                  </span>
                </div>

                <ProductivityLineChart data={data.daily_productivity} />
              </div>

              <p className="mt-4 text-xs text-tertiary">
                {data.avg_productivity.hours_provenance.description} Ngày nghỉ không phát sinh sản lượng không tính vào năng suất trung bình.
              </p>
            </SectionCard>

            <SectionCard
              className="lg:col-span-6"
              bodyClassName="flex flex-col justify-between"
              title={`Dự báo sản lượng ${data.week_label.toLowerCase()}`}
              description="Thực tế (cột đặc) và Ước tính (nét đứt)"
            >
              <div>
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-tertiary">
                  <div className="flex items-center gap-5">
                    <span className="inline-flex items-center gap-1.5">
                      <span className="size-3 rounded-[3px] bg-brand-solid" />
                      Thực tế
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <span className="size-3 rounded-[3px] border border-dashed border-brand bg-brand-primary" />
                      Ước tính
                    </span>
                  </div>
                  {data.forecast.daily_target > 0 && (
                    <Badge size="sm" type="pill-color" color="error">
                      Chỉ tiêu {formatNumber(data.forecast.daily_target)} / ngày
                    </Badge>
                  )}
                </div>

                <ForecastBarChart series={data.weekly_forecast_series} target={data.forecast.daily_target} />
              </div>

              <p className="mt-4 text-xs text-tertiary">
                Ước tính = năng suất TB/ngày công × ngày công còn lại; không phải cam kết.
              </p>
            </SectionCard>
          </div>

          <div className="flex items-start gap-3 rounded-xl bg-brand-primary px-5 py-4 text-sm text-brand-secondary ring-1 ring-utility-brand-200 ring-inset">
            <InfoCircle className="mt-0.5 size-5 shrink-0 text-fg-brand-primary" />
            <div>
              <p>
                Xếp hạng: sắp giảm dần sản lượng trong cùng vai trò, organization, loại việc và kỳ; bằng nhau thì đồng hạng.
              </p>
              <p>Bạn chỉ thấy hạng của mình — không hiển thị bảng xếp hạng người khác.</p>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function AnalyticsKpiCard({
  title,
  value,
  subtitle,
  icon,
}: {
  title: string
  value: string
  subtitle: string
  icon: FC<{ className?: string }>
}) {
  return (
    <div className="flex flex-col justify-between rounded-2xl bg-primary p-5 shadow-xs ring-1 ring-secondary">
      <div className="flex items-center gap-3">
        <FeaturedIcon icon={icon} color="brand" theme="light" size="md" />
        <span className="text-sm font-medium text-tertiary">{title}</span>
      </div>
      <div className="mt-4 text-display-xs font-semibold text-primary tabular-nums">{value}</div>
      <p className="mt-2 text-sm text-tertiary">{subtitle}</p>
    </div>
  )
}

function ProductivityLineChart({ data }: { data: AnnotatorAnalytics['daily_productivity'] }) {
  const active = data.filter((d) => !d.is_off_day)
  const points = active.length > 0 ? active : data
  const nonNullRates = points.flatMap((d) =>
    [d.first_pass_per_hour, d.rework_per_hour].filter((v): v is number => v != null),
  )

  if (nonNullRates.length === 0) {
    return (
      <div className="mt-4 flex h-55 items-center justify-center rounded-xl border border-dashed border-secondary bg-secondary_subtle px-4 text-center text-sm text-tertiary">
        Chưa có phiên nộp đủ dữ liệu thời gian ước tính trong kỳ để vẽ biểu đồ.
      </div>
    )
  }

  const maxRaw = Math.max(200, ...nonNullRates)
  const maxY = Math.ceil(maxRaw / 50) * 50

  const width = 460
  const height = 200
  const padL = 36
  const padR = 12
  const padT = 10
  const padB = 26
  const plotW = width - padL - padR
  const plotH = height - padT - padB
  const baselineY = padT + plotH

  const xOf = (idx: number) => (points.length <= 1 ? padL + plotW / 2 : padL + (idx * plotW) / (points.length - 1))
  const yOf = (val: number) => padT + plotH - (val / maxY) * plotH

  const fpRuns = buildContiguousRateRuns(points, (d) => d.first_pass_per_hour, xOf, yOf)
  const rwRuns = buildContiguousRateRuns(points, (d) => d.rework_per_hour, xOf, yOf)
  const labelStep = Math.max(1, Math.ceil(points.length / 7))

  return (
    <div className="mt-4 w-full overflow-x-auto">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-55 w-full" role="img" aria-label="Năng suất theo ngày">
        <defs>
          <linearGradient id="fpAreaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-bg-brand-solid)" stopOpacity="0.18" />
            <stop offset="100%" stopColor="var(--color-bg-brand-solid)" stopOpacity="0" />
          </linearGradient>
        </defs>

        {[0, 0.25, 0.5, 0.75, 1].map((t) => {
          const val = Math.round(maxY * t)
          const y = yOf(val)
          return (
            <g key={t}>
              <line x1={padL} x2={width - padR} y1={y} y2={y} stroke="var(--color-border-tertiary)" strokeWidth="1" />
              <text x={padL - 8} y={y + 4} textAnchor="end" fontSize="11" fill="var(--color-text-tertiary)">
                {val}
              </text>
            </g>
          )
        })}

        {fpRuns.map((run) => {
          if (run.length < 2) return null
          const coords = run.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`)
          const areaD = `M ${coords[0]} L ${coords.join(' L ')} L ${run[run.length - 1].x.toFixed(1)},${baselineY.toFixed(1)} L ${run[0].x.toFixed(1)},${baselineY.toFixed(1)} Z`
          return (
            <g key={`fp-seg-${run[0].item.date}`}>
              <path d={areaD} fill="url(#fpAreaGrad)" />
              <polyline fill="none" stroke="var(--color-bg-brand-solid)" strokeWidth="2.2" points={coords.join(' ')} />
            </g>
          )
        })}

        {rwRuns.map((run) => {
          if (run.length < 2) return null
          const coords = run.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
          return (
            <polyline
              key={`rw-seg-${run[0].item.date}`}
              fill="none"
              stroke="var(--color-bg-warning-solid)"
              strokeWidth="2.2"
              points={coords}
            />
          )
        })}

        {fpRuns.flatMap((run) =>
          run.map((p) => (
            <circle key={`fp-${p.item.date}`} cx={p.x} cy={p.y} r="3" fill="var(--color-bg-brand-solid)">
              <title>{`${p.item.label} · Lần đầu: ${p.value}/giờ (ước tính)`}</title>
            </circle>
          )),
        )}

        {rwRuns.flatMap((run) =>
          run.map((p) => (
            <circle key={`rw-${p.item.date}`} cx={p.x} cy={p.y} r="2.5" fill="var(--color-bg-warning-solid)">
              <title>{`${p.item.label} · Rework: ${p.value}/giờ (ước tính)`}</title>
            </circle>
          )),
        )}

        {points.map((d, i) =>
          i % labelStep === 0 ? (
            <text
              key={`lbl-${d.date}`}
              x={xOf(i)}
              y={height - 6}
              textAnchor="middle"
              fontSize="11"
              fill="var(--color-text-tertiary)"
            >
              {d.label}
            </text>
          ) : null,
        )}
      </svg>
    </div>
  )
}

function ForecastBarChart({
  series,
  target,
}: {
  series: AnnotatorAnalytics['weekly_forecast_series']
  target: number
}) {
  const maxRaw = Math.max(
    target || 1400,
    ...series.map((d) => Math.max(d.actual_objects, d.forecast_objects)),
    100,
  )
  const maxY = Math.ceil((maxRaw * 1.15) / 200) * 200
  const targetPct = target > 0 ? Math.min(100, (target / maxY) * 100) : 0

  return (
    <div className="mt-4">
      <div className="flex gap-3">
        <div className="flex h-50 flex-col justify-between text-right text-xs text-quaternary tabular-nums">
          <span>{formatNumber(maxY)}</span>
          <span>{formatNumber(Math.round(maxY / 2))}</span>
          <span>0</span>
        </div>

        <div className="relative flex-1">
          <div className="pointer-events-none absolute inset-x-0 top-0 flex h-50 flex-col justify-between">
            <div className="h-px bg-border-tertiary" />
            <div className="h-px bg-border-tertiary" />
            <div className="h-px bg-border-secondary" />
          </div>

          {target > 0 && (
            <div
              className="pointer-events-none absolute inset-x-0 border-t border-dashed border-error"
              style={{ bottom: `${targetPct}%`, height: 0 }}
            />
          )}

          <div className="relative flex h-50 items-end justify-between gap-2 px-2">
            {series.map((item) => {
              const val = item.is_forecast ? item.forecast_objects : item.actual_objects
              const hPct = Math.min(100, (val / maxY) * 100)
              return (
                <div
                  key={item.date}
                  className="flex h-full flex-1 flex-col items-center justify-end"
                  title={`${item.date}: ${formatNumber(val)} (${item.is_forecast ? 'Ước tính' : 'Thực tế'})`}
                >
                  {item.is_off_day ? (
                    <span className="mb-1 text-xs text-quaternary">Nghỉ</span>
                  ) : item.is_forecast ? (
                    <div
                      className="w-6 rounded-t-[4px] border border-dashed border-brand bg-brand-primary"
                      style={{ height: `${hPct}%`, minHeight: val > 0 ? 4 : 0 }}
                    />
                  ) : (
                    <div
                      className="w-6 rounded-t-[4px] bg-brand-solid"
                      style={{ height: `${hPct}%`, minHeight: val > 0 ? 4 : 0 }}
                    />
                  )}
                </div>
              )
            })}
          </div>
        </div>
      </div>

      <div className="mt-2 flex gap-2 pl-10 text-center text-xs text-tertiary">
        {series.map((item) => (
          <span key={item.date} className="flex-1">
            {item.day_label}
          </span>
        ))}
      </div>
    </div>
  )
}
