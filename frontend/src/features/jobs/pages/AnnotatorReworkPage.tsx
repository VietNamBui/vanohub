import { AlertTriangle, ArrowRight, LinkExternal01 } from '@untitledui/icons'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { Badge, BadgeWithDot } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { getErrorMessage } from '../../../shared/api/errors'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatShortDateTime } from '../../../shared/utils/format'
import { useProject } from '../../projects/projectContext'
import { SEVERITY_LABELS } from '../../quality/constants'
import type { Severity } from '../../quality/types'
import { listAnnotatorJobsWithErrors } from '../api'
import AnnotatorBreadcrumb from '../components/AnnotatorBreadcrumb'
import DisputeErrorModal from '../components/DisputeErrorModal'
import JobStatusBadge from '../components/JobStatusBadge'
import ReviewErrorChips from '../components/ReviewErrorChips'
import { formatDeadlineCountdown } from '../constants'
import { isJobEscalationWarnOnly, splitActiveErrors } from '../jobHelpers'
import type { JobWithErrors } from '../types'

const REWORK_PAGE_SIZE = 100
const MAX_REWORK_PAGES = 10

async function fetchAllReworkJobs(projectId: number): Promise<JobWithErrors[]> {
  const allJobs: JobWithErrors[] = []
  for (let page = 1; page <= MAX_REWORK_PAGES; page += 1) {
    const listed = await listAnnotatorJobsWithErrors(projectId, {
      tab: 'rework',
      page,
      page_size: REWORK_PAGE_SIZE,
    })
    allJobs.push(...listed.results)
    if (!listed.next || listed.results.length === 0) break
  }
  return allJobs
}

const SEVERITY_BADGE: Record<string, 'gray' | 'warning' | 'error'> = {
  minor: 'gray',
  major: 'warning',
  critical: 'error',
}

