import { ArrowLeft, InfoCircle } from '@untitledui/icons'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { getErrorMessage } from '../../shared/api/errors'
import PageState from '../../shared/components/ui/PageState'
import { useRequest } from '../../shared/hooks/useRequest'
import { formatNumber } from '../../shared/utils/format'
import { getAnnotatorAnalytics } from '../jobs/api'
import AnnotatorBreadcrumb from '../jobs/components/AnnotatorBreadcrumb'
import type { AnnotatorAnalytics, AnnotatorAnalyticsRange } from '../jobs/types'
import { useProject } from '../projects/projectContext'

/** Phân tích cá nhân (P2): Năng suất NS03/NS01, Dự báo sản lượng DB05 và Xếp hạng cá nhân KPI10 (chỉ dữ liệu PQ01). */
export default function AnnotatorAnalyticsPage() {
  const { projectId } = useProject()
  const navigate = useNavigate()
  const [range, setRange] = useState<AnnotatorAnalyticsRange>('7d')

  const { data, error, isLoading, retry } = useRequest(`annotator-analytics:${projectId}:${range}`, () =>
    getAnnotatorAnalytics(projectId, range),
  )

  const weekLabel = data?.week_label ?? 'Tuần này'

  return (
    <div className="mx-auto flex max-w-[1160px] flex-col gap-6 px-6 py-7">
      <AnnotatorBreadcrumb
        projectId={projectId}
        items={[
          { label: 'Dashboard', to: `/projects/${projectId}/annotator/dashboard` },
          { label: 'Phân tích cá nhân' },
        ]}
      />

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-[30px] leading-tight font-bold text-[#101828]">Phân tích cá nhân</h1>
            <Badge size="sm" type="pill-color" color="blue">
              P2
            </Badge>
          </div>
          <p className="mt-1 text-base text-[#475467]">
            Năng suất, dự báo sản lượng và thứ hạng của bạn · chỉ dữ liệu của bạn (PQ01)
          </p>
        </div>

        <Button
          color="secondary"
          size="md"
          iconLeading={ArrowLeft}
          onPress={() => navigate(`/projects/${projectId}/annotator/dashboard`)}
        >
          Về tổng quan
        </Button>
      </header>

      {/* Period segmented toggle */}
      <div className="inline-flex w-max overflow-hidden rounded-lg border border-[#D0D5DD] bg-white">
        {(
          [
            { id: '7d', label: '7 ngày' },
            { id: '30d', label: '30 ngày' },
            { id: 'week', label: weekLabel },
          ] as { id: AnnotatorAnalyticsRange; label: string }[]
        ).map((item, idx) => {
          const active = range === item.id
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => setRange(item.id)}
              className={`cursor-pointer px-4 py-2 text-sm font-semibold transition ${
                idx > 0 ? 'border-l border-[#D0D5DD]' : ''
              } ${active ? 'bg-[#F9FAFB] text-[#182230]' : 'bg-white text-[#344054] hover:bg-[#F9FAFB]'}`}
            >
              {item.label}
            </button>
          )
        })}
      </div>

      {error != null ? (
        <div className="rounded-xl border border-[#EAECF0] bg-white p-6">
          <PageState kind="error" description={getErrorMessage(error)} onRetry={retry} />
        </div>
      ) : isLoading || !data ? (
        <div className="rounded-xl border border-[#EAECF0] bg-white p-6">
          <PageState kind="loading" />
        </div>
      ) : (
        <>
          {/* 3 KPI cards */}
          <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
            <AnalyticsKpiCard
              title="Năng suất trung bình"
              value={`${formatNumber(data.avg_productivity.objects_per_hour)} / giờ`}
              code="NS03"
              subtitle={`${formatNumber(data.avg_productivity.total_objects)} cuboid ÷ ${data.avg_productivity.total_hours.toFixed(1).replace('.', ',')} giờ (NS01)`}
              icon={
                <svg className="size-5" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7">
                  <path d="M3 14.5 8 9.5l3 3 6-6.5" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M13.5 6H17v3.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              }
            />

            <AnalyticsKpiCard
              title="Sản lượng dự báo · Ước tính"
              value={`≈ ${formatNumber(data.forecast.estimated_objects)}`}
              code="DB05"
              subtitle={`${formatNumber(data.forecast.avg_daily_objects)} / ngày × ${data.forecast.remaining_workdays} ngày công còn lại`}
              icon={
                <svg className="size-5" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7">
                  <circle cx="10" cy="10" r="7" />
                  <path d="M10 6v4l2.5 2.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              }
            />

            <AnalyticsKpiCard
              title="Xếp hạng sản lượng"
              value={`Hạng ${data.ranking.rank} / ${data.ranking.total_annotators}`}
              code="KPI10"
              subtitle={`trong ${data.ranking.total_annotators} Annotator · kỳ trước hạng ${data.ranking.previous_rank}`}
              icon={
                <svg className="size-5" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7">
                  <path d="M6 16V9M10 16V4M14 16v-5" strokeLinecap="round" />
                </svg>
              }
            />
          </div>

          {/* 2 Charts */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
            {/* Năng suất theo ngày */}
            <section className="flex flex-col justify-between rounded-xl border border-[#EAECF0] bg-white p-6 lg:col-span-6">
              <div>
                <h2 className="text-lg font-bold text-[#101828]">Năng suất theo ngày</h2>
                <p className="mt-1 text-sm text-[#475467]">
                  Cuboid / giờ làm thực tế, tách lần đầu / rework (NS03)
                </p>

                <div className="mt-4 flex items-center gap-5 text-xs text-[#475467]">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="size-3 rounded-[3px] bg-[#7F56D9]" />
                    Lần đầu
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="size-3 rounded-[3px] bg-[#F79009]" />
                    Rework
                  </span>
                </div>

                <ProductivityLineChart data={data.daily_productivity} />
              </div>

              <p className="mt-4 text-xs text-[#667085]">
                Ngày nghỉ không phát sinh sản lượng — không tính vào năng suất trung bình.
              </p>
            </section>

            {/* Dự báo sản lượng tuần */}
            <section className="flex flex-col justify-between rounded-xl border border-[#EAECF0] bg-white p-6 lg:col-span-6">
              <div>
                <h2 className="text-lg font-bold text-[#101828]">Dự báo sản lượng {data.week_label.toLowerCase()}</h2>
                <p className="mt-1 text-sm text-[#475467]">
                  Thực tế (cột đặc) và Ước tính (nét đứt) — DB05
                </p>

                <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-xs text-[#475467]">
                  <div className="flex items-center gap-5">
                    <span className="inline-flex items-center gap-1.5">
                      <span className="size-3 rounded-[3px] bg-[#7F56D9]" />
                      Thực tế
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <span className="size-3 rounded-[3px] border border-dashed border-[#B692F6] bg-[#F9F5FF]" />
                      Ước tính
                    </span>
                  </div>
                  {data.forecast.daily_target > 0 && (
                    <span className="font-medium text-[#D92D20]">
                      KPI01 {formatNumber(data.forecast.daily_target)} / ngày
                    </span>
                  )}
                </div>

                <ForecastBarChart series={data.weekly_forecast_series} target={data.forecast.daily_target} />
              </div>

              <p className="mt-4 text-xs text-[#667085]">
                Ước tính = năng suất TB/ngày công × ngày công còn lại; không phải cam kết.
              </p>
            </section>
          </div>

          {/* Info banner KPI10 */}
          <div className="flex items-start gap-3 rounded-xl border border-[#E9D7FE] bg-[#FCFAFF] px-5 py-4 text-[13px] leading-relaxed text-[#6941C6]">
            <InfoCircle className="mt-0.5 size-5 shrink-0 text-[#7F56D9]" />
            <div>
              <p>
                Xếp hạng (KPI10): sắp giảm dần sản lượng trong cùng vai trò, dự án, loại việc và kỳ; bằng nhau thì đồng hạng.
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
  code,
  subtitle,
  icon,
}: {
  title: string
  value: string
  code: string
  subtitle: string
  icon: React.ReactNode
}) {
  return (
    <div className="flex flex-col justify-between rounded-xl border border-[#EAECF0] bg-white p-5">
      <div className="flex items-center gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-[#F9F5FF]">
          <span className="flex size-7 items-center justify-center rounded-full bg-[#E9D7FE] text-[#6941C6]">
            {icon}
          </span>
        </span>
        <span className="text-sm text-[#475467]">{title}</span>
      </div>
      <div className="mt-4 flex items-baseline justify-between gap-2">
        <span className="text-[30px] leading-none font-bold text-[#101828] tabular-nums">{value}</span>
        <span className="text-[11px] text-[#98A2B3]">{code}</span>
      </div>
      <p className="mt-2.5 text-sm text-[#475467]">{subtitle}</p>
    </div>
  )
}

function ProductivityLineChart({ data }: { data: AnnotatorAnalytics['daily_productivity'] }) {
  const active = data.filter((d) => !d.is_off_day)
  const points = active.length > 0 ? active : data
  const maxRaw = Math.max(200, ...points.map((d) => Math.max(d.first_pass_per_hour, d.rework_per_hour)))
  const maxY = Math.ceil(maxRaw / 50) * 50

  const width = 460
  const height = 200
  const padL = 36
  const padR = 12
  const padT = 10
  const padB = 26
  const plotW = width - padL - padR
  const plotH = height - padT - padB

  const xOf = (idx: number) => (points.length <= 1 ? padL + plotW / 2 : padL + (idx * plotW) / (points.length - 1))
  const yOf = (val: number) => padT + plotH - (val / maxY) * plotH

  const fpCoords = points.map((d, i) => `${xOf(i).toFixed(1)},${yOf(d.first_pass_per_hour).toFixed(1)}`)
  const rwCoords = points.map((d, i) => `${xOf(i).toFixed(1)},${yOf(d.rework_per_hour).toFixed(1)}`)

  const areaPath =
    points.length > 1
      ? `M ${fpCoords[0]} L ${fpCoords.join(' L ')} L ${xOf(points.length - 1).toFixed(1)},${(padT + plotH).toFixed(1)} L ${xOf(0).toFixed(1)},${(padT + plotH).toFixed(1)} Z`
      : ''

  const labelStep = Math.max(1, Math.ceil(points.length / 7))

  return (
    <div className="mt-4 w-full overflow-x-auto">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-[220px] w-full" role="img" aria-label="Năng suất theo ngày">
        <defs>
          <linearGradient id="fpAreaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#7F56D9" stopOpacity="0.18" />
            <stop offset="100%" stopColor="#7F56D9" stopOpacity="0" />
          </linearGradient>
        </defs>

        {[0, 0.25, 0.5, 0.75, 1].map((t) => {
          const val = Math.round(maxY * t)
          const y = yOf(val)
          return (
            <g key={t}>
              <line x1={padL} x2={width - padR} y1={y} y2={y} stroke="#F2F4F7" strokeWidth="1" />
              <text x={padL - 8} y={y + 4} textAnchor="end" fontSize="11" fill="#475467">
                {val}
              </text>
            </g>
          )
        })}

        {areaPath && <path d={areaPath} fill="url(#fpAreaGrad)" />}
        {fpCoords.length > 1 && (
          <polyline fill="none" stroke="#7F56D9" strokeWidth="2.2" points={fpCoords.join(' ')} />
        )}
        {rwCoords.length > 1 && (
          <polyline fill="none" stroke="#F79009" strokeWidth="2.2" points={rwCoords.join(' ')} />
        )}

        {points.map((d, i) => (
          <g key={d.date}>
            <circle cx={xOf(i)} cy={yOf(d.first_pass_per_hour)} r="3" fill="#7F56D9">
              <title>{`${d.label} · Lần đầu: ${d.first_pass_per_hour}/giờ`}</title>
            </circle>
            <circle cx={xOf(i)} cy={yOf(d.rework_per_hour)} r="2.5" fill="#F79009">
              <title>{`${d.label} · Rework: ${d.rework_per_hour}/giờ`}</title>
            </circle>
            {i % labelStep === 0 && (
              <text x={xOf(i)} y={height - 6} textAnchor="middle" fontSize="11" fill="#475467">
                {d.label}
              </text>
            )}
          </g>
        ))}
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
        <div className="flex h-[200px] flex-col justify-between text-right text-[11px] text-[#667085] tabular-nums">
          <span>{formatNumber(maxY)}</span>
          <span>{formatNumber(Math.round(maxY / 2))}</span>
          <span>0</span>
        </div>

        <div className="relative flex-1">
          <div className="pointer-events-none absolute inset-x-0 top-0 flex h-[200px] flex-col justify-between">
            <div className="h-px bg-[#F2F4F7]" />
            <div className="h-px bg-[#F2F4F7]" />
            <div className="h-px bg-[#EAECF0]" />
          </div>

          {target > 0 && (
            <div
              className="pointer-events-none absolute inset-x-0 border-t border-dashed border-[#D92D20]"
              style={{ bottom: `${targetPct}%`, height: 0 }}
            />
          )}

          <div className="relative flex h-[200px] items-end justify-between gap-2 px-2">
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
                    <span className="mb-1 text-[11px] text-[#98A2B3]">Nghỉ</span>
                  ) : item.is_forecast ? (
                    <div
                      className="w-6 rounded-t-[4px] border border-dashed border-[#B692F6] bg-[#F9F5FF]"
                      style={{ height: `${hPct}%`, minHeight: val > 0 ? 4 : 0 }}
                    />
                  ) : (
                    <div
                      className="w-6 rounded-t-[4px] bg-[#7F56D9]"
                      style={{ height: `${hPct}%`, minHeight: val > 0 ? 4 : 0 }}
                    />
                  )}
                </div>
              )
            })}
          </div>
        </div>
      </div>

      <div className="mt-2 flex gap-2 pl-10 text-center text-[11px] text-[#475467]">
        {series.map((item) => (
          <span key={item.date} className="flex-1">
            {item.day_label}
          </span>
        ))}
      </div>
    </div>
  )
}
