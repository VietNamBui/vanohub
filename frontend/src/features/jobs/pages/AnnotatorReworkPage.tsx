import { ArrowRight } from '@untitledui/icons'
import dayjs from 'dayjs'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { Badge, BadgeWithDot } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { getErrorMessage } from '../../../shared/api/errors'
import PageState from '../../../shared/components/ui/PageState'
import { useRequest } from '../../../shared/hooks/useRequest'
import { useProject } from '../../projects/projectContext'
import { SEVERITY_LABELS } from '../../quality/constants'
import type { Severity } from '../../quality/types'
import { getAnnotatorJob, listAnnotatorJobs } from '../api'
import AnnotatorBreadcrumb from '../components/AnnotatorBreadcrumb'
import DisputeErrorModal from '../components/DisputeErrorModal'
import { formatDeadlineCountdown } from '../constants'
import type { JobDetail } from '../types'

const SEVERITY_BADGE: Record<string, 'gray' | 'warning' | 'error'> = {
  minor: 'gray',
  major: 'warning',
  critical: 'error',
}

/** Trang "Cần sửa" chuyên biệt (/projects/:projectId/annotator/rework) — RW01, RW04, RW07, L7, L8. */
export default function AnnotatorReworkPage() {
  const { projectId } = useProject()
  const navigate = useNavigate()
  const [version, setVersion] = useState(0)
  const [disputeTarget, setDisputeTarget] = useState<{ job: JobDetail; errorId: number } | null>(null)

  const req = useRequest(`annotator-rework-full:${projectId}:${version}`, async () => {
    const listed = await listAnnotatorJobs(projectId, { tab: 'rework' })
    const details = await Promise.all(listed.results.map((j) => getAnnotatorJob(projectId, j.id)))
    return details
  })

  const reworkJobs = req.data ?? []
  const totalErrors = reworkJobs.reduce((sum, j) => sum + j.errors.length, 0)

  return (
    <div className="mx-auto flex max-w-[1160px] flex-col gap-6 px-6 py-7">
      <AnnotatorBreadcrumb
        projectId={projectId}
        items={[
          { label: 'Job của tôi', to: `/projects/${projectId}/annotator/jobs` },
          { label: 'Cần sửa' },
        ]}
      />

      <header>
        <h1 className="text-[30px] leading-tight font-bold text-[#101828]">Cần sửa</h1>
        <p className="mt-1 text-base text-[#475467]">
          {reworkJobs.length === 1
            ? `${reworkJobs[0].name} · ${totalErrors} object-frame còn phải sửa · RW04`
            : `${reworkJobs.length} job cần sửa · ${totalErrors} object-frame còn phải sửa · RW04`}
        </p>
      </header>

      {req.error != null ? (
        <div className="rounded-xl border border-[#EAECF0] bg-white p-6">
          <PageState kind="error" description={getErrorMessage(req.error)} onRetry={req.retry} />
        </div>
      ) : req.isLoading ? (
        <div className="rounded-xl border border-[#EAECF0] bg-white p-6">
          <PageState kind="loading" />
        </div>
      ) : reworkJobs.length === 0 ? (
        <div className="rounded-xl border border-[#EAECF0] bg-white p-10">
          <PageState
            kind="empty"
            title="Không có job nào cần sửa"
            description="Khi QC1 hoặc QC2 trả lại lỗi rework, danh sách lỗi theo object-frame sẽ xuất hiện tại đây."
          />
        </div>
      ) : (
        <div className="flex flex-col gap-6">
          {reworkJobs.map((job) => {
            const countdown = formatDeadlineCountdown(job.hours_remaining)
            return (
              <section key={job.id} className="overflow-hidden rounded-xl border border-[#EAECF0] bg-white">
                <div className="px-6 py-5">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                      <h2 className="text-lg font-bold text-[#101828]">{job.name}</h2>
                      <p className="mt-1 text-sm text-[#475467]">
                        {job.batch_name}
                        {job.deadline ? ` · Hạn sửa ${dayjs(job.deadline).format('DD/MM HH:mm')}` : ''}
                        {countdown ? ` · ${countdown.text}` : ''}
                      </p>
                    </div>
                    <Button
                      size="sm"
                      color="secondary"
                      iconLeading={ArrowRight}
                      onPress={() => navigate(`/projects/${projectId}/annotator/jobs/${job.id}`)}
                    >
                      Mở job
                    </Button>
                  </div>

                  <div className="mt-4 flex flex-wrap items-center gap-2.5">
                    <Badge size="sm" type="pill-color" color="brand">
                      {job.rework_scope === 'full' ? 'Sửa toàn job · L8' : 'Sửa một phần · L8'}
                    </Badge>
                    <Badge size="sm" type="pill-color" color="warning">
                      Vòng {job.rework_round}/{job.max_rework_rounds} · RW01
                    </Badge>
                  </div>

                  <p className="mt-3 text-sm text-[#475467]">
                    Sửa các object-frame QC1 ghi bên dưới. Khi QC1 yêu cầu sửa toàn job, rà soát mọi frame.
                  </p>
                </div>

                {job.errors.length === 0 ? (
                  <div className="border-t border-[#EAECF0] px-6 py-6 text-sm text-[#667085]">
                    Chưa có chi tiết lỗi cho job này.
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[760px] text-left">
                      <thead className="border-y border-[#EAECF0] bg-[#F9FAFB] text-xs font-medium text-[#475467]">
                        <tr>
                          <th className="px-6 py-3">Lỗi · CL04</th>
                          <th className="px-4 py-3">Vị trí · L7</th>
                          <th className="px-4 py-3">Mức</th>
                          <th className="px-4 py-3">Ghi chú QC1</th>
                          <th className="px-6 py-3 text-right">Phản hồi</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#EAECF0]">
                        {job.errors.map((err) => (
                          <tr key={err.id} className="hover:bg-[#F9FAFB]">
                            <td className="px-6 py-4 text-sm text-[#344054]">{err.category}</td>
                            <td className="px-4 py-4 text-sm text-[#475467]">{err.location || 'Chưa ghi vị trí'}</td>
                            <td className="px-4 py-4">
                              <BadgeWithDot size="sm" type="pill-color" color={SEVERITY_BADGE[err.severity] ?? 'warning'}>
                                {SEVERITY_LABELS[err.severity as Severity] ?? err.severity}
                              </BadgeWithDot>
                            </td>
                            <td className="px-4 py-4 text-sm text-[#475467]">{err.description || '—'}</td>
                            <td className="px-6 py-4 text-right">
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

                <footer className="border-t border-[#EAECF0] px-6 py-3.5 text-xs text-[#475467]">
                  Từ vòng 3, hệ thống cảnh báo và bạn vẫn có thể tiếp tục sửa · RW07
                </footer>
              </section>
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
          errors={disputeTarget.job.errors}
          initialErrorId={disputeTarget.errorId}
          onClose={() => setDisputeTarget(null)}
          onSubmitted={() => setVersion((v) => v + 1)}
        />
      )}
    </div>
  )
}