/** Trang "Cần sửa" (/projects/:projectId/annotator/rework) — danh sách lỗi theo object-frame cần xử lý rework. */
export default function AnnotatorReworkPage() {
  const { projectId, project } = useProject()
  const navigate = useNavigate()
  const [version, setVersion] = useState(0)
  const [disputeTarget, setDisputeTarget] = useState<{ job: JobWithErrors; errorId: number } | null>(null)

  const req = useRequest(`annotator-rework-full:${projectId}:${version}`, () => fetchAllReworkJobs(projectId))

  const reworkJobs = req.data ?? []
  const totalErrors = reworkJobs.reduce((sum, j) => sum + splitActiveErrors(j, j.errors).active.length, 0)

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 md:p-6">
      <AnnotatorBreadcrumb
        projectId={projectId}
        items={[
          { label: 'Job của tôi', to: `/projects/${projectId}/annotator/jobs` },
          { label: 'Cần sửa' },
        ]}
      />

      <header>
        <h1 className="text-display-xs font-semibold text-primary">Cần sửa</h1>
        <p className="mt-1 text-sm text-tertiary">
          {reworkJobs.length === 1
            ? `${reworkJobs[0].name} · ${totalErrors} lỗi còn phải sửa`
            : `${reworkJobs.length} job cần sửa · ${totalErrors} lỗi còn phải sửa`}
        </p>
      </header>

      {req.error != null ? (
        <SectionCard>
          <PageState kind="error" description={getErrorMessage(req.error)} onRetry={req.retry} />
        </SectionCard>
      ) : req.isLoading ? (
        <SectionCard>
          <PageState kind="loading" />
        </SectionCard>
      ) : reworkJobs.length === 0 ? (
        <SectionCard>
          <PageState
            kind="empty"
            title="Không có job nào cần sửa"
            description="Khi QC1 hoặc QC2 trả lại lỗi rework, danh sách lỗi theo object-frame sẽ xuất hiện tại đây."
          />
        </SectionCard>
      ) : (
        <div className="flex flex-col gap-5">
          {reworkJobs.map((job) => {
            const countdown = formatDeadlineCountdown(job.hours_remaining)
            const { active, history } = splitActiveErrors(job, job.errors)
            const isWarnOnly = isJobEscalationWarnOnly(job, project.escalation_policy)

            return (
              <SectionCard
                key={job.id}
                title={job.name}
                description={`${job.batch_name}${job.deadline ? ` · Hạn sửa ${formatShortDateTime(job.deadline)}` : ''}${countdown ? ` · ${countdown.text}` : ''}`}
                actions={
                  <div className="flex flex-wrap items-center gap-2">
                    {job.cvat_url && (
                      <Button
                        size="sm"
                        color="secondary"
                        iconLeading={LinkExternal01}
                        href={job.cvat_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Mở trên CVAT
                      </Button>
                    )}
                    <Button
                      size="sm"
                      color="secondary"
                      iconTrailing={ArrowRight}
                      onPress={() => navigate(`/projects/${projectId}/annotator/jobs/${job.id}`)}
                    >
                      Mở job
                    </Button>
                  </div>
                }
                bodyClassName="p-0"
              >
                <div className="border-b border-secondary px-5 py-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <JobStatusBadge
                      status={job.status}
                      escalated={job.is_escalated}
                      overdue={job.is_overdue}
                      locked={job.is_locked}
                      sourceMissing={job.source_missing}
                    />
                    <Badge size="sm" type="pill-color" color="brand">
                      {job.rework_scope === 'full' ? 'Sửa toàn job' : 'Sửa một phần'}
                    </Badge>
                    <Badge size="sm" type="pill-color" color="warning">
                      Vòng {job.rework_round}/{job.max_rework_rounds}
                    </Badge>
                  </div>
                  <p className="mt-2.5 text-sm text-tertiary">
                    Sửa các object-frame QC1 ghi bên dưới. Khi QC1 yêu cầu sửa toàn job, rà soát mọi frame.
                  </p>
                  {job.is_escalated && isWarnOnly && (
                    <div className="mt-3 flex items-center gap-2 rounded-xl bg-warning-primary px-3.5 py-2.5 text-xs text-warning-primary ring-1 ring-utility-yellow-200 ring-inset">
                      <AlertTriangle className="size-4 shrink-0 text-fg-warning-primary" />
                      Job đã vượt số vòng sửa tối đa — chế độ cảnh báo, bạn vẫn có thể tiếp tục sửa ({job.rework_round}/{job.max_rework_rounds}).
                    </div>
                  )}
                  {job.is_escalated && !isWarnOnly && (
                    <div className="mt-3 flex items-center gap-2 rounded-xl bg-error-primary px-3.5 py-2.5 text-xs text-error-primary ring-1 ring-utility-red-200 ring-inset">
                      <AlertTriangle className="size-4 shrink-0 text-fg-error-primary" />
                      Job đã vượt số vòng sửa tối đa ({job.rework_round}/{job.max_rework_rounds}) và đang chờ Project Manager xem xét.
                    </div>
                  )}
                </div>

                {active.length === 0 ? (
                  <div className="px-5 py-6 text-sm text-tertiary">
                    {history.length > 0
                      ? 'Không còn lỗi đang mở cần sửa cho vòng hiện tại.'
                      : 'Chưa có chi tiết lỗi cho job này.'}
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[760px] text-left text-sm">
                      <thead className="bg-secondary text-xs font-semibold text-quaternary">
                        <tr>
                          <th className="px-5 py-3">Lỗi</th>
                          <th className="px-4 py-3">Vị trí / Cuboid</th>
                          <th className="px-4 py-3">Mức</th>
                          <th className="px-4 py-3">Ghi chú QC1</th>
                          <th className="px-5 py-3 text-right">Phản hồi</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-secondary">
                        {active.map((err) => (
                          <tr key={err.id} className="transition hover:bg-primary_hover">
                            <td className="px-5 py-3.5 font-medium text-primary">
                              <div className="flex flex-wrap items-center gap-1.5">
                                <span>{err.category}</span>
                                <Badge size="sm" type="color" color="gray">
                                  {err.stage.toUpperCase()}
                                </Badge>
                              </div>
                            </td>
                            <td className="px-4 py-3.5 text-secondary">
                              <ReviewErrorChips err={err} />
                              {err.location ? (
                                <div className="mt-1 text-xs text-secondary">{err.location}</div>
                              ) : err.frame_number == null && err.cvat_object_id == null && !err.is_missing_object ? (
                                <span className="text-xs text-tertiary">Chưa ghi vị trí</span>
                              ) : null}
                            </td>
                            <td className="px-4 py-3.5">
                              <BadgeWithDot size="sm" type="pill-color" color={SEVERITY_BADGE[err.severity] ?? 'warning'}>
                                {SEVERITY_LABELS[err.severity as Severity] ?? err.severity}
                              </BadgeWithDot>
                            </td>
                            <td className="px-4 py-3.5 text-tertiary">{err.description || '—'}</td>
                            <td className="px-5 py-3.5 text-right">
                              <Button
                                size="sm"
                                color="secondary"
                                onPress={() => setDisputeTarget({ job, errorId: err.id })}
                              >
                                Phản hồi lỗi
                              </Button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {history.length > 0 && (
                  <div className="border-t border-secondary">
                    <div className="bg-secondary px-5 py-2.5 text-xs font-semibold text-quaternary">
                      Lịch sử lỗi các vòng trước & lỗi đã huỷ ({history.length})
                    </div>
                    <ul className="divide-y divide-secondary">
                      {history.map((err) => (
                        <li key={err.id} className="flex items-start justify-between gap-3 px-5 py-3 opacity-70">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span
                                className={`text-sm font-medium ${
                                  err.is_voided ? 'text-tertiary line-through' : 'text-secondary'
                                }`}
                              >
                                {err.category}
                              </span>
                              <Badge size="sm" type="pill-color" color="gray">
                                {err.stage.toUpperCase()} · vòng {err.rework_round}
                              </Badge>
                            </div>
                            <ReviewErrorChips err={err} />
                            {err.location && (
                              <div className={`mt-1 text-xs text-tertiary ${err.is_voided ? 'line-through' : ''}`}>
                                {err.location}
                              </div>
                            )}
                            {err.description && (
                              <div className={`mt-0.5 text-xs text-tertiary ${err.is_voided ? 'line-through' : ''}`}>
                                {err.description}
                              </div>
                            )}
                          </div>
                          <BadgeWithDot size="sm" type="pill-color" color={SEVERITY_BADGE[err.severity] ?? 'warning'}>
                            {SEVERITY_LABELS[err.severity as Severity] ?? err.severity}
                          </BadgeWithDot>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <footer className="border-t border-secondary px-5 py-3.5 text-xs text-tertiary">
                  {isWarnOnly
                    ? `Khi vượt số vòng sửa tối đa (${job.max_rework_rounds}), hệ thống sẽ cảnh báo và bạn vẫn có thể tiếp tục sửa.`
                    : `Khi vượt số vòng sửa tối đa (${job.max_rework_rounds}), job sẽ bị tạm khoá và chuyển Project Manager xem xét.`}
                </footer>
              </SectionCard>
            )
          })}
        </div>
      )}

      {disputeTarget && (
        <DisputeErrorModal
          isOpen
          projectId={projectId}
          jobId={disputeTarget.job.id}
          jobName={disputeTarget.job.name}
          errors={splitActiveErrors(disputeTarget.job, disputeTarget.job.errors).active}
          initialErrorId={disputeTarget.errorId}
          onClose={() => setDisputeTarget(null)}
          onSubmitted={() => setVersion((v) => v + 1)}
        />
      )}
    </div>
  )
}
