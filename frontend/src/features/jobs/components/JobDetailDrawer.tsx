import { AlertCircle, AlertTriangle, LinkExternal01 } from '@untitledui/icons'
import { useState } from 'react'
import { Table } from '@/components/application/table/table'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { TextArea } from '@/components/base/textarea/textarea'
import { getErrorMessage } from '../../../shared/api/errors'
import StateView from '../../../shared/components/StateView'
import EmptyRow from '../../../shared/components/ui/EmptyRow'
import FormDialog from '../../../shared/components/ui/FormDialog'
import Slideover from '../../../shared/components/ui/Slideover'
import UserName from '../../../shared/components/UserName'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import MemberSelect from '../../projects/components/MemberSelect'
import { useProject } from '../../projects/projectContext'
import { assignJob, getJob, resolveEscalation, setJobDeadline, setJobLock } from '../api'
import { ACTION_LABELS, JOB_STATUS_LABELS } from '../constants'
import type { JobDetail, JobStatus } from '../types'
import AssignModal from './AssignModal'
import DeadlineModal from './DeadlineModal'
import JobStatusBadge from './JobStatusBadge'

interface Props {
  jobId: number | null
  onClose: () => void
  /** Gọi sau mỗi thao tác thay đổi job, để trang cha tải lại danh sách. */
  onChanged?: () => void
}

function describeEvent(event: JobDetail['timeline'][number]) {
  const after = event.after ?? {}
  if (event.action === 'job.status' || event.action.startsWith('qc1.') || event.action.startsWith('qc2.')) {
    const status = after.status as JobStatus | undefined
    return status ? `→ ${JOB_STATUS_LABELS[status] ?? status}` : ''
  }
  if (event.action === 'job.deadline') {
    const d = after.deadline as string | null
    return `→ ${d ? formatDateTime(d) : 'không có deadline'}`
  }
  return ''
}

function timelineDotColor(action: string): string {
  if (action === 'qc2.reject') return 'bg-fg-error-primary'
  if (action === 'qc2.pass') return 'bg-fg-success-primary'
  return 'bg-brand-solid'
}

