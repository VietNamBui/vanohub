import { AlertTriangle, LinkExternal01, Plus, Trash01 } from '@untitledui/icons'
import { useState } from 'react'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { Input } from '@/components/base/input/input'
import { Select } from '@/components/base/select/select'
import { TextArea } from '@/components/base/textarea/textarea'
import { getErrorMessage } from '../../../shared/api/errors'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import JobStatusBadge from '../../jobs/components/JobStatusBadge'
import { ACTION_LABELS, JOB_STATUS_LABELS } from '../../jobs/constants'
import type { JobDetail, JobStatus } from '../../jobs/types'
import { getQc1Job, listErrorCategories, passQc1Job, rejectQc1Job, startQc1Job } from '../api'
import { SEVERITY_LABELS } from '../constants'
import type { Severity } from '../types'

interface Props {
  projectId: number
  jobId: number
  version: number
  onDone: () => void
}

type ErrorRow = { key: number; category: number | null; severity: Severity | null; location: string; description: string }

const SEVERITY_BADGE_COLORS: Record<string, 'gray' | 'warning' | 'error'> = {
  minor: 'gray',
  major: 'warning',
  critical: 'error',
}

/** Khung kiểm tra QC1 cho một job: mở CVAT, nhận bắt đầu, Pass sang QC2 hoặc Reject kèm lỗi QC1. */
export default function Qc1ReviewPanel({ projectId, jobId, version, onDone }: Props) {
  const { data: job, error, isLoading, retry } = useRequest(`qc1-job:${projectId}:${jobId}:${version}`, () =>
    getQc1Job(projectId, jobId),
  )

  if (error != null) return <SectionCard><PageState kind="error" description={getErrorMessage(error)} onRetry={retry} /></SectionCard>
  if (isLoading || !job) return <SectionCard><PageState kind="loading" /></SectionCard>

  const reviewable = job.status === 'pending_qc1' || job.status === 'qc1_reviewing'

  return (
    <SectionCard
      title={job.name}
      description={`${job.dataset_name} / ${job.batch_name}`}
      actions={job.cvat_url ? (
        <Button size="sm" color="secondary" iconTrailing={LinkExternal01} href={job.cvat_url} target="_blank" rel="noreferrer">
          Mở trong CVAT
        </Button>
      ) : (
        <span className="text-sm text-quaternary">Chưa liên kết CVAT</span>
      )}
    >
      <div className="flex flex-col gap-5">
        <JobStatusBadge status={job.status} escalated={job.is_escalated} overdue={job.is_overdue} locked={job.is_locked} />

        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
          <Info label="Annotator" value={job.annotator?.full_name ?? 'Chưa giao'} />
          <Info label="Người QC1" value={job.qc1_reviewer?.full_name ?? 'Chưa nhận (Pool)'} />
          <Info label="Object / frame" value={`${job.object_count} / ${job.frame_count}`} />
          <Info label="Vòng rework" value={`${job.rework_round} / ${job.max_rework_rounds}`} />
          <Info label="Deadline" value={formatDateTime(job.deadline)} />
        </dl>

        {job.is_locked ? (
          <Notice text="Job đang bị khoá — không thể kiểm tra." />
        ) : job.is_escalated ? (
          <Notice text="Job đang ở trạng thái Escalated, chờ PM xử lý." />
        ) : reviewable ? (
          <Qc1ReviewForm key={`${job.id}:${job.status}:${job.updated_at}`} projectId={projectId} job={job} onDone={onDone} />
        ) : (
          <p className="rounded-lg bg-secondary p-3 text-sm text-tertiary">
            Job hiện ở trạng thái <span className="font-medium text-secondary">{JOB_STATUS_LABELS[job.status]}</span> — không còn trong hàng chờ QC1.
          </p>
        )}

        {job.errors.length > 0 && (
          <section className="border-t border-secondary pt-4">
            <h3 className="mb-2 text-sm font-semibold text-primary">
              Lỗi đã ghi nhận <span className="font-normal text-tertiary">({job.errors.length})</span>
            </h3>
            <ul className="flex flex-col gap-2">
              {job.errors.map((e) => (
                <li key={e.id} className="rounded-lg p-3 text-sm ring-1 ring-secondary ring-inset">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-secondary">{e.category}</span>
                    <Badge type="color" size="sm" color={SEVERITY_BADGE_COLORS[e.severity] ?? 'gray'}>
                      {SEVERITY_LABELS[e.severity as Severity] ?? e.severity}
                    </Badge>
                    <span className="text-xs text-quaternary">
                      {e.stage.toUpperCase()} · vòng {e.rework_round}
                    </span>
                  </div>
                  {e.location && <p className="mt-1 text-tertiary">Vị trí: {e.location}</p>}
                  {e.description && <p className="mt-0.5 text-tertiary">{e.description}</p>}
                </li>
              ))}
            </ul>
          </section>
        )}

        {job.timeline.length > 0 && (
          <section className="border-t border-secondary pt-4">
            <h3 className="mb-2 text-sm font-semibold text-primary">Dòng thời gian</h3>
            <ol className="flex flex-col">
              {job.timeline.map((e, i) => {
                const nextStatus = e.after?.status as JobStatus | undefined
                return (
                  <li key={e.id} className="relative flex gap-3 pb-4 last:pb-0">
                    {i < job.timeline.length - 1 && (
                      <span aria-hidden className="absolute top-3 bottom-0 left-[4px] w-px bg-border-secondary" />
                    )}
                    <span className="mt-1.5 size-2.5 shrink-0 rounded-full bg-brand-solid" />
                    <div className="text-sm">
                      <p className="font-medium text-secondary">
                        {ACTION_LABELS[e.action] ?? e.action}
                        {nextStatus && <span className="font-normal text-tertiary"> → {JOB_STATUS_LABELS[nextStatus] ?? nextStatus}</span>}
                      </p>
                      <p className="text-xs text-quaternary">{e.actor?.full_name ?? 'Hệ thống'} · {formatDateTime(e.created_at)}</p>
                      {e.note && <p className="text-xs text-tertiary">{e.note}</p>}
                    </div>
                  </li>
                )
              })}
            </ol>
          </section>
        )}
      </div>
    </SectionCard>
  )
}

