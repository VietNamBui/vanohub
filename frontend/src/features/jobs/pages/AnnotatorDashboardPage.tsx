import { AlertTriangle, ArrowRight, CheckCircle, Clock } from '@untitledui/icons'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { Badge, BadgeWithDot } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { ProgressBarBase } from '@/components/base/progress-indicators/progress-indicators'
import { useShell } from '../../../layouts/ShellContext'
import { getErrorMessage } from '../../../shared/api/errors'
import PageState from '../../../shared/components/ui/PageState'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime, formatNumber, formatShortDateTime, VN_TIME_ZONE } from '../../../shared/utils/format'
import { useAuth } from '../../auth/useAuth'
import { useProject } from '../../projects/projectContext'
import { SEVERITY_LABELS } from '../../quality/constants'
import type { Severity } from '../../quality/types'
import { getAnnotatorDashboard } from '../api'
import AnnotatorBreadcrumb from '../components/AnnotatorBreadcrumb'
import AnnotatorJobDrawer from '../components/AnnotatorJobDrawer'
import { formatDeadlineCountdown, JOB_STATUS_LABELS } from '../constants'
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

/** Tổng quan cá nhân của Annotator — khớp thiết kế Annota (KPI cards, Công việc tiếp theo, Việc cần sửa, Kết quả theo ngày, Yêu cầu của tôi). */
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
    <div className="mx-auto flex max-w-[1160px] flex-col gap-6 px-6 py-7">
      <AnnotatorBreadcrumb
        projectId={projectId}
        items={[
          { label: 'Dashboard', to: `/projects/${projectId}/annotator/dashboard` },
          { label: 'Tổng quan cá nhân' },
        ]}
      />

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-[30px] leading-tight font-bold text-[#101828]">
            {getGreeting()}, {firstName}
          </h1>
          <p className="mt-1.5 text-sm text-[#475467]">
            {[data?.meta?.team_name, project.name, syncText].filter(Boolean).join(' · ')}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button
            color="secondary"
            size="md"
            onPress={() => navigate(`/projects/${projectId}/annotator/analytics`)}
          >
            Phân tích cá nhân (P2)
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
        <div className="rounded-xl border border-[#EAECF0] bg-white p-6">
          <PageState kind="error" description={getErrorMessage(error)} onRetry={retry} />
        </div>
      ) : isLoading || !data ? (
        <div className="rounded-xl border border-[#EAECF0] bg-white p-6">
          <PageState kind="loading" />
        </div>
      ) : (
        <>
          {/* 4 KPI Cards */}
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard
              title="Sản lượng / chỉ tiêu"
              value={
                data.kpi_summary.achievement_pct != null
                  ? formatViPercent(data.kpi_summary.achievement_pct)
                  : formatNumber(data.kpi_summary.actual_objects)
              }
              code="SL06 · KPI02"
              subtitle={
                data.kpi_summary.target_objects
                  ? `${formatNumber(data.kpi_summary.actual_objects)} / ${formatNumber(data.kpi_summary.target_objects)} · thiếu ${formatNumber(data.kpi_summary.shortfall)} (KPI03)`
                  : `${formatNumber(data.kpi_summary.actual_objects)} object-frame hoàn tất`
              }
              tone="brand"
              icon={
                <svg className="size-5" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7">
                  <circle cx="10" cy="10" r="7" />
                  <circle cx="10" cy="10" r="3" />
                </svg>
              }
              onClick={() => navigate(`/projects/${projectId}/annotator/analytics`)}
            />

            <KpiCard
              title="Job cần sửa"
              value={String(data.kpi_summary.rework_jobs_count)}
              code="TD02"
              subtitle={
                data.kpi_summary.rework_jobs_count > 0
                  ? `job · vòng sửa ${data.kpi_summary.max_rework_round_active} / ${data.kpi_summary.max_rework_rounds}`
                  : `0 job cần sửa (tối đa ${data.kpi_summary.max_rework_rounds} vòng)`
              }
              tone={data.kpi_summary.rework_jobs_count > 0 ? 'warning' : 'brand'}
              icon={<AlertTriangle className="size-5" />}
              onClick={() => navigate(`/projects/${projectId}/annotator/rework`)}
            />

            <KpiCard
              title="Job sắp / quá hạn"
              value={String(data.kpi_summary.due_soon_count + data.kpi_summary.overdue_count)}
              code="DH02 · DH04"
              subtitle={`${data.kpi_summary.due_soon_count} sắp hạn · ${data.kpi_summary.overdue_count} quá hạn`}
              tone={data.kpi_summary.due_soon_count + data.kpi_summary.overdue_count > 0 ? 'warning' : 'brand'}
              icon={<Clock className="size-5" />}
              onClick={() => navigate(`/projects/${projectId}/annotator/jobs?due_soon=1`)}
            />

            <KpiCard
              title="FPY cá nhân"
              value={formatViPercent(data.kpi_summary.fpy_pct)}
              code="CL01"
              subtitle={`${data.kpi_summary.fpy_passed} / ${data.kpi_summary.fpy_total} job đạt`}
              tone="brand"
              icon={<CheckCircle className="size-5" />}
            />
          </div>

          {/* Công việc tiếp theo */}
          <section className="overflow-hidden rounded-xl border border-[#EAECF0] bg-white">
            <div className="px-6 py-5">
              <h2 className="text-lg font-bold text-[#101828]">Công việc tiếp theo</h2>
              <p className="mt-1 text-sm text-[#475467]">
                Đang giữ {data.meta.active_jobs_count} / {data.meta.wip_limit} job (GV02) ·{' '}
                {formatNumber(data.meta.active_object_frames)} object-frame (TD10) · thứ tự DB06: quá hạn → sắp hạn → còn lại
              </p>
            </div>

            {data.next_jobs.length === 0 ? (
              <div className="border-t border-[#EAECF0] p-6">
                <PageState
                  kind="empty"
                  title="Không có job đang mở"
                  description='Nhấn "Job của tôi" → "Nhận job mới" để nhận thêm công việc từ hàng chờ.'
                />
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[780px] text-left">
                  <thead className="border-y border-[#EAECF0] bg-[#F9FAFB] text-xs font-medium text-[#475467]">
                    <tr>
                      <th className="px-6 py-3">Job</th>
                      <th className="px-4 py-3">Trạng thái</th>
                      <th className="px-4 py-3">Tiến độ (TD03)</th>
                      <th className="px-4 py-3">Hạn (DH02 · DH04)</th>
                      <th className="px-4 py-3">Ưu tiên</th>
                      <th className="px-6 py-3 text-right">Thao tác</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#EAECF0]">
                    {data.next_jobs.map((job, idx) => {
                      const target = job.target_object_count || job.object_count
                      const pct = job.progress_percent ?? 0
                      const countdown = formatDeadlineCountdown(job.hours_remaining)
                      const isRework = job.status === 'rework'
                      return (
                        <tr
                          key={job.id}
                          onClick={() => setDrawerJobId(job.id)}
                          className="cursor-pointer transition hover:bg-[#F9FAFB]"
                        >
                          <td className="px-6 py-4">
                            <div className="text-sm font-bold text-[#101828]">{job.name}</div>
                            <div className="mt-0.5 text-xs text-[#667085]">
                              {job.batch_name} · {formatNumber(target)} obj-frame
                            </div>
                          </td>
                          <td className="px-4 py-4">
                            <BadgeWithDot
                              size="sm"
                              type="pill-color"
                              color={isRework ? 'warning' : job.status === 'annotating' ? 'blue' : 'gray'}
                            >
                              {isRework ? 'Cần sửa' : job.status === 'annotating' ? 'Đang làm' : JOB_STATUS_LABELS[job.status]}
                            </BadgeWithDot>
                            <div className="mt-1 text-xs text-[#667085]">
                              {job.rework_round > 0 ? `Vòng sửa ${job.rework_round} / ${job.max_rework_rounds}` : 'Lần làm đầu'}
                            </div>
                          </td>
                          <td className="w-56 px-4 py-4">
                            <div className="mb-1.5 text-xs text-[#344054] tabular-nums">
                              {pct}% · {formatNumber(job.object_count)} / {formatNumber(target)}
                            </div>
                            <ProgressBarBase value={pct} className="bg-[#EAECF0]" progressClassName="bg-[#7F56D9]" />
                          </td>
                          <td className="px-4 py-4">
                            <div className="text-xs font-medium text-[#344054]">
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
                          <td className="px-4 py-4">
                            <Badge size="sm" type="pill-color" color={isRework ? 'warning' : 'gray'}>
                              {isRework ? 'Rework' : 'Bình thường'}
                            </Badge>
                          </td>
                          <td
                            className="px-6 py-4 text-right"
                            onClick={(e) => e.stopPropagation()}
                          >
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
          </section>

          {/* Hàng giữa: Việc cần sửa + Kết quả theo ngày */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
            {/* Việc cần sửa */}
            <section className="flex flex-col justify-between rounded-xl border border-[#EAECF0] bg-white p-6 lg:col-span-7">
              <div>
                <div className="flex flex-wrap items-center gap-2.5">
                  <h2 className="text-lg font-bold text-[#101828]">Việc cần sửa</h2>
                  {data.rework_focus && (
                    <Badge size="sm" type="pill-color" color="warning">
                      {data.rework_focus.error_count} lỗi
                    </Badge>
                  )}
                </div>
                {data.rework_focus ? (
                  <>
                    <p className="mt-1 text-sm text-[#475467]">
                      {data.rework_focus.job_name}
                      {data.rework_focus.deadline ? ` · hạn ${formatShortDateTime(data.rework_focus.deadline)}` : ''} · lỗi theo object-frame (CL04 · RW01 · RW04)
                    </p>

                    <div className="mt-4 grid grid-cols-3 gap-3">
                      <MiniStat label="Lỗi cần sửa" code="CL04" value={String(data.rework_focus.error_count)} />
                      <MiniStat
                        label="Vòng rework"
                        code="RW01"
                        value={`${data.rework_focus.rework_round} / ${data.rework_focus.max_rework_rounds}`}
                      />
                      <MiniStat
                        label="Chờ sửa"
                        code="RW04"
                        value={`${data.rework_focus.pending_object_frames} obj-frame`}
                      />
                    </div>

                    <ul className="mt-5 divide-y divide-[#F2F4F7]">
                      {data.rework_focus.errors.slice(0, 3).map((err) => (
                        <li
                          key={err.id}
                          onClick={() => navigate(`/projects/${projectId}/annotator/jobs/${data.rework_focus!.job_id}`)}
                          className="flex cursor-pointer items-start justify-between gap-3 py-3 hover:bg-[#F9FAFB]"
                        >
                          <div className="flex items-start gap-3">
                            <div className="w-28 shrink-0 pt-0.5">
                              <BadgeWithDot size="sm" type="pill-color" color={SEVERITY_BADGE[err.severity] ?? 'warning'}>
                                {SEVERITY_LABELS[err.severity as Severity] ?? err.severity}
                              </BadgeWithDot>
                            </div>
                            <div className="min-w-0">
                              <p className="text-sm font-medium text-[#101828]">{err.category}</p>
                              {err.description && <p className="mt-0.5 text-xs text-[#667085]">{err.description}</p>}
                            </div>
                          </div>
                          <span className="shrink-0 text-right text-xs text-[#344054]">
                            {err.location || `vòng ${err.rework_round}`}
                          </span>
                        </li>
                      ))}
                      {data.rework_focus.errors.length === 0 && (
                        <li className="py-6 text-center text-sm text-[#667085]">Chưa có ghi chú lỗi chi tiết.</li>
                      )}
                    </ul>
                  </>
                ) : (
                  <div className="py-8">
                    <PageState
                      kind="empty"
                      title="Không có việc cần sửa"
                      description="Tất cả job của bạn đều đang trong luồng làm bình thường hoặc đã đạt QC1."
                    />
                  </div>
                )}
              </div>

              <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-[#F2F4F7] pt-4">
                <span className="text-xs text-[#667085]">Sửa theo note từng lỗi (L8) · vượt quá số vòng tối đa sẽ tạm khoá và chuyển PM xem xét</span>
                <Link
                  to={`/projects/${projectId}/annotator/rework`}
                  className="inline-flex items-center gap-1.5 text-sm font-semibold text-[#6941C6] hover:text-[#53389E]"
                >
                  Xem tất cả lỗi
                  <ArrowRight className="size-4" />
                </Link>
              </div>
            </section>

            {/* Kết quả theo ngày */}
            <section className="flex flex-col justify-between rounded-xl border border-[#EAECF0] bg-white p-6 lg:col-span-5">
              <div>
                <h2 className="text-lg font-bold text-[#101828]">Kết quả theo ngày</h2>
                <p className="mt-1 text-sm text-[#475467]">
                  Lần đầu / rework so với chỉ tiêu (SL01 · SL03 · KPI01)
                </p>

                <div className="mt-4 rounded-lg border border-[#EAECF0] bg-[#F9FAFB] px-4 py-3">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-[#475467]">Nộp đúng hạn</span>
                    <span className="text-[10px] text-[#98A2B3]">DH06</span>
                  </div>
                  <div className="mt-1 flex items-baseline gap-2.5">
                    <span className="text-xl font-bold text-[#101828]">
                      {formatViPercent(data.kpi_summary.on_time_pct)}
                    </span>
                    <span className="text-xs text-[#667085]">
                      {data.kpi_summary.on_time_count} / {data.kpi_summary.submitted_total} job nộp đúng hạn
                    </span>
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap items-center gap-4 text-xs text-[#475467]">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="size-3 rounded-[3px] bg-[#7F56D9]" />
                    Lần đầu
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="size-3 rounded-[3px] bg-[#D6BBFB]" />
                    Rework
                  </span>
                  {data.kpi_target != null && data.kpi_target > 0 && (
                    <span className="inline-flex items-center gap-1.5">
                      <span className="h-0.5 w-4 border-t-2 border-dashed border-[#D92D20]" />
                      Chỉ tiêu
                    </span>
                  )}
                </div>

                <DailyStackedChart data={data.daily_results} target={data.kpi_target ?? undefined} />
              </div>

              <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-[#F2F4F7] pt-4">
                <span className="text-xs text-[#667085]">Phần rework vẫn tính KPI (CS03)</span>
                <Link
                  to={`/projects/${projectId}/annotator/analytics`}
                  className="inline-flex items-center gap-1.5 text-sm font-semibold text-[#6941C6] hover:text-[#53389E]"
                >
                  Phân tích (P2)
                  <ArrowRight className="size-4" />
                </Link>
              </div>
            </section>
          </div>

          {/* Yêu cầu của tôi */}
          <section className="overflow-hidden rounded-xl border border-[#EAECF0] bg-white">
            <div className="flex flex-wrap items-start justify-between gap-3 px-6 py-5">
              <div>
                <div className="flex items-center gap-2.5">
                  <h2 className="text-lg font-bold text-[#101828]">Yêu cầu của tôi</h2>
                  {data.recent_requests.pending_count > 0 && (
                    <Badge size="sm" type="pill-color" color="warning">
                      {data.recent_requests.pending_count} đang chờ
                    </Badge>
                  )}
                </div>
                <p className="mt-1 text-sm text-[#475467]">
                  Phản hồi lỗi &amp; dữ liệu bị chặn: người đang xử lý và kết luận (TD13)
                </p>
              </div>
              <Button
                color="secondary"
                size="sm"
                onPress={() => navigate(`/projects/${projectId}/annotator/requests`)}
              >
                Xem tất cả
              </Button>
            </div>

            {data.recent_requests.items.length === 0 ? (
              <div className="border-t border-[#EAECF0] p-6">
                <PageState
                  kind="empty"
                  title="Chưa có yêu cầu nào"
                  description="Phản hồi lỗi QC1 hoặc báo cáo dữ liệu bị chặn sẽ hiển thị tại đây."
                />
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[700px] text-left">
                  <thead className="border-y border-[#EAECF0] bg-[#F9FAFB] text-xs font-medium text-[#475467]">
                    <tr>
                      <th className="px-6 py-3">Loại</th>
                      <th className="px-4 py-3">Đối tượng / nội dung</th>
                      <th className="px-4 py-3">Người xử lý</th>
                      <th className="px-6 py-3">Kết luận</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#EAECF0]">
                    {data.recent_requests.items.map((req) => (
                      <tr
                        key={req.id}
                        onClick={() => navigate(`/projects/${projectId}/annotator/requests`)}
                        className="cursor-pointer hover:bg-[#F9FAFB]"
                      >
                        <td className="px-6 py-3.5">
                          <Badge
                            size="sm"
                            type="pill-color"
                            color={req.request_type === 'error_dispute' ? 'blue' : 'gray'}
                          >
                            {req.request_type_label}
                          </Badge>
                        </td>
                        <td className="px-4 py-3.5">
                          <div className="text-sm font-bold text-[#101828]">{req.job_name}</div>
                          <div className="mt-0.5 text-xs text-[#475467]">{req.title}</div>
                        </td>
                        <td className="px-4 py-3.5 text-sm text-[#475467]">
                          {req.handler ? `${req.handler.full_name} (${req.handler_role})` : req.handler_role}
                        </td>
                        <td className="px-6 py-3.5">
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
          </section>
        </>
      )}

      <AnnotatorJobDrawer projectId={projectId} jobId={drawerJobId} onClose={() => setDrawerJobId(null)} />
    </div>
  )
}

function KpiCard({
  title,
  value,
  code,
  subtitle,
  tone,
  icon,
  onClick,
}: {
  title: string
  value: string
  code: string
  subtitle: string
  tone: 'brand' | 'warning'
  icon: React.ReactNode
  onClick?: () => void
}) {
  const isWarn = tone === 'warning'
  return (
    <div
      onClick={onClick}
      className={`flex flex-col justify-between rounded-xl border bg-white p-5 transition ${
        isWarn ? 'border-[#FEDF89]' : 'border-[#EAECF0]'
      } ${onClick ? 'cursor-pointer hover:shadow-xs' : ''}`}
    >
      <div className="flex items-center gap-3">
        <span
          className={`flex size-10 shrink-0 items-center justify-center rounded-full ${
            isWarn ? 'bg-[#FFFAEB]' : 'bg-[#F9F5FF]'
          }`}
        >
          <span
            className={`flex size-7 items-center justify-center rounded-full ${
              isWarn ? 'bg-[#FEDF89] text-[#B54708]' : 'bg-[#E9D7FE] text-[#6941C6]'
            }`}
          >
            {icon}
          </span>
        </span>
        <span className="text-sm text-[#475467]">{title}</span>
      </div>

      <div className="mt-4 flex items-baseline justify-between gap-2">
        <span className="text-[30px] leading-none font-bold text-[#101828] tabular-nums">{value}</span>
        <span className="text-[11px] text-[#98A2B3]">{code}</span>
      </div>

      <p className="mt-2.5 truncate text-sm text-[#475467]" title={subtitle}>
        {subtitle}
      </p>
    </div>
  )
}

function MiniStat({ label, code, value }: { label: string; code: string; value: string }) {
  return (
    <div className="rounded-lg border border-[#EAECF0] bg-[#F9FAFB] px-3 py-2.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-[#475467]">{label}</span>
        <span className="text-[10px] text-[#98A2B3]">{code}</span>
      </div>
      <div className="mt-1 text-lg font-bold text-[#101828] tabular-nums">{value}</div>
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
        <div className="flex h-[120px] flex-col justify-between text-right text-[11px] text-[#667085] tabular-nums">
          <span>{formatNumber(maxY)}</span>
          <span>{formatNumber(Math.round(maxY / 2))}</span>
          <span>0</span>
        </div>

        <div className="relative flex-1">
          <div className="pointer-events-none absolute inset-x-0 top-0 flex h-[120px] flex-col justify-between">
            <div className="h-px bg-[#F2F4F7]" />
            <div className="h-px bg-[#F2F4F7]" />
            <div className="h-px bg-[#EAECF0]" />
          </div>

          {targetVal > 0 && (
            <div
              className="pointer-events-none absolute inset-x-0 border-t border-dashed border-[#D92D20]"
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
                    <span className="mb-1 text-[11px] text-[#98A2B3]">Nghỉ</span>
                  ) : (
                    <div className="flex w-7 flex-col justify-end overflow-hidden rounded-t-[4px]" style={{ height: '100%' }}>
                      <div className="w-full bg-[#D6BBFB]" style={{ height: `${rwH}%` }} />
                      <div className="w-full bg-[#7F56D9]" style={{ height: `${fpH}%`, minHeight: d.first_pass_objects > 0 ? 2 : 0 }} />
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {hoverIdx !== null && data[hoverIdx] && (
            <div className="pointer-events-none absolute -top-2 right-0 z-10 rounded-lg border border-[#EAECF0] bg-white px-3 py-2 text-xs shadow-lg">
              <p className="font-semibold text-[#101828]">{data[hoverIdx].label}</p>
              <p className="text-[#475467]">Lần đầu: {formatNumber(data[hoverIdx].first_pass_objects)}</p>
              <p className="text-[#475467]">Rework: {formatNumber(data[hoverIdx].rework_objects)}</p>
              <p className="font-medium text-[#6941C6]">Tổng KPI: {formatNumber(data[hoverIdx].total_objects)}</p>
            </div>
          )}
        </div>
      </div>

      <div className="mt-2 flex gap-2 pl-10 text-center text-[11px] text-[#475467]">
        {data.map((d, idx) => (
          <span key={d.date} className={`flex-1 ${idx === data.length - 1 ? 'font-semibold text-[#101828]' : ''}`}>
            {d.label}
          </span>
        ))}
      </div>
    </div>
  )
}
