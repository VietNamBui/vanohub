import { AlertTriangle, Check, CheckCircle, LinkExternal01 } from '@untitledui/icons'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { Badge, BadgeWithDot } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { Input } from '@/components/base/input/input'
import { ProgressBarBase } from '@/components/base/progress-indicators/progress-indicators'
import { TextArea } from '@/components/base/textarea/textarea'
import { useShell } from '../../../layouts/ShellContext'
import { getErrorMessage } from '../../../shared/api/errors'
import FormDialog from '../../../shared/components/ui/FormDialog'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime, formatNumber, formatShortDateTime } from '../../../shared/utils/format'
import { listGuidelines } from '../../projects/api'
import { useProject } from '../../projects/projectContext'
import { SEVERITY_LABELS } from '../../quality/constants'
import type { Severity } from '../../quality/types'
import { getAnnotatorJob, startAnnotatorJob, submitAnnotatorJob } from '../api'
import AnnotatorBreadcrumb from '../components/AnnotatorBreadcrumb'
import DisputeErrorModal from '../components/DisputeErrorModal'
import JobStatusBadge from '../components/JobStatusBadge'
import ReportDataIssueModal from '../components/ReportDataIssueModal'
import { ACTION_LABELS, formatDeadlineCountdown, JOB_STATUS_LABELS } from '../constants'
import type { JobStatus } from '../types'

const SEVERITY_BADGE: Record<string, 'gray' | 'warning' | 'error'> = {
  minor: 'gray',
  major: 'warning',
  critical: 'error',
}

