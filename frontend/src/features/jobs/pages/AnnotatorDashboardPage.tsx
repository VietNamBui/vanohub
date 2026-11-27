import { AlertTriangle, ArrowRight, CheckCircle, Clock, Target04 } from '@untitledui/icons'
import type { FC } from 'react'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { Badge, BadgeWithDot } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { ProgressBarBase } from '@/components/base/progress-indicators/progress-indicators'
import { FeaturedIcon } from '@/components/foundations/featured-icon/featured-icon'
import { useShell } from '../../../layouts/ShellContext'
import { getErrorMessage } from '../../../shared/api/errors'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime, formatNumber, formatShortDateTime, VN_TIME_ZONE } from '../../../shared/utils/format'
import { useAuth } from '../../auth/useAuth'
import { useProject } from '../../projects/projectContext'
import { SEVERITY_LABELS } from '../../quality/constants'
import type { Severity } from '../../quality/types'
import { getAnnotatorDashboard } from '../api'
import AnnotatorBreadcrumb from '../components/AnnotatorBreadcrumb'
import AnnotatorJobDrawer from '../components/AnnotatorJobDrawer'
import JobStatusBadge from '../components/JobStatusBadge'
import { formatDeadlineCountdown } from '../constants'
import type { AnnotatorDailyResult, AnnotatorRequestStatus } from '../types'

function getGreeting() {
  const hourStr = new Intl.DateTimeFormat('en-GB', {
    timeZone: VN_TIME_ZONE,
    hour: '2-digit',
    hourCycle: 'h23',
  }).format(new Date())
  const hour = Number(hourStr)
  if (hour < 12) return 'Chào buổi sáng'
  if (hour < 18) return 'Chào buổi chiều'
  return 'Chào buổi tối'
}

function getShortName(fullName?: string, firstName?: string, username?: string) {
  if (fullName) {
    const parts = fullName.trim().split(/\s+/)
    if (parts.length > 0) return parts[parts.length - 1]
  }
  return firstName || username || 'bạn'
}

function formatViPercent(val: number | null) {
  if (val == null) return '—'
  return `${val.toFixed(1).replace('.', ',')}%`
}

const SEVERITY_BADGE: Record<string, 'gray' | 'warning' | 'error'> = {
  minor: 'gray',
  major: 'warning',
  critical: 'error',
}

const REQUEST_STATUS_COLOR: Record<AnnotatorRequestStatus, 'warning' | 'success' | 'error' | 'gray'> = {
  pending_pm: 'warning',
  resolved: 'success',
  rejected: 'error',
}

