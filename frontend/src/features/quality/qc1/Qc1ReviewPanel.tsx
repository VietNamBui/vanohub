import { AlertTriangle, LinkExternal01, Plus, Trash01 } from '@untitledui/icons'
import { useState } from 'react'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { Checkbox } from '@/components/base/checkbox/checkbox'
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
import ReviewErrorChips from '../../jobs/components/ReviewErrorChips'
import { ACTION_LABELS, formatDeadlineCountdown, JOB_STATUS_LABELS } from '../../jobs/constants'
import {
  isJobEscalationBlocked,
  isJobEscalationWarnOnly,
  parseOptionalInt,
  splitActiveErrors,
} from '../../jobs/jobHelpers'
import type { JobDetail, JobStatus, ReworkScope } from '../../jobs/types'
import { useProject } from '../../projects/projectContext'
import { getQc1Job, listErrorCategories, passQc1Job, rejectQc1Job, startQc1Job } from '../api'
import { SEVERITY_LABELS } from '../constants'
import type { ErrorInput, ErrorVerdict, Severity } from '../types'

interface Props {
  projectId: number
  jobId: number
  version: number
  onDone: () => void
}

type ErrorRow = {
  key: number
  category: number | null
  severity: Severity | null
  verdict: ErrorVerdict
  is_missing_object: boolean
  frame_number: string
  cvat_object_id: string
  location: string
  description: string
}

const SEVERITY_BADGE_COLORS: Record<string, 'gray' | 'warning' | 'error'> = {
  minor: 'gray',
  major: 'warning',
  critical: 'error',
}

const VERDICT_OPTIONS: { id: ErrorVerdict; label: string }[] = [
  { id: 'fail', label: 'Lỗi (Fail)' },
  { id: 'edge', label: 'Cận biên (Edge)' },
]