function extractChecklist(markdown?: string): string[] {
  if (!markdown) return []
  const headings = markdown
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.startsWith('## ') || line.startsWith('- '))
    .map((line) => line.replace(/^##\s+|^-\s+/, '').trim())
    .filter(Boolean)
  return headings.slice(0, 5)
}

/** Trang chi tiết Job chuyên biệt cho Annotator (/projects/:projectId/annotator/jobs/:jobId). */
export default function AnnotatorJobDetailPage() {
  const { projectId, project } = useProject()
  const { jobId: jobIdParam } = useParams()
  const jobId = Number(jobIdParam)
  const navigate = useNavigate()
  const { teamLeaderName } = useShell()
  const { run, pending } = useAction()

  const [version, setVersion] = useState(0)
  const [disputeErrorId, setDisputeErrorId] = useState<number | null>(null)
  const [disputeOpen, setDisputeOpen] = useState(false)
  const [dataIssueOpen, setDataIssueOpen] = useState(false)
  const [submitModalOpen, setSubmitModalOpen] = useState(false)
  const [submitObjects, setSubmitObjects] = useState('')
  const [submitObjectsError, setSubmitObjectsError] = useState<string | null>(null)
  const [submitNote, setSubmitNote] = useState('')

  const jobReq = useRequest(`annotator-job-detail:${projectId}:${jobId}:${version}`, () =>
    getAnnotatorJob(projectId, jobId),
  )
  const guideReq = useRequest(`annotator-job-guidelines:${projectId}`, () => listGuidelines(projectId))

  const job = jobReq.data
  const latestGuideline = guideReq.data?.[0]
  const checklist = extractChecklist(latestGuideline?.content)
  const reload = () => setVersion((v) => v + 1)

  async function handleStart() {
    if (!job) return
    const ok = await run(
      () => startAnnotatorJob(projectId, job.id),
      job.status === 'rework' ? `Đã bắt đầu sửa ${job.name}` : `Đã bắt đầu làm ${job.name}`,
    )
    if (ok) reload()
  }

  async function handleConfirmSubmit() {
    if (!job) return
    const trimmed = submitObjects.trim()
    let parsed: number | undefined
    if (trimmed !== '') {
      if (!/^\d+$/.test(trimmed)) {
        setSubmitObjectsError('Vui lòng nhập số nguyên không âm (ví dụ: 120).')
        return
      }
      parsed = Number(trimmed)
    }
    setSubmitObjectsError(null)
    const ok = await run(
      () => submitAnnotatorJob(projectId, job.id, { note: submitNote.trim(), ...(parsed !== undefined ? { object_count: parsed } : {}) }),
      `Đã nộp ${job.name} lên QC1`,
    )
    if (ok) {
      setSubmitModalOpen(false)
      reload()
    }
  }

  const countdown = formatDeadlineCountdown(job?.hours_remaining)
  const target = job ? job.target_object_count || job.object_count : 0
  const pct = job?.progress_percent ?? 0
  const isBlocked = Boolean(job?.is_locked || job?.is_escalated)
  const canStart = job && !isBlocked && (job.status === 'pending_annotation' || job.status === 'rework')
  const canSubmit = job && !isBlocked && job.status === 'annotating'

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 md:p-6">
      <AnnotatorBreadcrumb
        projectId={projectId}
        items={[
          { label: 'Job của tôi', to: `/projects/${projectId}/annotator/jobs` },
          { label: job?.name ?? `Job #${jobId}` },
        ]}
      />

      {jobReq.error != null ? (
        <SectionCard>
          <PageState kind="error" description={getErrorMessage(jobReq.error)} onRetry={jobReq.retry} />
        </SectionCard>
      ) : jobReq.isLoading || !job ? (
        <SectionCard>
          <PageState kind="loading" />
        </SectionCard>
      ) : (
        <>
          <header className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h1 className="text-display-xs font-semibold text-primary">{job.name}</h1>
              <p className="mt-1 text-sm text-tertiary">
                {project.name} · {job.batch_name}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button
                color="secondary"
                size="md"
                iconLeading={AlertTriangle}
                onPress={() => setDataIssueOpen(true)}
              >
                Báo vấn đề dữ liệu
              </Button>
              {job.cvat_url ? (
                <Button
                  color="secondary"
                  size="md"
                  iconLeading={LinkExternal01}
                  href={job.cvat_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Mở trên CVAT
                </Button>
              ) : (
                <Button color="secondary" size="md" iconLeading={LinkExternal01} isDisabled>
                  Mở trên CVAT
                </Button>
              )}
              {canStart && (
                <Button color="primary" size="md" isLoading={pending} onPress={handleStart}>
                  {job.status === 'rework' ? 'Bắt đầu sửa' : 'Bắt đầu làm'}
                </Button>
              )}
              {canSubmit && (
                <Button
                  color="primary"
                  size="md"
                  iconLeading={Check}
                  onPress={() => {
                    setSubmitObjects(job.object_count > 0 ? String(job.object_count) : '')
                    setSubmitObjectsError(null)
                    setSubmitNote('')
                    setSubmitModalOpen(true)
                  }}
                >
                  Nộp lên QC1
                </Button>
              )}
            </div>
          </header>

          <SectionCard>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <JobStatusBadge
                  status={job.status}
                  escalated={job.is_escalated}
                  overdue={job.is_overdue}
                  locked={job.is_locked}
                />
                <Badge size="sm" type="pill-color" color="gray">
                  Vòng {job.rework_round}/{job.max_rework_rounds}
                </Badge>
                {job.rework_round > 0 && (
                  <Badge size="sm" type="pill-color" color="brand">
                    {job.rework_scope === 'full' ? 'Sửa toàn job' : 'Sửa một phần'}
                  </Badge>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2.5">
                <span className="text-xs font-medium text-secondary">
                  {job.deadline
                    ? `${job.status === 'rework' ? 'Hạn sửa' : 'Hạn nộp'} ${formatShortDateTime(job.deadline)}`
                    : 'Chưa đặt hạn'}
                </span>
                {countdown && (
                  <Badge size="sm" type="pill-color" color={countdown.tone}>
                    {countdown.text}
                  </Badge>
                )}
              </div>
            </div>

            <div className="mt-5">
              <div className="mb-2 flex items-center justify-between text-sm">
                <span className="font-semibold text-primary">Tiến độ gán nhãn</span>
                <span className="font-semibold text-secondary tabular-nums">
                  {pct}% · {formatNumber(job.object_count)}/{formatNumber(target)} object-frame
                </span>
              </div>
              <ProgressBarBase value={pct} />
            </div>

            {job.is_locked && (
              <div className="mt-4 flex items-center gap-2.5 rounded-xl bg-warning-primary px-4 py-3 text-sm text-warning-primary ring-1 ring-utility-yellow-200 ring-inset">
                <AlertTriangle className="size-4 shrink-0 text-fg-warning-primary" />
                Job đang bị khoá — không thể thay đổi trạng thái hoặc nộp lên QC1.
              </div>
            )}
            {job.is_escalated && (
              <div className="mt-4 flex items-center gap-2.5 rounded-xl bg-error-primary px-4 py-3 text-sm text-error-primary ring-1 ring-utility-red-200 ring-inset">
                <AlertTriangle className="size-4 shrink-0 text-fg-error-primary" />
                Job đã vượt số vòng rework cho phép ({job.rework_round}/{job.max_rework_rounds}) và đang chờ Project Manager xem xét.
              </div>
            )}
          </SectionCard>

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
            <SectionCard
              className="lg:col-span-7"
              title="Lỗi cần sửa"
              description={`Sửa theo ghi chú QC1 · ${job.errors.length} object-frame còn lại`}
              bodyClassName="p-0"
            >
              {job.errors.length === 0 ? (
                <PageState kind="empty" title="Chưa có lỗi nào được ghi nhận" />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-secondary text-xs font-semibold text-quaternary">
                      <tr>
                        <th className="px-5 py-3">Lỗi</th>
                        <th className="px-4 py-3">Mức</th>
                        <th className="px-5 py-3 text-right">Phản hồi</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-secondary">
                      {job.errors.map((err) => (
                        <tr key={err.id}>
                          <td className="px-5 py-3.5">
                            <div className="font-semibold text-primary">{err.category}</div>
                            {err.location && <div className="mt-0.5 text-xs text-secondary">{err.location}</div>}
                            {err.description && <div className="mt-0.5 text-xs text-tertiary">{err.description}</div>}
                          </td>
                          <td className="px-4 py-3.5">
                            <BadgeWithDot size="sm" type="pill-color" color={SEVERITY_BADGE[err.severity] ?? 'warning'}>
                              {SEVERITY_LABELS[err.severity as Severity] ?? err.severity}
                            </BadgeWithDot>
                          </td>
                          <td className="px-5 py-3.5 text-right">
                            <Button
                              size="sm"
                              color="secondary"
                              onPress={() => {
                                setDisputeErrorId(err.id)
                                setDisputeOpen(true)
                              }}
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
            </SectionCard>

            <SectionCard
              className="lg:col-span-5"
              bodyClassName="flex flex-col justify-between"
              title="Hướng dẫn đang áp dụng"
              description={latestGuideline ? `Phiên bản v${latestGuideline.version}` : 'Chưa xuất bản phiên bản'}
            >
              <div>
                {!latestGuideline ? (
                  <p className="text-sm text-tertiary">
                    Chưa có hướng dẫn gán nhãn nào được xuất bản cho organization này.
                  </p>
                ) : checklist.length === 0 ? (
                  <p className="text-sm text-tertiary">
                    Mở trang Hướng dẫn để xem chi tiết phiên bản v{latestGuideline.version}.
                  </p>
                ) : (
                  <ul className="flex flex-col gap-3">
                    {checklist.map((item) => (
                      <li key={item} className="flex items-start gap-2.5 text-sm text-secondary">
                        <CheckCircle className="mt-0.5 size-4 shrink-0 text-fg-brand-primary" />
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="mt-5 border-t border-secondary pt-4">
                <Button
                  color="secondary"
                  size="sm"
                  onPress={() => navigate(`/projects/${projectId}/guidelines`)}
                >
                  Xem hướng dẫn
                </Button>
              </div>
            </SectionCard>
          </div>

          <SectionCard title="Lịch sử xử lý">
            {job.timeline.length === 0 ? (
              <p className="text-sm text-tertiary">Chưa có hoạt động nào.</p>
            ) : (
              <ol className="flex flex-col">
                {job.timeline.map((ev, i) => {
                  const nextStatus = ev.after?.status as JobStatus | undefined
                  return (
                    <li key={ev.id} className="relative flex gap-3 pb-4 last:pb-0">
                      {i < job.timeline.length - 1 && (
                        <span className="absolute top-3.5 bottom-0 left-[6px] w-px bg-border-secondary" />
                      )}
                      <span className="mt-1 size-3.5 shrink-0 rounded-full bg-brand-solid" />
                      <div className="text-sm">
                        <p className="font-medium text-primary">
                          {ACTION_LABELS[ev.action] ?? ev.action}
                          {nextStatus ? ` → ${JOB_STATUS_LABELS[nextStatus] ?? nextStatus}` : ''}
                        </p>
                        <p className="text-xs text-tertiary">
                          {ev.actor?.full_name ?? 'Hệ thống'} · {formatDateTime(ev.created_at)}
                        </p>
                        {ev.note && <p className="mt-0.5 text-xs text-secondary">{ev.note}</p>}
                      </div>
                    </li>
                  )
                })}
              </ol>
            )}
          </SectionCard>

          <DisputeErrorModal
            isOpen={disputeOpen}
            projectId={projectId}
            jobId={job.id}
            jobName={job.name}
            teamLeaderName={teamLeaderName}
            errors={job.errors}
            initialErrorId={disputeErrorId}
            onClose={() => setDisputeOpen(false)}
            onSubmitted={reload}
          />

          <ReportDataIssueModal
            isOpen={dataIssueOpen}
            projectId={projectId}
            jobId={job.id}
            jobName={job.name}
            onClose={() => setDataIssueOpen(false)}
            onSubmitted={reload}
          />

          <FormDialog
            isOpen={submitModalOpen}
            onClose={() => setSubmitModalOpen(false)}
            title={`Nộp ${job.name} lên QC1`}
            description="Xác nhận bạn đã kiểm tra cuboid, đối tượng và tracking ID trước khi nộp."
            submitLabel="Xác nhận nộp QC1"
            onSubmit={handleConfirmSubmit}
            pending={pending}
          >
            <div className="flex flex-col gap-4">
              <Input
                label="Số object-frame đã hoàn tất (không bắt buộc)"
                placeholder="Để trống để giữ nguyên số hiện tại"
                value={submitObjects}
                onChange={(v) => {
                  setSubmitObjects(v)
                  if (submitObjectsError) setSubmitObjectsError(null)
                }}
                isInvalid={!!submitObjectsError}
                hint={submitObjectsError ?? undefined}
              />
              <TextArea
                label="Ghi chú cho QC1 (không bắt buộc)"
                placeholder="Ghi chú các điểm đã sửa hoặc lưu ý đặc biệt…"
                rows={3}
                value={submitNote}
                onChange={setSubmitNote}
              />
            </div>
          </FormDialog>
        </>
      )}
    </div>
  )
}
