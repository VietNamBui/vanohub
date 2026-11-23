import { AlertTriangle, LinkExternal01, Plus, Trash01 } from '@untitledui/icons'
import { useState } from 'react'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { Input } from '@/components/base/input/input'
import { Select } from '@/components/base/select/select'
import { TextArea } from '@/components/base/textarea/textarea'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import { listErrorCategories, passSample, rejectSample } from '../api'
import { RESULT_LABELS, SEVERITY_LABELS } from '../constants'
import type { AuditSample, Severity } from '../types'

interface Props {
  projectId: number
  sample: AuditSample
  /** Luật bốn mắt: người đang xem đã annotate / QC1 job này. */
  conflict: boolean
  onDone: () => void
}

type ErrorRow = { key: number; category: number | null; severity: Severity | null; location: string; description: string }

const RESULT_BADGE_COLORS = { pending: 'gray', pass: 'success', reject: 'error' } as const
const SEVERITY_BADGE_COLORS = { minor: 'gray', major: 'warning', critical: 'error' } as const

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
      description={`${job.batch_name} · Audit #${sample.audit}${sample.stratum ? ` · nhóm ${sample.stratum}` : ''}`}
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

      {decided ? (
        <DecidedView sample={sample} />
      ) : closed ? (
        <Notice text="Đợt audit đã chốt — không ghi kết quả được nữa." />
      ) : conflict ? (
        <Notice text="Luật bốn mắt: bạn đã annotate hoặc QC1 job này nên không được audit." />
      ) : (
        <ReviewForm projectId={projectId} sample={sample} onDone={onDone} />
      )}
    </SectionCard>
  )
}

function ReviewForm({ projectId, sample, onDone }: { projectId: number; sample: AuditSample; onDone: () => void }) {
  const { run, pending } = useAction()
  const { data: categories } = useRequest(`error-categories:${projectId}:qc2`, () => listErrorCategories(projectId, 'qc2'))
  const [rows, setRows] = useState<ErrorRow[]>([])
  const [comment, setComment] = useState('')
  const [showErrors, setShowErrors] = useState(false)
  const nextKey = () => Math.max(0, ...rows.map((r) => r.key)) + 1
  const patch = (key: number, change: Partial<ErrorRow>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...change } : r)))

  async function pass() {
    if (await run(() => passSample(projectId, sample.id, comment), `Đã Pass ${sample.job.name}`)) onDone()
  }

  async function reject() {
    setShowErrors(true)
    if (rows.length === 0 || rows.some((r) => r.category == null)) return
    const errors = rows.map((r) => ({
      category: r.category!, severity: r.severity ?? undefined, location: r.location.trim(), description: r.description.trim(),
    }))
    if (await run(() => rejectSample(projectId, sample.id, errors, comment), `Đã Reject ${sample.job.name} — job chuyển về Rework`)) onDone()
  }

  return (
    <div className="flex flex-col gap-4 border-t border-secondary pt-5">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-primary">Ghi lỗi audit</h3>
        <span className="text-xs text-tertiary">Bắt buộc ít nhất 1 lỗi khi Reject</span>
      </div>

      {rows.map((row, index) => (
        <div key={row.key} className="flex flex-col gap-3 rounded-xl bg-secondary p-3.5 ring-1 ring-secondary ring-inset">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-tertiary">Lỗi {index + 1}</span>
            <Button size="xs" color="tertiary-destructive" iconLeading={Trash01} aria-label={`Xoá lỗi ${index + 1}`}
              onPress={() => setRows((rs) => rs.filter((r) => r.key !== row.key))} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Select
              label="Loại lỗi" size="sm" isRequired placeholder="Chọn loại lỗi"
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
              label="Mức độ" size="sm" placeholder="Theo loại lỗi"
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

      <Button color="secondary" size="sm" iconLeading={Plus} className="self-start"
        onPress={() => setRows((rs) => [...rs, { key: nextKey(), category: null, severity: null, location: '', description: '' }])}>
        Thêm lỗi
      </Button>
      {showErrors && rows.length === 0 && <p className="text-sm text-error-primary">Thêm ít nhất 1 lỗi trước khi Reject.</p>}

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
            <li key={e.id} className="rounded-lg p-3 ring-1 ring-secondary ring-inset">
              <div className="flex items-center gap-2">
                <span className="font-semibold text-secondary">{e.category_name}</span>
                <Badge type="color" size="sm" color={SEVERITY_BADGE_COLORS[e.severity]}>{SEVERITY_LABELS[e.severity]}</Badge>
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
    <div className="flex gap-3 rounded-xl bg-warning-primary p-4 ring-1 ring-yellow-200 ring-inset">
      <AlertTriangle className="mt-0.5 size-5 shrink-0 text-fg-warning-primary" />
      <p className="text-sm text-warning-primary">{text}</p>
    </div>
  )
}
