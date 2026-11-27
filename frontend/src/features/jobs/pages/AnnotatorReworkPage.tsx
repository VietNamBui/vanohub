import { ArrowRight } from '@untitledui/icons'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { Badge, BadgeWithDot } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { useShell } from '../../../layouts/ShellContext'
import { getErrorMessage } from '../../../shared/api/errors'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatShortDateTime } from '../../../shared/utils/format'
import { useProject } from '../../projects/projectContext'
import { SEVERITY_LABELS } from '../../quality/constants'
import type { Severity } from '../../quality/types'
import { getAnnotatorJob, listAnnotatorJobs } from '../api'
import AnnotatorBreadcrumb from '../components/AnnotatorBreadcrumb'
import DisputeErrorModal from '../components/DisputeErrorModal'
import JobStatusBadge from '../components/JobStatusBadge'
import { formatDeadlineCountdown } from '../constants'
import type { Job, JobDetail } from '../types'

const REWORK_PAGE_SIZE = 100
const MAX_REWORK_PAGES = 10
const DETAIL_BATCH_SIZE = 6

async function fetchAllReworkJobs(projectId: number): Promise<JobDetail[]> {
  const allJobs: Job[] = []
  for (let page = 1; page <= MAX_REWORK_PAGES; page += 1) {
    const listed = await listAnnotatorJobs(projectId, { tab: 'rework', page, page_size: REWORK_PAGE_SIZE })
    allJobs.push(...listed.results)
    if (!listed.next || listed.results.length === 0) break
  }
  const details: JobDetail[] = []
  for (let i = 0; i < allJobs.length; i += DETAIL_BATCH_SIZE) {
    const chunk = allJobs.slice(i, i + DETAIL_BATCH_SIZE)
    const batchDetails = await Promise.all(chunk.map((j) => getAnnotatorJob(projectId, j.id)))
    details.push(...batchDetails)
  }
  return details
}

const SEVERITY_BADGE: Record<string, 'gray' | 'warning' | 'error'> = {
  minor: 'gray',
  major: 'warning',
  critical: 'error',
}

/** Trang "Cần sửa" (/projects/:projectId/annotator/rework) — danh sách lỗi theo object-frame cần xử lý rework. */
export default function AnnotatorReworkPage() {
  const { projectId } = useProject()
  const navigate = useNavigate()
  const { teamLeaderName } = useShell()
  const [version, setVersion] = useState(0)
  const [disputeTarget, setDisputeTarget] = useState<{ job: JobDetail; errorId: number } | null>(null)

  const req = useRequest(`annotator-rework-full:${projectId}:${version}`, () => fetchAllReworkJobs(projectId))

  const reworkJobs = req.data ?? []
  const totalErrors = reworkJobs.reduce((sum, j) => sum + j.errors.length, 0)

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
            ? `${reworkJobs[0].name} · ${totalErrors} object-frame còn phải sửa`
            : `${reworkJobs.length} job cần sửa · ${totalErrors} object-frame còn phải sửa`}
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
            return (
              <SectionCard
                key={job.id}
                title={job.name}
                description={`${job.batch_name}${job.deadline ? ` · Hạn sửa ${formatShortDateTime(job.deadline)}` : ''}${countdown ? ` · ${countdown.text}` : ''}`}
                actions={
                  <Button
                    size="sm"
                    color="secondary"
                    iconTrailing={ArrowRight}
                    onPress={() => navigate(`/projects/${projectId}/annotator/jobs/${job.id}`)}
                  >
                    Mở job
                  </Button>
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
                </div>

                {job.errors.length === 0 ? (
                  <div className="px-5 py-6 text-sm text-tertiary">
                    Chưa có chi tiết lỗi cho job này.
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[760px] text-left text-sm">
                      <thead className="bg-secondary text-xs font-semibold text-quaternary">
                        <tr>
                          <th className="px-5 py-3">Lỗi</th>
                          <th className="px-4 py-3">Vị trí</th>
                          <th className="px-4 py-3">Mức</th>
                          <th className="px-4 py-3">Ghi chú QC1</th>
                          <th className="px-5 py-3 text-right">Phản hồi</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-secondary">
                        {job.errors.map((err) => (
                          <tr key={err.id} className="transition hover:bg-primary_hover">
                            <td className="px-5 py-3.5 font-medium text-primary">{err.category}</td>
                            <td className="px-4 py-3.5 text-secondary">{err.location || 'Chưa ghi vị trí'}</td>
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

                <footer className="border-t border-secondary px-5 py-3.5 text-xs text-tertiary">
                  Khi vượt số vòng sửa tối đa ({job.max_rework_rounds}), job sẽ bị tạm khoá và chuyển Project Manager xem xét.
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
          teamLeaderName={teamLeaderName}
          errors={disputeTarget.job.errors}
          initialErrorId={disputeTarget.errorId}
          onClose={() => setDisputeTarget(null)}
          onSubmitted={() => setVersion((v) => v + 1)}
        />
      )}
    </div>
  )
}