/** Khung kiểm tra QC1 cho một job: mở CVAT, nhận bắt đầu, duyệt Đạt QC1 hoặc Reject kèm lỗi có cấu trúc. */
export default function Qc1ReviewPanel({ projectId, jobId, version, onDone }: Props) {
  const { project } = useProject()
  const { data: job, error, isLoading, retry } = useRequest(`qc1-job:${projectId}:${jobId}:${version}`, () =>
    getQc1Job(projectId, jobId),
  )

  if (error != null) return <SectionCard><PageState kind="error" description={getErrorMessage(error)} onRetry={retry} /></SectionCard>
  if (isLoading || !job) return <SectionCard><PageState kind="loading" /></SectionCard>

  const reviewable = job.status === 'pending_qc1' || job.status === 'qc1_reviewing'
  const isEscalatedBlocked = isJobEscalationBlocked(job, project.escalation_policy)
  const isEscalatedWarnOnly = isJobEscalationWarnOnly(job, project.escalation_policy)
  const countdown = formatDeadlineCountdown(job.hours_remaining)
  const { active: activeErrors, history: historyErrors } = splitActiveErrors(job, job.errors)

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
        <div className="flex flex-wrap items-center gap-2">
          <JobStatusBadge
            status={job.status}
            escalated={job.is_escalated}
            overdue={job.is_overdue}
            locked={job.is_locked}
            sourceMissing={job.source_missing}
          />
          {job.rework_round > 0 && (
            <Badge size="sm" type="pill-color" color="brand">
              {job.rework_scope === 'full' ? 'Sửa toàn job' : 'Sửa một phần'}
            </Badge>
          )}
          {countdown && (
            <Badge size="sm" type="pill-color" color={countdown.tone}>
              {countdown.text}
            </Badge>
          )}
        </div>

        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
          <Info label="Annotator" value={job.annotator?.full_name ?? 'Chưa giao'} />
          <Info label="Người QC1" value={job.qc1_reviewer?.full_name ?? 'Chưa nhận (Pool)'} />
          <Info label="Object / frame" value={`${job.object_count} / ${job.frame_count}`} />
          <Info label="Vòng rework" value={`${job.rework_round} / ${job.max_rework_rounds}`} />
          <Info label="Deadline" value={formatDateTime(job.deadline)} />
        </dl>

        {job.source_missing && (
          <Notice text="Không còn tìm thấy job nguồn trên CVAT ở lần đồng bộ gần nhất." />
        )}

        {job.is_locked ? (
          <Notice text="Job đang bị khoá — không thể kiểm tra." />
        ) : isEscalatedBlocked ? (
          <Notice text="Job đang ở trạng thái Escalated (chế độ chặn), chờ PM xử lý." />
        ) : reviewable ? (
          <>
            {isEscalatedWarnOnly && (
              <Notice text="Job đã vượt số vòng rework tối đa — chế độ cảnh báo, bạn vẫn có thể tiếp tục kiểm tra." />
            )}
            <Qc1ReviewForm key={`${job.id}:${job.status}:${job.updated_at}`} projectId={projectId} job={job} onDone={onDone} />
          </>
        ) : (
          <p className="rounded-lg bg-secondary p-3 text-sm text-tertiary">
            Job hiện ở trạng thái <span className="font-medium text-secondary">{JOB_STATUS_LABELS[job.status]}</span> — không còn trong hàng chờ QC1.
          </p>
        )}

        {job.errors.length > 0 && (
          <section className="border-t border-secondary pt-4">
            <h3 className="mb-2 text-sm font-semibold text-primary">
              Lỗi đã ghi nhận{' '}
              <span className="font-normal text-tertiary">
                ({activeErrors.length} hiệu lực{historyErrors.length > 0 ? ` · ${historyErrors.length} lịch sử / đã huỷ` : ''})
              </span>
            </h3>

            {activeErrors.length > 0 && (
              <ul className="flex flex-col gap-2">
                {activeErrors.map((e) => (
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
                    <ReviewErrorChips err={e} />
                    {e.location && <p className="mt-1 text-tertiary">Vị trí: {e.location}</p>}
                    {e.description && <p className="mt-0.5 text-tertiary">{e.description}</p>}
                  </li>
                ))}
              </ul>
            )}

            {historyErrors.length > 0 && (
              <div className={activeErrors.length > 0 ? 'mt-3 border-t border-secondary pt-3' : undefined}>
                <p className="mb-2 text-xs font-semibold text-quaternary">
                  Lịch sử lỗi các vòng trước & lỗi đã huỷ ({historyErrors.length})
                </p>
                <ul className="flex flex-col gap-2">
                  {historyErrors.map((e) => (
                    <li key={e.id} className="rounded-lg p-3 text-sm opacity-70 ring-1 ring-secondary ring-inset">
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={`font-semibold ${
                            e.is_voided ? 'text-tertiary line-through' : 'text-secondary'
                          }`}
                        >
                          {e.category}
                        </span>
                        <Badge type="color" size="sm" color={SEVERITY_BADGE_COLORS[e.severity] ?? 'gray'}>
                          {SEVERITY_LABELS[e.severity as Severity] ?? e.severity}
                        </Badge>
                        <span className="text-xs text-quaternary">
                          {e.stage.toUpperCase()} · vòng {e.rework_round}
                        </span>
                      </div>
                      <ReviewErrorChips err={e} />
                      {e.location && (
                        <p className={`mt-1 text-tertiary ${e.is_voided ? 'line-through' : ''}`}>
                          Vị trí: {e.location}
                        </p>
                      )}
                      {e.description && (
                        <p className={`mt-0.5 text-tertiary ${e.is_voided ? 'line-through' : ''}`}>
                          {e.description}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
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
                      <span aria-hidden className="absolute top-3 bottom-0 left-1 w-px bg-border-secondary" />
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
  const [reworkScope, setReworkScope] = useState<ReworkScope>('partial')
  const [comment, setComment] = useState('')
  const [showErrors, setShowErrors] = useState(false)
  const nextKey = () => Math.max(0, ...rows.map((r) => r.key)) + 1
  const patch = (key: number, change: Partial<ErrorRow>) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...change } : r)))

  async function start() {
    if (await run(() => startQc1Job(projectId, job.id), `Đã nhận kiểm tra ${job.name}`)) onDone()
  }

  async function pass() {
    if (await run(() => passQc1Job(projectId, job.id, comment.trim()), `Đã duyệt đạt QC1 cho ${job.name}`)) onDone()
  }

  async function reject() {
    setShowErrors(true)
    if (rows.length === 0) return

    const errors: ErrorInput[] = []
    for (const r of rows) {
      if (r.category == null) return
      const frame = parseOptionalInt(r.frame_number, 0)
      const objId = r.is_missing_object ? { valid: true, value: null } : parseOptionalInt(r.cvat_object_id, 1)
      if (!frame.valid || !objId.valid) return
      errors.push({
        category: r.category,
        severity: r.severity ?? undefined,
        verdict: r.is_missing_object ? 'fail' : r.verdict,
        is_missing_object: r.is_missing_object,
        frame_number: frame.value,
        cvat_object_id: objId.value,
        location: r.location.trim(),
        description: r.description.trim(),
      })
    }

    if (
      await run(
        () => rejectQc1Job(projectId, job.id, errors, comment.trim(), reworkScope),
        `Đã Reject ${job.name} — job chuyển về Rework`,
      )
    ) {
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

      {rows.map((row, index) => {
        const frameParsed = parseOptionalInt(row.frame_number, 0)
        const objectParsed = row.is_missing_object ? { valid: true, value: null } : parseOptionalInt(row.cvat_object_id, 1)
        return (
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
                name={`error-${row.key}-category`}
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
                name={`error-${row.key}-severity`}
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
            <div className="grid items-end gap-3 sm:grid-cols-2">
              <Select
                name={`error-${row.key}-verdict`}
                label="Kết luận"
                size="sm"
                isDisabled={row.is_missing_object}
                items={VERDICT_OPTIONS}
                selectedKey={row.is_missing_object ? 'fail' : row.verdict}
                onSelectionChange={(k) => patch(row.key, { verdict: k as ErrorVerdict })}
              >
                {(item) => <Select.Item id={item.id} label={item.label} />}
              </Select>
              <div className="pb-1.5">
                <Checkbox
                  name={`error-${row.key}-missing`}
                  size="sm"
                  label="Thiếu đối tượng"
                  hint="Bắt buộc Lỗi (Fail), bỏ qua Object ID"
                  isSelected={row.is_missing_object}
                  onChange={(checked) =>
                    patch(
                      row.key,
                      checked
                        ? { is_missing_object: true, cvat_object_id: '', verdict: 'fail' }
                        : { is_missing_object: false },
                    )
                  }
                />
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Input
                name={`error-${row.key}-frame`}
                label="Frame"
                size="sm"
                inputMode="numeric"
                placeholder="VD: 12"
                value={row.frame_number}
                onChange={(v) => patch(row.key, { frame_number: v })}
                isInvalid={showErrors && !frameParsed.valid}
                hint={showErrors && !frameParsed.valid ? 'Nhập số nguyên ≥ 0' : undefined}
              />
              <Input
                name={`error-${row.key}-object-id`}
                label="CVAT Object ID"
                size="sm"
                inputMode="numeric"
                isDisabled={row.is_missing_object}
                placeholder={row.is_missing_object ? 'Không áp dụng' : 'VD: 42'}
                value={row.cvat_object_id}
                onChange={(v) => patch(row.key, { cvat_object_id: v })}
                isInvalid={showErrors && !objectParsed.valid}
                hint={showErrors && !objectParsed.valid ? 'Nhập số nguyên ≥ 1' : undefined}
              />
            </div>
            <Input name={`error-${row.key}-location`} label="Vị trí lỗi" size="sm" placeholder="Mô tả ngắn vị trí (tuỳ chọn)" value={row.location} onChange={(v) => patch(row.key, { location: v })} />
            <TextArea name={`error-${row.key}-description`} label="Mô tả lỗi" placeholder="Nhập nội dung…" rows={2} value={row.description} onChange={(v) => patch(row.key, { description: v })} />
          </div>
        )
      })}

      <Button
        color="secondary"
        size="sm"
        iconLeading={Plus}
        className="self-start"
        onPress={() =>
          setRows((rs) => [
            ...rs,
            {
              key: nextKey(),
              category: null,
              severity: null,
              verdict: 'fail',
              is_missing_object: false,
              frame_number: '',
              cvat_object_id: '',
              location: '',
              description: '',
            },
          ])
        }
      >
        Thêm lỗi
      </Button>
      {showErrors && rows.length === 0 && <p className="text-sm text-error-primary">Thêm ít nhất 1 lỗi trước khi Reject.</p>}

      <Select
        name="rework_scope"
        label="Phạm vi rework (khi Reject)"
        size="sm"
        items={[
          { id: 'partial', label: 'Sửa một phần', supportingText: 'Chỉ sửa các lỗi đã ghi' },
          { id: 'full', label: 'Sửa toàn job', supportingText: 'Rà soát lại toàn bộ frame' },
        ]}
        selectedKey={reworkScope}
        onSelectionChange={(k) => setReworkScope(k as ReworkScope)}
      >
        {(item) => <Select.Item id={item.id} label={item.label} supportingText={item.supportingText} />}
      </Select>

      <TextArea name="qc1_comment" label="Nhận xét (không bắt buộc)" rows={2} value={comment} onChange={setComment} />

      <div className="flex justify-end gap-3 border-t border-secondary pt-4">
        <Button color="primary-destructive" isLoading={pending} onPress={reject}>Reject → Rework</Button>
        <Button color="primary" isLoading={pending} onPress={pass}>Đạt QC1</Button>
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
    <div className="flex gap-3 rounded-xl bg-warning-primary p-4 ring-1 ring-utility-yellow-200 ring-inset">
      <AlertTriangle className="mt-0.5 size-5 shrink-0 text-fg-warning-primary" />
      <p className="text-sm text-warning-primary">{text}</p>
    </div>
  )
}
