import { AlertTriangle, LinkExternal01, Plus, Trash01 } from '@untitledui/icons'
import { useState } from 'react'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { Checkbox } from '@/components/base/checkbox/checkbox'
import { Input } from '@/components/base/input/input'
import { Select } from '@/components/base/select/select'
import { TextArea } from '@/components/base/textarea/textarea'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import type { ReworkScope } from '../../jobs/types'
import { listErrorCategories, passSample, rejectSample } from '../api'
import { RESULT_LABELS, SEVERITY_LABELS } from '../constants'
import type { AuditSample, ErrorInput, ErrorVerdict, Severity } from '../types'
import { cx } from '@/utils/cx'

interface Props {
  projectId: number
  sample: AuditSample
  /** Luật bốn mắt: người đang xem đã annotate / QC1 job này. */
  conflict: boolean
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

const PG_INT32_MAX = 2_147_483_647

const RESULT_BADGE_COLORS = { pending: 'gray', pass: 'success', reject: 'error' } as const
const SEVERITY_BADGE_COLORS = { minor: 'gray', major: 'warning', critical: 'error' } as const

const VERDICT_OPTIONS: { id: ErrorVerdict; label: string }[] = [
  { id: 'fail', label: 'Lỗi (Fail)' },
  { id: 'edge', label: 'Cận biên (Edge)' },
]

function parseOptionalInt(raw: string, min: number): { valid: boolean; value: number | null } {
  const trimmed = raw.trim()
  if (!trimmed) return { valid: true, value: null }
  if (!/^\d+$/.test(trimmed)) return { valid: false, value: null }
  const num = Number(trimmed)
  if (!Number.isSafeInteger(num) || num < min || num > PG_INT32_MAX) return { valid: false, value: null }
  return { valid: true, value: num }
}

export function ResultBadge({ result }: { result: AuditSample['result'] }) {
  return <Badge type="pill-color" size="sm" color={RESULT_BADGE_COLORS[result]}>{RESULT_LABELS[result]}</Badge>
}

/** Khung "Ghi lỗi audit" cho một mẫu: mở CVAT để kiểm, rồi Pass hoặc Reject kèm danh sách lỗi. */
export default function ReviewPanel({ projectId, sample, conflict, onDone }: Props) {
  const job = sample.job
  const decided = sample.result !== 'pending'
  const closed = sample.audit_status !== 'in_progress'

  return (
    <SectionCard
      title={job.name}
      description={`${job.dataset_name} / ${job.batch_name}${sample.rework_round ? ` · vòng rework ${sample.rework_round}` : ''}`}
      actions={job.cvat_url ? (
        <Button size="sm" color="secondary" iconTrailing={LinkExternal01} href={job.cvat_url} target="_blank" rel="noreferrer">Mở trong CVAT</Button>
      ) : <span className="text-sm text-quaternary">Chưa liên kết CVAT</span>}
    >
      <dl className="mb-5 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
        <Info label="Annotator" value={job.annotator?.full_name} />
        <Info label="QC1" value={job.qc1_reviewer?.full_name} />
        <Info label="Object / frame" value={`${job.object_count} / ${job.frame_count}`} />
        <Info label="Vòng rework" value={String(job.rework_round)} />
      </dl>

      <FramesToCheck sample={sample} />

      {decided ? (
        <DecidedView sample={sample} />
      ) : closed ? (
        <Notice text="Đợt audit đã chốt — không ghi kết quả được nữa." />
      ) : conflict ? (
        <Notice text="Luật bốn mắt: bạn đã annotate hoặc QC1 job này nên không được audit." />
      ) : (
        <ReviewForm key={sample.id} projectId={projectId} sample={sample} onDone={onDone} />
      )}
    </SectionCard>
  )
}

function ReviewForm({ projectId, sample, onDone }: { projectId: number; sample: AuditSample; onDone: () => void }) {
  const { run, pending } = useAction()
  const { data: categories } = useRequest(`error-categories:${projectId}:qc2`, () => listErrorCategories(projectId, 'qc2'))
  const [rows, setRows] = useState<ErrorRow[]>([])
  const [reworkScope, setReworkScope] = useState<ReworkScope>('partial')
  const [comment, setComment] = useState('')
  const [showErrors, setShowErrors] = useState(false)
  const nextKey = () => Math.max(0, ...rows.map((r) => r.key)) + 1
  const patch = (key: number, change: Partial<ErrorRow>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...change } : r)))

  async function pass() {
    if (await run(() => passSample(projectId, sample.id, comment.trim()), `Đã Pass ${sample.job.name}`)) onDone()
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
        () => rejectSample(projectId, sample.id, errors, comment.trim(), reworkScope),
        `Đã Reject ${sample.job.name} — job chuyển về Rework`,
      )
    ) {
      onDone()
    }
  }

  return (
    <div className="flex flex-col gap-4 border-t border-secondary pt-5">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-primary">Ghi lỗi audit</h3>
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
            <div className="grid items-end gap-3 sm:grid-cols-2">
              <Select
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
            {sample.frames.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-xs text-quaternary">Điền nhanh frame:</span>
                {sample.frames.map((frame) => {
                  const active = row.frame_number.trim() === String(frame)
                  return (
                    <button
                      key={frame}
                      type="button"
                      onClick={() => patch(row.key, { frame_number: String(frame) })}
                      className={cx(
                        'cursor-pointer rounded-md px-2 py-0.5 text-xs font-medium tabular-nums ring-1 transition ring-inset',
                        active
                          ? 'bg-brand-primary_alt text-brand-secondary ring-brand'
                          : 'bg-primary text-tertiary ring-secondary hover:bg-primary_hover hover:text-secondary',
                      )}
                    >
                      #{frame}
                    </button>
                  )
                })}
              </div>
            )}
            <Input label="Vị trí lỗi" size="sm" placeholder="Mô tả ngắn vị trí (tuỳ chọn)" value={row.location} onChange={(v) => patch(row.key, { location: v })} />
            <TextArea label="Mô tả lỗi" placeholder="Nhập nội dung…" rows={2} value={row.description} onChange={(v) => patch(row.key, { description: v })} />
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

      <TextArea label="Nhận xét (không bắt buộc)" rows={2} value={comment} onChange={setComment} />

      <div className="flex justify-end gap-3 border-t border-secondary pt-4">
        <Button color="primary-destructive" isLoading={pending} onPress={reject}>Reject → Rework</Button>
        <Button color="primary" isLoading={pending} onPress={pass}>Pass</Button>
      </div>
    </div>
  )
}

