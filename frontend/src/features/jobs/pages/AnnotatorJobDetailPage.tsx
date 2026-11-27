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
    <div className="mx-auto flex max-w-[1160px] flex-col gap-6 px-6 py-7">
      <AnnotatorBreadcrumb
        projectId={projectId}
        items={[
          { label: 'Job của tôi', to: `/projects/${projectId}/annotator/jobs` },
          { label: job?.name ?? `Job #${jobId}` },
        ]}
      />

      {jobReq.error != null ? (
        <div className="rounded-xl border border-[#EAECF0] bg-white p-6">
          <PageState kind="error" description={getErrorMessage(jobReq.error)} onRetry={jobReq.retry} />
        </div>
      ) : jobReq.isLoading || !job ? (
        <div className="rounded-xl border border-[#EAECF0] bg-white p-6">
          <PageState kind="loading" />
        </div>
      ) : (
        <>
          <header className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h1 className="text-[30px] leading-tight font-bold text-[#101828]">{job.name}</h1>
              <p className="mt-1 text-base text-[#475467]">
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

          {/* Status + Progress Card */}
          <section className="rounded-xl border border-[#EAECF0] bg-white p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-2.5">
                <BadgeWithDot
                  size="sm"
                  type="pill-color"
                  color={
                    job.status === 'rework'
                      ? 'warning'
                      : job.status === 'annotating'
                        ? 'blue'
                        : job.status === 'approved' || job.status === 'delivered'
                          ? 'success'
                          : 'gray'
                  }
                >
                  {job.status === 'rework' ? 'Cần sửa' : job.status === 'annotating' ? 'Đang làm' : JOB_STATUS_LABELS[job.status]}
                </BadgeWithDot>
                <Badge size="sm" type="pill-color" color="gray">
                  Vòng {job.rework_round}/{job.max_rework_rounds} · RW01
                </Badge>
                {job.rework_round > 0 && (
                  <Badge size="sm" type="pill-color" color="brand">
                    {job.rework_scope === 'full' ? 'Sửa toàn job · L8' : 'Sửa một phần · L8'}
                  </Badge>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2.5">
                <span className="text-xs text-[#344054]">
                  {job.deadline
                    ? `${job.status === 'rework' ? 'Hạn sửa' : 'Hạn nộp'} ${formatShortDateTime(job.deadline)} · DH01/02`
                    : 'Chưa đặt hạn · DH01/02'}
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
                <span className="font-bold text-[#101828]">Tiến độ gán nhãn · TD03</span>
                <span className="font-semibold text-[#344054] tabular-nums">
                  {pct}% · {formatNumber(job.object_count)}/{formatNumber(target)} object-frame
                </span>
              </div>
              <ProgressBarBase value={pct} className="bg-[#EAECF0]" progressClassName="bg-[#7F56D9]" />
            </div>

            {job.is_locked && (
              <div className="mt-4 flex items-center gap-2.5 rounded-lg border border-[#FEDF89] bg-[#FFFAEB] px-4 py-3 text-sm text-[#B54708]">
                <AlertTriangle className="size-4 shrink-0" />
                Job đang bị khoá — không thể thay đổi trạng thái hoặc nộp lên QC1.
              </div>
            )}
            {job.is_escalated && (
              <div className="mt-4 flex items-center gap-2.5 rounded-lg border border-[#FECDCA] bg-[#FEF3F2] px-4 py-3 text-sm text-[#B42318]">
                <AlertTriangle className="size-4 shrink-0" />
                Job đã vượt số vòng rework cho phép ({job.rework_round}/{job.max_rework_rounds}) và đang chờ PM xem xét.
              </div>
            )}
          </section>

          {/* 2-Column Section: Lỗi cần sửa + Hướng dẫn đang áp dụng */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
            <section className="overflow-hidden rounded-xl border border-[#EAECF0] bg-white lg:col-span-7">
              <div className="px-6 py-5">
                <h2 className="text-lg font-bold text-[#101828]">Lỗi cần sửa</h2>
                <p className="mt-1 text-sm text-[#475467]">
                  Sửa theo ghi chú QC1 · {job.errors.length} object-frame còn lại · RW04
                </p>
              </div>

              {job.errors.length === 0 ? (
                <div className="border-t border-[#EAECF0] p-6">
                  <PageState kind="empty" title="Chưa có lỗi nào được ghi nhận" />
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left">
                    <thead className="border-y border-[#EAECF0] bg-[#F9FAFB] text-xs font-medium text-[#475467]">
                      <tr>
                        <th className="px-6 py-3">Lỗi · CL04</th>
                        <th className="px-4 py-3">Mức</th>
                        <th className="px-6 py-3 text-right">Phản hồi</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#EAECF0]">
                      {job.errors.map((err) => (
                        <tr key={err.id}>
                          <td className="px-6 py-4">
                            <div className="text-sm font-bold text-[#101828]">{err.category}</div>
                            {err.location && <div className="mt-0.5 text-xs text-[#344054]">{err.location}</div>}
                            {err.description && <div className="mt-0.5 text-xs text-[#475467]">{err.description}</div>}
                          </td>
                          <td className="px-4 py-4">
                            <BadgeWithDot size="sm" type="pill-color" color={SEVERITY_BADGE[err.severity] ?? 'warning'}>
                              {SEVERITY_LABELS[err.severity as Severity] ?? err.severity}
                            </BadgeWithDot>
                          </td>
                          <td className="px-6 py-4 text-right">
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
            </section>

            <section className="flex flex-col justify-between rounded-xl border border-[#EAECF0] bg-white p-6 lg:col-span-5">
              <div>
                <h2 className="text-lg font-bold text-[#101828]">Hướng dẫn đang áp dụng</h2>
                <p className="mt-1 text-sm text-[#475467]">
                  {latestGuideline ? `Phiên bản v${latestGuideline.version} · DL07` : 'Chưa xuất bản phiên bản · DL07'}
                </p>

                {!latestGuideline ? (
                  <p className="mt-5 text-sm text-[#667085]">
                    Chưa có hướng dẫn gán nhãn nào được xuất bản cho dự án này.
                  </p>
                ) : checklist.length === 0 ? (
                  <p className="mt-5 text-sm text-[#667085]">
                    Mở trang Hướng dẫn để xem chi tiết phiên bản v{latestGuideline.version}.
                  </p>
                ) : (
                  <ul className="mt-5 flex flex-col gap-3.5">
                    {checklist.map((item) => (
                      <li key={item} className="flex items-start gap-2.5 text-sm text-[#344054]">
                        <CheckCircle className="mt-0.5 size-4 shrink-0 text-[#7F56D9]" />
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="mt-6 pt-4">
                <Button
                  color="secondary"
                  size="sm"
                  onPress={() => navigate(`/projects/${projectId}/guidelines`)}
                >
                  Xem hướng dẫn
                </Button>
              </div>
            </section>
          </div>

          {/* Lịch sử xử lý L13 */}
          <section className="rounded-xl border border-[#EAECF0] bg-white p-6">
            <h2 className="text-base font-bold text-[#101828]">Lịch sử xử lý (L13)</h2>
            {job.timeline.length === 0 ? (
              <p className="mt-2 text-sm text-[#667085]">Chưa có hoạt động nào.</p>
            ) : (
              <ol className="mt-4 flex flex-col">
                {job.timeline.map((ev, i) => {
                  const nextStatus = ev.after?.status as JobStatus | undefined
                  return (
                    <li key={ev.id} className="relative flex gap-3 pb-4 last:pb-0">
                      {i < job.timeline.length - 1 && (
                        <span className="absolute top-3.5 bottom-0 left-[6px] w-px bg-[#EAECF0]" />
                      )}
                      <span className="mt-1 size-3.5 shrink-0 rounded-full bg-[#7F56D9]" />
                      <div className="text-sm">
                        <p className="font-medium text-[#101828]">
                          {ACTION_LABELS[ev.action] ?? ev.action}
                          {nextStatus ? ` → ${JOB_STATUS_LABELS[nextStatus] ?? nextStatus}` : ''}
                        </p>
                        <p className="text-xs text-[#667085]">
                          {ev.actor?.full_name ?? 'Hệ thống'} · {formatDateTime(ev.created_at)}
                        </p>
                        {ev.note && <p className="mt-0.5 text-xs text-[#475467]">{ev.note}</p>}
                      </div>
                    </li>
                  )
                })}
              </ol>
            )}
          </section>

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