/** Chi tiết Job: thông tin, dòng thời gian, lỗi đã ghi, lịch sử deadline, thao tác theo quyền. */
export default function JobDetailDrawer({ jobId, onClose, onChanged }: Props) {
  const { projectId, project, can } = useProject()
  const [version, setVersion] = useState(0)
  const { data: job, error, isLoading, retry } = useRequest(`job:${jobId}:${version}`, () =>
    jobId ? getJob(projectId, jobId) : Promise.resolve(null),
  )
  const { run, pending } = useAction()
  const [modal, setModal] = useState<'assign' | 'deadline' | 'escalation' | null>(null)

  const canManage = can('manage_jobs')
  const handleClose = () => {
    setModal(null)
    onClose()
  }
  const refresh = () => {
    setVersion((v) => v + 1)
    onChanged?.()
  }
  async function act(action: () => Promise<unknown>, success: string) {
    if (await run(action, success)) {
      setModal(null)
      refresh()
    }
  }

  const deadlineHistory = job?.timeline.filter((e) => e.action === 'job.deadline') ?? []
  const escalationPolicy = job?.escalation_policy ?? project.escalation_policy ?? 'block'

  return (
    <Slideover
      isOpen={jobId !== null}
      onClose={handleClose}
      title={job ? job.name : 'Chi tiết Job'}
      extra={
        job && (
          <JobStatusBadge
            status={job.status}
            escalated={job.is_escalated}
            locked={job.is_locked}
            overdue={job.is_overdue}
            sourceMissing={job.source_missing}
          />
        )
      }
      footer={
        job && canManage ? (
          <div className="flex flex-wrap items-center justify-end gap-2">
            {job.is_escalated && (
              <Button size="sm" color="secondary-destructive" onPress={() => setModal('escalation')}>
                Xử lý escalation
              </Button>
            )}
            <Button
              size="sm"
              color="secondary"
              isLoading={pending}
              onPress={() => act(() => setJobLock(projectId, job.id, !job.is_locked), job.is_locked ? 'Đã mở khoá' : 'Đã khoá job')}
            >
              {job.is_locked ? 'Mở khoá' : 'Khoá job'}
            </Button>
            <Button
              size="sm"
              color="secondary"
              isDisabled={job.is_locked || job.status === 'delivered'}
              onPress={() => setModal('assign')}
            >
              Giao lại
            </Button>
            <Button
              size="sm"
              color="primary"
              isDisabled={job.is_locked || job.status === 'delivered'}
              onPress={() => setModal('deadline')}
            >
              Đặt deadline
            </Button>
          </div>
        ) : undefined
      }
    >
      {isLoading && <StateView kind="loading" />}
      {error != null && (
        <StateView kind="error" description={getErrorMessage(error)} action={{ label: 'Thử lại', onClick: retry }} />
      )}
      {job && (
        <div className="flex flex-col gap-6">
          {job.source_missing && (
            <div className="flex items-start gap-2.5 rounded-xl bg-warning-primary px-4 py-3 text-sm text-warning-primary ring-1 ring-utility-yellow-200 ring-inset">
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-fg-warning-primary" aria-hidden="true" />
              <span>Không còn tìm thấy job nguồn trên CVAT ở lần đồng bộ gần nhất. Trạng thái trên VanoHub vẫn được giữ nguyên.</span>
            </div>
          )}

          {job.is_escalated && (
            escalationPolicy === 'warn_only' ? (
              <div className="flex items-start gap-2.5 rounded-xl bg-warning-primary px-4 py-3 text-sm text-warning-primary ring-1 ring-utility-yellow-200 ring-inset">
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-fg-warning-primary" aria-hidden="true" />
                <span>
                  {`Job vượt số vòng rework tối đa (${job.rework_round}/${job.max_rework_rounds}) — chế độ cảnh báo.`}
                </span>
              </div>
            ) : (
              <div className="flex items-start gap-2.5 rounded-xl bg-error-primary px-4 py-3 text-sm text-error-primary ring-1 ring-utility-red-200 ring-inset">
                <AlertCircle className="mt-0.5 size-4 shrink-0 text-fg-error-primary" aria-hidden="true" />
                <span>
                  {`Job vượt số vòng rework tối đa (${job.rework_round}/${job.max_rework_rounds}).`}
                </span>
              </div>
            )
          )}

          <dl className="grid grid-cols-1 gap-4 rounded-xl border border-secondary bg-secondary_subtle p-4 sm:grid-cols-2">
            <div>
              <dt className="text-xs font-medium text-tertiary">Project</dt>
              <dd className="mt-0.5 text-sm font-medium text-primary">{job.dataset_name}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-tertiary">Task</dt>
              <dd className="mt-0.5 text-sm font-medium text-primary">{job.batch_name ?? '—'}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-tertiary">Annotator</dt>
              <dd className="mt-0.5 text-sm text-primary">
                <UserName user={job.annotator} empty="Chưa giao" />
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-tertiary">Người QC1</dt>
              <dd className="mt-0.5 text-sm text-primary">
                <UserName user={job.qc1_reviewer} empty="Chưa giao" />
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-tertiary">Deadline</dt>
              <dd className="mt-0.5 text-sm text-primary tabular-nums">{formatDateTime(job.deadline)}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-tertiary">Round rework</dt>
              <dd className="mt-0.5 text-sm text-primary tabular-nums">
                {job.rework_round} / {job.max_rework_rounds}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-tertiary">Số object</dt>
              <dd className="mt-0.5 text-sm text-primary tabular-nums">{job.object_count}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-tertiary">Số frame</dt>
              <dd className="mt-0.5 text-sm text-primary tabular-nums">{job.frame_count}</dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-xs font-medium text-tertiary">CVAT</dt>
              <dd className="mt-1">
                {job.cvat_job_id ? (
                  <div className="flex flex-wrap items-center gap-2 text-sm text-primary">
                    <span>Job #{job.cvat_job_id}</span>
                    {job.cvat_stage && (
                      <Badge type="color" size="sm" color="gray">
                        {job.cvat_stage} / {job.cvat_state}
                      </Badge>
                    )}
                    {job.source_missing && (
                      <Badge type="pill-color" size="sm" color="warning">
                        Thiếu nguồn CVAT
                      </Badge>
                    )}
                    {job.cvat_url && (
                      <Button
                        size="xs"
                        color="secondary"
                        iconLeading={LinkExternal01}
                        href={job.cvat_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Mở trong CVAT
                      </Button>
                    )}
                  </div>
                ) : (
                  <span className="text-sm text-tertiary">Chưa liên kết CVAT</span>
                )}
              </dd>
            </div>
          </dl>

          <section>
            <h3 className="mb-3 text-sm font-semibold text-primary">Dòng thời gian</h3>
            {job.timeline.length === 0 ? (
              <div className="rounded-xl border border-secondary bg-primary">
                <EmptyRow text="Chưa có sự kiện" />
              </div>
            ) : (
              <ol className="flex flex-col">
                {job.timeline.map((e, i) => {
                  const summary = describeEvent(e)
                  return (
                    <li key={e.id} className="relative flex gap-3 pb-4 last:pb-0">
                      {i < job.timeline.length - 1 && (
                        <span className="absolute top-3.5 bottom-0 left-[5px] w-px bg-border-secondary" aria-hidden="true" />
                      )}
                      <span className={`mt-1.5 size-3 shrink-0 rounded-full ${timelineDotColor(e.action)}`} aria-hidden="true" />
                      <div className="min-w-0 text-sm">
                        <p className="text-primary">
                          <span className="font-semibold">{ACTION_LABELS[e.action] ?? e.action}</span>
                          {summary ? ` ${summary}` : ''}
                        </p>
                        <p className="mt-0.5 text-xs text-tertiary">
                          {formatDateTime(e.created_at)} · {e.actor?.full_name ?? 'Hệ thống'}
                          {e.note ? ` · ${e.note}` : ''}
                        </p>
                      </div>
                    </li>
                  )
                })}
              </ol>
            )}
          </section>

          <section>
            <h3 className="mb-3 text-sm font-semibold text-primary">Lỗi đã ghi</h3>
            <div className="overflow-hidden rounded-xl bg-primary ring-1 ring-secondary">
              <Table aria-label="Lỗi đã ghi" size="sm">
                <Table.Header>
                  <Table.Head id="stage" label="Stage" isRowHeader />
                  <Table.Head id="round" label="Round" />
                  <Table.Head id="category" label="Loại lỗi" />
                  <Table.Head id="location" label="Vị trí / Cuboid" />
                  <Table.Head id="description" label="Mô tả" />
                </Table.Header>
                <Table.Body items={job.errors} renderEmptyState={() => <EmptyRow text="Chưa có lỗi" />}>
                  {(err) => {
                    const hasStructured =
                      err.frame_number != null || err.cvat_object_id != null || Boolean(err.is_missing_object)
                    return (
                      <Table.Row id={err.id} className={err.is_voided ? 'opacity-60' : undefined}>
                        <Table.Cell>
                          <Badge type="color" size="sm" color="gray">
                            {err.stage.toUpperCase()}
                          </Badge>
                        </Table.Cell>
                        <Table.Cell className="tabular-nums">{err.rework_round}</Table.Cell>
                        <Table.Cell>
                          <div className="flex flex-col gap-1">
                            <span className={err.is_voided ? 'text-tertiary line-through' : 'font-medium text-primary'}>
                              {err.category}
                            </span>
                            <div className="flex flex-wrap gap-1">
                              {err.verdict === 'edge' && (
                                <Badge type="pill-color" size="sm" color="warning">
                                  Cận biên
                                </Badge>
                              )}
                              {err.verdict === 'fail' && (
                                <Badge type="pill-color" size="sm" color="error">
                                  Lỗi
                                </Badge>
                              )}
                              {err.is_voided && (
                                <Badge type="pill-color" size="sm" color="gray">
                                  Đã huỷ lỗi
                                </Badge>
                              )}
                            </div>
                          </div>
                        </Table.Cell>
                        <Table.Cell>
                          <div className="flex flex-col gap-1">
                            {hasStructured && (
                              <div className="flex flex-wrap gap-1">
                                {err.frame_number != null && (
                                  <Badge type="pill-color" size="sm" color="gray">
                                    Frame #{err.frame_number}
                                  </Badge>
                                )}
                                {err.cvat_object_id != null && (
                                  <Badge type="pill-color" size="sm" color="blue">
                                    Object #{err.cvat_object_id}
                                  </Badge>
                                )}
                                {err.is_missing_object && (
                                  <Badge type="pill-color" size="sm" color="orange">
                                    Thiếu đối tượng
                                  </Badge>
                                )}
                              </div>
                            )}
                            {err.location ? (
                              <span className={err.is_voided ? 'text-xs text-tertiary line-through' : 'text-xs text-secondary'}>
                                {err.location}
                              </span>
                            ) : !hasStructured ? (
                              <span className="text-xs text-tertiary">—</span>
                            ) : null}
                          </div>
                        </Table.Cell>
                        <Table.Cell>
                          <span className={err.is_voided ? 'text-tertiary line-through' : undefined}>
                            {err.description || '—'}
                          </span>
                        </Table.Cell>
                      </Table.Row>
                    )
                  }}
                </Table.Body>
              </Table>
            </div>
          </section>

          <section>
            <h3 className="mb-2 text-sm font-semibold text-primary">Lịch sử deadline</h3>
            {deadlineHistory.length === 0 ? (
              <p className="text-sm text-tertiary">Chưa đổi deadline.</p>
            ) : (
              <ul className="list-disc space-y-1 pl-5 text-sm text-primary">
                {deadlineHistory.map((e) => (
                  <li key={e.id}>
                    {formatDateTime(e.before?.deadline as string | null)} → {formatDateTime(e.after?.deadline as string | null)}
                    <span className="text-tertiary">
                      {' '}
                      · {e.actor?.full_name ?? 'Hệ thống'} · {formatDateTime(e.created_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}

      {job && (
        <>
          <AssignModal
            open={modal === 'assign'}
            projectId={projectId}
            initial={{ annotator: job.annotator?.id ?? null, qc1_reviewer: job.qc1_reviewer?.id ?? null }}
            confirmLoading={pending}
            onCancel={() => setModal(null)}
            onSubmit={(values) => act(() => assignJob(projectId, job.id, values), 'Đã giao lại job')}
          />
          <DeadlineModal
            open={modal === 'deadline'}
            currentDeadline={job.deadline}
            confirmLoading={pending}
            onCancel={() => setModal(null)}
            onSubmit={(deadline, note) => act(() => setJobDeadline(projectId, job.id, deadline, note), 'Đã cập nhật deadline')}
          />
          {modal === 'escalation' && (
            <EscalationDialog
              key={job.id}
              isOpen
              projectId={projectId}
              pending={pending}
              onClose={() => setModal(null)}
              onSubmit={(annotator, note) =>
                act(() => resolveEscalation(projectId, job.id, annotator ?? undefined, note), 'Đã xử lý escalation')
              }
            />
          )}
        </>
      )}
    </Slideover>
  )
}

function EscalationDialog({
  isOpen,
  projectId,
  pending,
  onClose,
  onSubmit,
}: {
  isOpen: boolean
  projectId: number
  pending: boolean
  onClose: () => void
  onSubmit: (annotator: number | null, note: string) => void
}) {
  const [annotator, setAnnotator] = useState<number | null>(null)
  const [note, setNote] = useState('')

  return (
    <FormDialog
      isOpen={isOpen}
      onClose={onClose}
      title="Xử lý job Escalated"
      description="Gỡ cờ Escalated và đặt lại số vòng rework về 0 (lịch sử lỗi vẫn được giữ). Có thể giao cho annotator khác."
      submitLabel="Xác nhận"
      pending={pending}
      onSubmit={() => onSubmit(annotator, note)}
    >
      <div className="flex flex-col gap-4">
        <MemberSelect
          projectId={projectId}
          role="annotator"
          label="Giao cho annotator khác (tuỳ chọn)"
          value={annotator}
          onChange={setAnnotator}
        />
        <TextArea label="Ghi chú" rows={2} value={note} onChange={setNote} />
      </div>
    </FormDialog>
  )
}