/** Tổng quan cá nhân của Annotator trên VanoHub (KPI, công việc tiếp theo, việc cần sửa, kết quả theo ngày, yêu cầu). */
export default function AnnotatorDashboardPage() {
  const { projectId, project } = useProject()
  const { user } = useAuth()
  const { setTeamLeaderName } = useShell()
  const navigate = useNavigate()
  const [drawerJobId, setDrawerJobId] = useState<number | null>(null)

  const { data, error, isLoading, retry } = useRequest(`annotator-dashboard:${projectId}:week`, () =>
    getAnnotatorDashboard(projectId, 'week'),
  )

  useEffect(() => {
    if (data?.meta?.team_leader_name) {
      setTeamLeaderName(data.meta.team_leader_name)
    }
  }, [data?.meta?.team_leader_name, setTeamLeaderName])

  const firstName = getShortName(user?.full_name, user?.first_name, user?.username)
  const syncText = data?.meta?.last_cvat_sync_at
    ? `đồng bộ CVAT lần cuối ${formatDateTime(data.meta.last_cvat_sync_at)}`
    : 'giờ Việt Nam'

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 md:p-6">
      <AnnotatorBreadcrumb
        projectId={projectId}
        items={[
          { label: 'Dashboard', to: `/projects/${projectId}/annotator/dashboard` },
          { label: 'Tổng quan cá nhân' },
        ]}
      />

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">
            {getGreeting()}, {firstName}
          </h1>
          <p className="mt-1 text-sm text-tertiary">
            {[data?.meta?.team_name, project.name, syncText].filter(Boolean).join(' · ')}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button
            color="secondary"
            size="md"
            onPress={() => navigate(`/projects/${projectId}/annotator/analytics`)}
          >
            Phân tích cá nhân
          </Button>
          <Button
            color="primary"
            size="md"
            onPress={() => navigate(`/projects/${projectId}/annotator/jobs`)}
          >
            Job của tôi
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
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard
              title="Sản lượng / chỉ tiêu"
              value={
                data.kpi_summary.achievement_pct != null
                  ? formatViPercent(data.kpi_summary.achievement_pct)
                  : formatNumber(data.kpi_summary.actual_objects)
              }
              subtitle={
                data.kpi_summary.target_objects
                  ? `${formatNumber(data.kpi_summary.actual_objects)} / ${formatNumber(data.kpi_summary.target_objects)} · thiếu ${formatNumber(data.kpi_summary.shortfall)}`
                  : `${formatNumber(data.kpi_summary.actual_objects)} object-frame hoàn tất`
              }
              tone="brand"
              icon={Target04}
              onClick={() => navigate(`/projects/${projectId}/annotator/analytics`)}
            />

            <KpiCard
              title="Job cần sửa"
              value={String(data.kpi_summary.rework_jobs_count)}
              subtitle={
                data.kpi_summary.rework_jobs_count > 0
                  ? `job · vòng sửa ${data.kpi_summary.max_rework_round_active} / ${data.kpi_summary.max_rework_rounds}`
                  : `0 job cần sửa (tối đa ${data.kpi_summary.max_rework_rounds} vòng)`
              }
              tone={data.kpi_summary.rework_jobs_count > 0 ? 'warning' : 'brand'}
              icon={AlertTriangle}
              onClick={() => navigate(`/projects/${projectId}/annotator/rework`)}
            />

            <KpiCard
              title="Job sắp / quá hạn"
              value={String(data.kpi_summary.due_soon_count + data.kpi_summary.overdue_count)}
              subtitle={`${data.kpi_summary.due_soon_count} sắp hạn · ${data.kpi_summary.overdue_count} quá hạn`}
              tone={data.kpi_summary.due_soon_count + data.kpi_summary.overdue_count > 0 ? 'warning' : 'brand'}
              icon={Clock}
              onClick={() => navigate(`/projects/${projectId}/annotator/jobs?due_soon=1`)}
            />

            <KpiCard
              title="FPY cá nhân"
              value={formatViPercent(data.kpi_summary.fpy_pct)}
              subtitle={`${data.kpi_summary.fpy_passed} / ${data.kpi_summary.fpy_total} job đạt`}
              tone="brand"
              icon={CheckCircle}
            />
          </div>

          <SectionCard
            title="Công việc tiếp theo"
            description={`Đang giữ ${data.meta.active_jobs_count} / ${data.meta.wip_limit} job · ${formatNumber(data.meta.active_object_frames)} object-frame · ưu tiên: quá hạn → sắp hạn → còn lại`}
            bodyClassName="p-0"
          >
            {data.next_jobs.length === 0 ? (
              <PageState
                kind="empty"
                title="Không có job đang mở"
                description='Nhấn "Job của tôi" → "Nhận job mới" để nhận thêm công việc từ hàng chờ.'
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[780px] text-left text-sm">
                  <thead className="bg-secondary text-xs font-semibold text-quaternary">
                    <tr>
                      <th className="px-5 py-3">Job</th>
                      <th className="px-4 py-3">Trạng thái</th>
                      <th className="px-4 py-3">Tiến độ</th>
                      <th className="px-4 py-3">Hạn</th>
                      <th className="px-4 py-3">Ưu tiên</th>
                      <th className="px-5 py-3 text-right">Thao tác</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-secondary">
                    {data.next_jobs.map((job, idx) => {
                      const target = job.target_object_count || job.object_count
                      const pct = job.progress_percent ?? 0
                      const countdown = formatDeadlineCountdown(job.hours_remaining)
                      const isRework = job.status === 'rework'
                      const isWarnOnlyEscalated =
                        job.is_escalated && (job.escalation_policy ?? project.escalation_policy ?? 'block') === 'warn_only'
                      return (
                        <tr
                          key={job.id}
                          onClick={() => setDrawerJobId(job.id)}
                          className="cursor-pointer transition hover:bg-primary_hover"
                        >
                          <td className="px-5 py-3.5">
                            <div className="font-semibold text-primary">{job.name}</div>
                            <div className="mt-0.5 text-xs text-tertiary">
                              {job.batch_name} · {formatNumber(target)} obj-frame
                            </div>
                          </td>
                          <td className="px-4 py-3.5">
                            <JobStatusBadge
                              status={job.status}
                              escalated={job.is_escalated}
                              overdue={job.is_overdue}
                              locked={job.is_locked}
                              sourceMissing={job.source_missing}
                            />
                            <div className="mt-1 text-xs text-tertiary">
                              {job.rework_round > 0 ? `Vòng sửa ${job.rework_round} / ${job.max_rework_rounds}` : 'Lần làm đầu'}
                            </div>
                            {isWarnOnlyEscalated && (
                              <div className="mt-1 text-xs text-warning-primary">
                                Chế độ cảnh báo — vẫn có thể tiếp tục sửa
                              </div>
                            )}
                          </td>
                          <td className="w-56 px-4 py-3.5">
                            <div className="mb-1.5 text-xs text-secondary tabular-nums">
                              {pct}% · {formatNumber(job.object_count)} / {formatNumber(target)}
                            </div>
                            <ProgressBarBase value={pct} />
                          </td>
                          <td className="px-4 py-3.5">
                            <div className="text-xs font-medium text-secondary">
                              {job.deadline ? formatShortDateTime(job.deadline) : 'Chưa đặt'}
                            </div>
                            {countdown && (
                              <div className="mt-1">
                                <Badge size="sm" type="pill-color" color={countdown.tone}>
                                  {countdown.text}
                                </Badge>
                              </div>
                            )}
                          </td>
                          <td className="px-4 py-3.5">
                            <Badge size="sm" type="pill-color" color={isRework ? 'warning' : 'gray'}>
                              {isRework ? 'Rework' : 'Bình thường'}
                            </Badge>
                          </td>
                          <td className="px-5 py-3.5 text-right" onClick={(e) => e.stopPropagation()}>
                            <Button
                              size="sm"
                              color={idx === 0 ? 'primary' : 'secondary'}
                              onPress={() => navigate(`/projects/${projectId}/annotator/jobs/${job.id}`)}
                            >
                              Tiếp tục làm
                            </Button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </SectionCard>

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
            <SectionCard
              className="lg:col-span-7"
              bodyClassName="flex flex-col justify-between"
              title={
                <span className="inline-flex flex-wrap items-center gap-2.5">
                  <span>Việc cần sửa</span>
                  {data.rework_focus && (
                    <Badge size="sm" type="pill-color" color="warning">
                      {data.rework_focus.error_count} lỗi
                    </Badge>
                  )}
                </span>
              }
              description={
                data.rework_focus
                  ? `${data.rework_focus.job_name}${data.rework_focus.deadline ? ` · hạn ${formatShortDateTime(data.rework_focus.deadline)}` : ''} · lỗi theo object-frame`
                  : undefined
              }
            >
              <div>
                {data.rework_focus ? (
                  <>
                    <div className="grid grid-cols-3 gap-3">
                      <MiniStat label="Lỗi cần sửa" value={String(data.rework_focus.error_count)} />
                      <MiniStat
                        label="Vòng rework"
                        value={`${data.rework_focus.rework_round} / ${data.rework_focus.max_rework_rounds}`}
                      />
                      <MiniStat
                        label="Chờ sửa"
                        value={`${data.rework_focus.pending_object_frames} obj-frame`}
                      />
                    </div>

                    {(() => {
                      const activeFocusErrors = data.rework_focus.errors.filter(
                        (err) =>
                          !err.is_voided &&
                          (data.rework_focus!.rework_round > 0
                            ? err.rework_round === data.rework_focus!.rework_round - 1
                            : true),
                      )
                      return (
                        <ul className="mt-4 divide-y divide-secondary">
                          {activeFocusErrors.slice(0, 3).map((err) => (
                            <li
                              key={err.id}
                              onClick={() => navigate(`/projects/${projectId}/annotator/jobs/${data.rework_focus!.job_id}`)}
                              className="flex cursor-pointer items-start justify-between gap-3 py-3 transition hover:bg-primary_hover"
                            >
                              <div className="flex items-start gap-3">
                                <div className="w-28 shrink-0 pt-0.5">
                                  <BadgeWithDot size="sm" type="pill-color" color={SEVERITY_BADGE[err.severity] ?? 'warning'}>
                                    {SEVERITY_LABELS[err.severity as Severity] ?? err.severity}
                                  </BadgeWithDot>
                                </div>
                                <div className="min-w-0">
                                  <p className="text-sm font-medium text-primary">{err.category}</p>
                                  {(err.frame_number != null ||
                                    err.cvat_object_id != null ||
                                    err.is_missing_object ||
                                    err.verdict === 'edge') && (
                                    <div className="mt-1 flex flex-wrap gap-1">
                                      {err.frame_number != null && (
                                        <Badge size="sm" type="pill-color" color="gray">
                                          Frame #{err.frame_number}
                                        </Badge>
                                      )}
                                      {err.cvat_object_id != null && (
                                        <Badge size="sm" type="pill-color" color="blue">
                                          Object #{err.cvat_object_id}
                                        </Badge>
                                      )}
                                      {err.is_missing_object && (
                                        <Badge size="sm" type="pill-color" color="orange">
                                          Thiếu đối tượng
                                        </Badge>
                                      )}
                                      {err.verdict === 'edge' && (
                                        <Badge size="sm" type="pill-color" color="warning">
                                          Cận biên
                                        </Badge>
                                      )}
                                    </div>
                                  )}
                                  {err.description && <p className="mt-0.5 text-xs text-tertiary">{err.description}</p>}
                                </div>
                              </div>
                              <span className="shrink-0 text-right text-xs text-secondary">
                                {err.location || `vòng ${err.rework_round}`}
                              </span>
                            </li>
                          ))}
                          {activeFocusErrors.length === 0 && (
                            <li className="py-6 text-center text-sm text-tertiary">Chưa có ghi chú lỗi chi tiết.</li>
                          )}
                        </ul>
                      )
                    })()}
                  </>
                ) : (
                  <PageState
                    kind="empty"
                    title="Không có việc cần sửa"
                    description="Tất cả job của bạn đều đang trong luồng làm bình thường hoặc đã đạt QC1."
                  />
                )}
              </div>

              <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-secondary pt-4">
                <span className="text-xs text-tertiary">
                  {project.escalation_policy === 'warn_only'
                    ? 'Sửa theo ghi chú từng lỗi · vượt quá số vòng tối đa sẽ cảnh báo và bạn vẫn có thể tiếp tục sửa'
                    : 'Sửa theo ghi chú từng lỗi · vượt quá số vòng tối đa sẽ tạm khoá và chuyển Project Manager xem xét'}
                </span>
                <Link
                  to={`/projects/${projectId}/annotator/rework`}
                  className="inline-flex items-center gap-1.5 text-sm font-semibold text-brand-secondary transition hover:text-brand-secondary_hover"
                >
                  Xem tất cả lỗi
                  <ArrowRight className="size-4" />
                </Link>
              </div>
            </SectionCard>

            <SectionCard
              className="lg:col-span-5"
              bodyClassName="flex flex-col justify-between"
              title="Kết quả theo ngày"
              description="Lần đầu / rework so với chỉ tiêu"
            >
              <div>
                <div className="rounded-xl bg-secondary px-4 py-3 ring-1 ring-secondary ring-inset">
                  <div className="text-xs text-tertiary">Nộp đúng hạn</div>
                  <div className="mt-1 flex items-baseline gap-2.5">
                    <span className="text-xl font-semibold text-primary tabular-nums">
                      {formatViPercent(data.kpi_summary.on_time_pct)}
                    </span>
                    <span className="text-xs text-tertiary">
                      {data.kpi_summary.on_time_count} / {data.kpi_summary.submitted_total} job nộp đúng hạn
                    </span>
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap items-center gap-4 text-xs text-tertiary">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="size-3 rounded-[3px] bg-brand-solid" />
                    Lần đầu
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="size-3 rounded-[3px] bg-utility-brand-300" />
                    Rework
                  </span>
                  {data.kpi_target != null && data.kpi_target > 0 && (
                    <span className="inline-flex items-center gap-1.5">
                      <span className="h-0.5 w-4 border-t-2 border-dashed border-error" />
                      Chỉ tiêu
                    </span>
                  )}
                </div>

                <DailyStackedChart data={data.daily_results} target={data.kpi_target ?? undefined} />
              </div>

              <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-secondary pt-4">
                <span className="text-xs text-tertiary">Phần rework vẫn tính KPI</span>
                <Link
                  to={`/projects/${projectId}/annotator/analytics`}
                  className="inline-flex items-center gap-1.5 text-sm font-semibold text-brand-secondary transition hover:text-brand-secondary_hover"
                >
                  Phân tích cá nhân
                  <ArrowRight className="size-4" />
                </Link>
              </div>
            </SectionCard>
          </div>

          <SectionCard
            title={
              <span className="inline-flex items-center gap-2.5">
                <span>Yêu cầu của tôi</span>
                {data.recent_requests.pending_count > 0 && (
                  <Badge size="sm" type="pill-color" color="warning">
                    {data.recent_requests.pending_count} đang chờ
                  </Badge>
                )}
              </span>
            }
            description="Phản hồi lỗi & dữ liệu bị chặn: người đang xử lý và kết luận"
            actions={
              <Button
                color="secondary"
                size="sm"
                onPress={() => navigate(`/projects/${projectId}/annotator/requests`)}
              >
                Xem tất cả
              </Button>
            }
            bodyClassName="p-0"
          >
            {data.recent_requests.items.length === 0 ? (
              <PageState
                kind="empty"
                title="Chưa có yêu cầu nào"
                description="Phản hồi lỗi QC1 hoặc báo cáo dữ liệu bị chặn sẽ hiển thị tại đây."
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[700px] text-left text-sm">
                  <thead className="bg-secondary text-xs font-semibold text-quaternary">
                    <tr>
                      <th className="px-5 py-3">Loại</th>
                      <th className="px-4 py-3">Đối tượng / nội dung</th>
                      <th className="px-4 py-3">Người xử lý</th>
                      <th className="px-5 py-3">Kết luận</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-secondary">
                    {data.recent_requests.items.map((req) => (
                      <tr
                        key={req.id}
                        onClick={() => navigate(`/projects/${projectId}/annotator/requests`)}
                        className="cursor-pointer transition hover:bg-primary_hover"
                      >
                        <td className="px-5 py-3.5">
                          <Badge
                            size="sm"
                            type="pill-color"
                            color={req.request_type === 'error_dispute' ? 'blue' : 'gray'}
                          >
                            {req.request_type_label}
                          </Badge>
                        </td>
                        <td className="px-4 py-3.5">
                          <div className="font-semibold text-primary">{req.job_name}</div>
                          <div className="mt-0.5 text-xs text-tertiary">{req.title}</div>
                        </td>
                        <td className="px-4 py-3.5 text-secondary">
                          {req.handler ? `${req.handler.full_name} (${req.handler_role})` : req.handler_role}
                        </td>
                        <td className="px-5 py-3.5">
                          <BadgeWithDot size="sm" type="pill-color" color={REQUEST_STATUS_COLOR[req.status]}>
                            {req.status_label}
                          </BadgeWithDot>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </SectionCard>
        </>
      )}

      <AnnotatorJobDrawer projectId={projectId} jobId={drawerJobId} onClose={() => setDrawerJobId(null)} />
    </div>
  )
}

function KpiCard({
  title,
  value,
  subtitle,
  tone,
  icon,
  onClick,
}: {
  title: string
  value: string
  subtitle: string
  tone: 'brand' | 'warning'
  icon: FC<{ className?: string }>
  onClick?: () => void
}) {
  const isWarn = tone === 'warning'
  const cardClasses = `flex flex-col justify-between rounded-2xl bg-primary p-5 text-left shadow-xs ring-1 transition ${
    isWarn ? 'ring-utility-yellow-200' : 'ring-secondary'
  } ${onClick ? 'cursor-pointer hover:bg-primary_hover' : ''}`

  const content = (
    <>
      <div className="flex items-center gap-3">
        <FeaturedIcon icon={icon} color={isWarn ? 'warning' : 'brand'} theme="light" size="md" />
        <span className="text-sm font-medium text-tertiary">{title}</span>
      </div>
      <div className="mt-4 text-display-xs font-semibold text-primary tabular-nums">{value}</div>
      <p className="mt-2 truncate text-sm text-tertiary" title={subtitle}>
        {subtitle}
      </p>
    </>
  )

  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={cardClasses}>
        {content}
      </button>
    )
  }

  return <div className={cardClasses}>{content}</div>
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-secondary px-3 py-2.5 ring-1 ring-secondary ring-inset">
      <div className="text-xs text-tertiary">{label}</div>
      <div className="mt-1 text-lg font-semibold text-primary tabular-nums">{value}</div>
    </div>
  )
}

function DailyStackedChart({ data, target }: { data: AnnotatorDailyResult[]; target?: number }) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)
  const targetVal = target ?? 0
  const rawMax = Math.max(targetVal, ...data.map((d) => d.total_objects), 100)
  const maxY = Math.ceil((rawMax * 1.15) / 200) * 200
  const targetPct = targetVal > 0 ? Math.min(100, (targetVal / maxY) * 100) : 0

  return (
    <div className="relative mt-4">
      <div className="flex gap-3">
        <div className="flex h-[120px] flex-col justify-between text-right text-xs text-quaternary tabular-nums">
          <span>{formatNumber(maxY)}</span>
          <span>{formatNumber(Math.round(maxY / 2))}</span>
          <span>0</span>
        </div>

        <div className="relative flex-1">
          <div className="pointer-events-none absolute inset-x-0 top-0 flex h-[120px] flex-col justify-between">
            <div className="h-px bg-border-tertiary" />
            <div className="h-px bg-border-tertiary" />
            <div className="h-px bg-border-secondary" />
          </div>

          {targetVal > 0 && (
            <div
              className="pointer-events-none absolute inset-x-0 border-t border-dashed border-error"
              style={{ bottom: `${targetPct}%`, height: 0 }}
            />
          )}

          <div className="relative flex h-[120px] items-end justify-between gap-2 px-1" onMouseLeave={() => setHoverIdx(null)}>
            {data.map((d, idx) => {
              const fpH = (d.first_pass_objects / maxY) * 100
              const rwH = (d.rework_objects / maxY) * 100
              return (
                <div
                  key={d.date}
                  onMouseEnter={() => setHoverIdx(idx)}
                  className="flex h-full flex-1 flex-col items-center justify-end"
                >
                  {d.is_off_day ? (
                    <span className="mb-1 text-xs text-quaternary">Nghỉ</span>
                  ) : (
                    <div className="flex w-7 flex-col justify-end overflow-hidden rounded-t-[4px]" style={{ height: '100%' }}>
                      <div className="w-full bg-utility-brand-300" style={{ height: `${rwH}%` }} />
                      <div className="w-full bg-brand-solid" style={{ height: `${fpH}%`, minHeight: d.first_pass_objects > 0 ? 2 : 0 }} />
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {hoverIdx !== null && data[hoverIdx] && (
            <div className="pointer-events-none absolute -top-2 right-0 z-10 rounded-lg bg-primary px-3 py-2 text-xs shadow-lg ring-1 ring-secondary_alt">
              <p className="font-semibold text-primary">{data[hoverIdx].label}</p>
              <p className="text-tertiary">Lần đầu: {formatNumber(data[hoverIdx].first_pass_objects)}</p>
              <p className="text-tertiary">Rework: {formatNumber(data[hoverIdx].rework_objects)}</p>
              <p className="font-medium text-brand-secondary">Tổng KPI: {formatNumber(data[hoverIdx].total_objects)}</p>
            </div>
          )}
        </div>
      </div>

      <div className="mt-2 flex gap-2 pl-10 text-center text-xs text-tertiary">
        {data.map((d, idx) => (
          <span key={d.date} className={`flex-1 ${idx === data.length - 1 ? 'font-semibold text-primary' : ''}`}>
            {d.label}
          </span>
        ))}
      </div>
    </div>
  )
}