function Qc1ReviewForm({ projectId, job, onDone }: { projectId: number; job: JobDetail; onDone: () => void }) {
  const { run, pending } = useAction()
  const { data: categories } = useRequest(`error-categories:${projectId}:qc1`, () => listErrorCategories(projectId, 'qc1'))
  const [rows, setRows] = useState<ErrorRow[]>([])
  const [comment, setComment] = useState('')
  const [showErrors, setShowErrors] = useState(false)
  const nextKey = () => Math.max(0, ...rows.map((r) => r.key)) + 1
  const patch = (key: number, change: Partial<ErrorRow>) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...change } : r)))

  async function start() {
    if (await run(() => startQc1Job(projectId, job.id), `Đã nhận kiểm tra ${job.name}`)) onDone()
  }

  async function pass() {
    if (await run(() => passQc1Job(projectId, job.id, comment.trim()), `Đã Pass QC1 ${job.name} → Chờ QC2`)) onDone()
  }

  async function reject() {
    setShowErrors(true)
    if (rows.length === 0 || rows.some((r) => r.category == null)) return
    const errors = rows.map((r) => ({
      category: r.category!,
      severity: r.severity ?? undefined,
      location: r.location.trim(),
      description: r.description.trim(),
    }))
    if (await run(() => rejectQc1Job(projectId, job.id, errors, comment.trim()), `Đã Reject ${job.name} — job chuyển về Rework`)) {
      onDone()
    }
  }

  return (
    <div className="flex flex-col gap-4 border-t border-secondary pt-4">
      {job.status === 'pending_qc1' && (
        <div className="flex items-center justify-between gap-3 rounded-xl bg-secondary p-3.5">
          <p className="text-sm text-secondary">
            {job.qc1_reviewer ? 'Bắt đầu kiểm tra để chuyển sang Đang QC1.' : 'Job chưa có người QC1 — bấm nhận để khoá cho bạn.'}
          </p>
          <Button size="sm" color="secondary" isLoading={pending} onPress={start}>
            {job.qc1_reviewer ? 'Bắt đầu QC1' : 'Nhận job QC1'}
          </Button>
        </div>
      )}

      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-primary">Ghi lỗi QC1</h3>
        <span className="text-xs text-tertiary">Bắt buộc ít nhất 1 lỗi khi Reject</span>
      </div>

      {rows.map((row, index) => (
        <div key={row.key} className="flex flex-col gap-3 rounded-xl bg-secondary p-3.5 ring-1 ring-secondary ring-inset">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-tertiary">Lỗi {index + 1}</span>
            <Button
              size="xs"
              color="tertiary-destructive"
              iconLeading={Trash01}
              aria-label={`Xoá lỗi ${index + 1}`}
              onPress={() => setRows((rs) => rs.filter((r) => r.key !== row.key))}
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Select
              label="Loại lỗi"
              size="sm"
              isRequired
              placeholder="Chọn loại lỗi"
              isInvalid={showErrors && row.category == null}
              hint={showErrors && row.category == null ? 'Chọn loại lỗi' : undefined}
              items={(categories ?? []).map((c) => ({ id: c.id, label: c.name, supportingText: SEVERITY_LABELS[c.severity] }))}
              selectedKey={row.category}
              onSelectionChange={(k) => {
                const category = categories?.find((c) => c.id === Number(k))
                patch(row.key, { category: Number(k), severity: row.severity ?? category?.severity ?? null })
              }}
            >
              {(item) => <Select.Item id={item.id} label={item.label} supportingText={item.supportingText} />}
            </Select>
            <Select
              label="Mức độ"
              size="sm"
              placeholder="Theo loại lỗi"
              items={(Object.keys(SEVERITY_LABELS) as Severity[]).map((s) => ({ id: s, label: SEVERITY_LABELS[s] }))}
              selectedKey={row.severity}
              onSelectionChange={(k) => patch(row.key, { severity: k as Severity })}
            >
              {(item) => <Select.Item id={item.id} label={item.label} />}
            </Select>
          </div>
          <Input label="Vị trí lỗi" size="sm" placeholder="Frame / object ID" value={row.location} onChange={(v) => patch(row.key, { location: v })} />
          <TextArea label="Mô tả lỗi" placeholder="Nhập nội dung…" rows={2} value={row.description} onChange={(v) => patch(row.key, { description: v })} />
        </div>
      ))}

      <Button
        color="secondary"
        size="sm"
        iconLeading={Plus}
        className="self-start"
        onPress={() => setRows((rs) => [...rs, { key: nextKey(), category: null, severity: null, location: '', description: '' }])}
      >
        Thêm lỗi
      </Button>
      {showErrors && rows.length === 0 && <p className="text-sm text-error-primary">Thêm ít nhất 1 lỗi trước khi Reject.</p>}

      <TextArea label="Nhận xét (không bắt buộc)" rows={2} value={comment} onChange={setComment} />

      <div className="flex justify-end gap-3 border-t border-secondary pt-4">
        <Button color="primary-destructive" isLoading={pending} onPress={reject}>Reject → Rework</Button>
        <Button color="primary" isLoading={pending} onPress={pass}>Pass → QC2</Button>
      </div>
    </div>
  )
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-quaternary">{label}</dt>
      <dd className="font-medium text-secondary">{value}</dd>
    </div>
  )
}

function Notice({ text }: { text: string }) {
  return (
    <div className="flex gap-3 rounded-xl bg-warning-primary p-4 ring-1 ring-yellow-200 ring-inset">
      <AlertTriangle className="mt-0.5 size-5 shrink-0 text-fg-warning-primary" />
      <p className="text-sm text-warning-primary">{text}</p>
    </div>
  )
}