function DecidedView({ sample }: { sample: AuditSample }) {
  return (
    <div className="flex flex-col gap-3 border-t border-secondary pt-5 text-sm">
      <p className="flex flex-wrap items-center gap-2 text-tertiary">
        <ResultBadge result={sample.result} />
        bởi <span className="font-medium text-secondary">{sample.reviewed_by?.full_name ?? '—'}</span> lúc {formatDateTime(sample.reviewed_at)}
      </p>
      {sample.comment && <p className="rounded-lg bg-secondary p-3 text-secondary">{sample.comment}</p>}
      {sample.errors.length > 0 && (
        <ul className="flex flex-col gap-2">
          {sample.errors.map((e) => (
            <li
              key={e.id}
              className={cx(
                'rounded-lg p-3 ring-1 ring-secondary ring-inset',
                e.is_voided && 'bg-secondary opacity-75',
              )}
            >
              <div className="flex flex-wrap items-center gap-1.5">
                <span className={cx('font-semibold text-secondary', e.is_voided && 'line-through')}>
                  {e.category_name}
                </span>
                <Badge type="color" size="sm" color={SEVERITY_BADGE_COLORS[e.severity]}>
                  {SEVERITY_LABELS[e.severity]}
                </Badge>
                {e.verdict && (
                  <Badge type="color" size="sm" color={e.verdict === 'edge' ? 'warning' : 'error'}>
                    {e.verdict === 'edge' ? 'Cận biên (Edge)' : 'Lỗi (Fail)'}
                  </Badge>
                )}
                {e.is_missing_object && (
                  <Badge type="color" size="sm" color="orange">
                    Thiếu đối tượng
                  </Badge>
                )}
                {e.frame_number != null && (
                  <Badge type="pill-color" size="sm" color="brand">
                    Frame #{e.frame_number}
                  </Badge>
                )}
                {e.cvat_object_id != null && (
                  <Badge type="pill-color" size="sm" color="gray">
                    Object #{e.cvat_object_id}
                  </Badge>
                )}
                {e.is_voided && (
                  <Badge type="pill-color" size="sm" color="gray">
                    Đã huỷ lỗi
                  </Badge>
                )}
              </div>
              {e.location && <p className="mt-1 text-tertiary">Vị trí: {e.location}</p>}
              {e.description && <p className="mt-0.5 text-tertiary">{e.description}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Info({ label, value }: { label: string; value?: string | null }) {
  return (
    <div>
      <dt className="text-xs text-quaternary">{label}</dt>
      <dd className="font-medium text-secondary">{value ?? '—'}</dd>
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

/** Các frame QC2 cần kiểm (đánh số theo task như trên CVAT). Bấm để mở CVAT đúng frame đó. */
function FramesToCheck({ sample }: { sample: AuditSample }) {
  const url = sample.job.cvat_url
  return (
    <section className="mb-5">
      <h3 className="mb-2 text-sm font-semibold text-primary">
        Frame cần kiểm <span className="font-normal text-tertiary">· {sample.frames.length}/{sample.job.frame_count} frame của job</span>
      </h3>
      <ul className="flex flex-wrap gap-1.5">
        {sample.frames.map((frame) => (
          <li key={frame}>
            {url ? (
              <a
                href={`${url}?frame=${frame}`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex rounded-md px-2 py-1 text-sm font-medium text-brand-secondary tabular-nums ring-1 ring-secondary ring-inset hover:bg-primary_hover"
              >
                #{frame}
              </a>
            ) : (
              <span className="inline-flex rounded-md px-2 py-1 text-sm tabular-nums ring-1 ring-secondary ring-inset">#{frame}</span>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
