import { Eye, InfoCircle, Lock01 } from '@untitledui/icons'
import { useState } from 'react'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { InputNumber } from '@/components/base/input/input-number'
import { Select } from '@/components/base/select/select'
import { getErrorMessage } from '../../../shared/api/errors'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import StatCard from '../../../shared/components/ui/StatCard'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import { updateSettings } from '../../projects/api'
import { useProject } from '../../projects/projectContext'
import type { SamplingMethod, StratifyBy } from '../../projects/types'
import { getAuditStrategy, previewAudit } from '../api'
import { METHOD_LABELS, STRATIFY_LABELS } from '../constants'
import type { AuditPreview, AuditStrategy } from '../types'
import { cx } from '@/utils/cx'

const METHODS: { id: SamplingMethod; title: string; description: string }[] = [
  { id: 'random', title: 'Random sampling', description: 'Chọn ngẫu nhiên N% job đang chờ QC2 trong batch.' },
  { id: 'stratified', title: 'Stratified sampling', description: 'Chia job theo nhóm (annotator, người QC1, dataset) rồi lấy N% mỗi nhóm — nhóm nào cũng có mẫu.' },
]
const FIELD_LABELS = { sampling_method: 'Phương pháp', sampling_rate: 'Tỉ lệ', stratify_by: 'Phân tầng theo' } as const

function describeValue(field: keyof typeof FIELD_LABELS, value: string | number | undefined) {
  if (value === undefined || value === '') return '—'
  if (field === 'sampling_method') return METHOD_LABELS[value as SamplingMethod] ?? String(value)
  if (field === 'sampling_rate') return `${value}%`
  return STRATIFY_LABELS[value as StratifyBy] ?? String(value)
}

/**
 * QC2-02 Chiến thuật audit. QC2 chỉ XEM chiến thuật đang áp dụng và xem trước mẫu;
 * PM (có quyền cấu hình) sửa được ngay tại đây. Áp dụng cho các đợt audit tạo sau khi lưu.
 */
export default function AuditStrategyPage() {
  const { projectId } = useProject()
  const [version, setVersion] = useState(0)
  const { data, error, isLoading, retry } = useRequest(`audit-strategy:${projectId}:${version}`, () => getAuditStrategy(projectId))

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Chiến thuật audit</h1>
          <p className="mt-1 text-sm text-tertiary">Cách chọn job để QC2 kiểm tra lại sau QC1.</p>
        </div>
        {data && !data.can_edit && (
          <Badge type="pill-color" size="md" color="gray"><span className="flex items-center gap-1"><Lock01 className="size-3.5" />Chỉ xem · do PM thiết lập</span></Badge>
        )}
      </header>

      {error != null ? (
        <SectionCard><PageState kind="error" description={getErrorMessage(error)} onRetry={retry} /></SectionCard>
      ) : isLoading || !data ? (
        <SectionCard><PageState kind="loading" /></SectionCard>
      ) : (
        <>
          <StrategyForm key={version} strategy={data} projectId={projectId} onSaved={() => setVersion((v) => v + 1)} />
          <div className="grid gap-5 lg:grid-cols-5">
            <PreviewSection strategy={data} projectId={projectId} className="lg:col-span-3" />
            <HistorySection strategy={data} className="lg:col-span-2" />
          </div>
          <div className="flex gap-3 rounded-xl bg-warning-primary p-4 ring-1 ring-yellow-200 ring-inset">
            <InfoCircle className="mt-0.5 size-5 shrink-0 text-fg-warning-primary" />
            <p className="text-sm text-warning-primary">
              <span className="font-semibold">Chờ chốt:</span> luật chọn Random / Stratified và tỉ lệ mặc định cần xác nhận lại với mentor.
            </p>
          </div>
        </>
      )}
    </div>
  )
}

function StrategyForm({ strategy, projectId, onSaved }: { strategy: AuditStrategy; projectId: number; onSaved: () => void }) {
  const [method, setMethod] = useState<SamplingMethod>(strategy.method)
  const [rate, setRate] = useState(strategy.sampling_rate)
  const [stratifyBy, setStratifyBy] = useState<StratifyBy>(strategy.stratify_by || 'annotator')
  const { run, pending } = useAction()
  const editable = strategy.can_edit
  const dirty = method !== strategy.method || rate !== strategy.sampling_rate || (method === 'stratified' && stratifyBy !== strategy.stratify_by)

  async function save() {
    const ok = await run(() => updateSettings(projectId, { sampling_method: method, sampling_rate: rate, stratify_by: stratifyBy }), 'Đã lưu chiến thuật')
    if (ok) onSaved()
  }

  return (
    <SectionCard
      title="Chọn chiến thuật lấy mẫu"
      description="Phạm vi áp dụng: các đợt audit tạo sau khi lưu. Đợt đang chạy giữ nguyên mẫu đã chọn."
      actions={editable && <Button size="sm" isDisabled={!dirty} isLoading={pending} onPress={save}>Lưu chiến thuật</Button>}
    >
      <div className="grid gap-6 lg:grid-cols-2">
        <div role="radiogroup" aria-label="Phương pháp lấy mẫu" className="flex flex-col gap-3">
          {METHODS.map((m) => {
            const selected = method === m.id
            return (
              <button
                key={m.id}
                type="button"
                role="radio"
                aria-checked={selected}
                disabled={!editable}
                onClick={() => setMethod(m.id)}
                className={cx(
                  'flex gap-3 rounded-xl p-4 text-left ring-1 transition duration-100 ring-inset',
                  selected ? 'bg-brand-primary_alt ring-2 ring-brand' : 'ring-secondary',
                  editable ? 'cursor-pointer hover:bg-primary_hover' : 'cursor-default',
                  !editable && !selected && 'opacity-60',
                )}
              >
                <span className={cx('mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full ring-1 ring-inset', selected ? 'bg-brand-solid ring-brand-solid' : 'ring-primary')}>
                  {selected && <span className="size-1.5 rounded-full bg-white" />}
                </span>
                <span>
                  <span className="block text-sm font-semibold text-secondary">{m.title}</span>
                  <span className="mt-0.5 block text-sm text-tertiary">{m.description}</span>
                </span>
              </button>
            )
          })}
        </div>

        <div className="flex flex-col gap-5">
          <div>
            <div className="mb-2 flex items-baseline justify-between">
              <span className="text-sm font-medium text-secondary">Tỉ lệ lấy mẫu</span>
              <span className="text-display-xs font-semibold text-primary tabular-nums">{rate}%</span>
            </div>
            <input
              type="range" min={1} max={100} value={rate} disabled={!editable}
              aria-label="Tỉ lệ lấy mẫu (%)"
              onChange={(e) => setRate(Number(e.target.value))}
              className="w-full accent-[var(--color-bg-brand-solid)] disabled:opacity-60"
            />
            <div className="flex justify-between text-xs text-quaternary"><span>1%</span><span>100%</span></div>
            {editable && (
              <InputNumber className="mt-3 max-w-40" aria-label="Nhập tỉ lệ" minValue={1} maxValue={100} value={rate}
                onChange={(v) => !Number.isNaN(v) && setRate(v)} />
            )}
          </div>
          {method === 'stratified' && (
            <Select
              label="Phân tầng theo"
              isDisabled={!editable}
              selectedKey={stratifyBy}
              onSelectionChange={(k) => setStratifyBy(k as StratifyBy)}
              items={(['annotator', 'qc1_reviewer', 'dataset'] as StratifyBy[]).map((s) => ({ id: s, label: STRATIFY_LABELS[s] }))}
            >
              {(item) => <Select.Item id={item.id} label={item.label} />}
            </Select>
          )}
        </div>
      </div>
    </SectionCard>
  )
}

function PreviewSection({ strategy, projectId, className }: { strategy: AuditStrategy; projectId: number; className?: string }) {
  const [batch, setBatch] = useState<number | null>(strategy.preview_batches[0]?.id ?? null)
  const [preview, setPreview] = useState<AuditPreview | null>(null)
  const { run, pending } = useAction()

  async function load() {
    if (batch == null) return
    const result = await run(() => previewAudit(projectId, { batch }))
    if (result) setPreview(result)
  }

  return (
    <SectionCard
      title="Xem trước mẫu audit"
      description="Theo chiến thuật đang áp dụng. Không lưu gì — mẫu thật được chọn khi PM tạo đợt audit, mỗi lần xem có thể khác."
      className={className}
    >
      {strategy.preview_batches.length === 0 ? (
        <PageState kind="empty" title="Không có batch nào để xem trước" description="Cần batch đang mở, có job Chờ QC2 và chưa có đợt audit đang chạy." />
      ) : (
        <div className="flex flex-col gap-5">
          <div className="flex flex-wrap items-end gap-3">
            <Select
              label="Batch"
              className="min-w-60 flex-1"
              selectedKey={batch}
              onSelectionChange={(k) => { setBatch(Number(k)); setPreview(null) }}
              items={strategy.preview_batches.map((b) => ({ id: b.id, label: b.name, supportingText: `${b.dataset_name} · ${b.pending_qc2} chờ QC2` }))}
            >
              {(item) => <Select.Item id={item.id} label={item.label} supportingText={item.supportingText} />}
            </Select>
            <Button color="secondary" size="md" iconLeading={Eye} isLoading={pending} onPress={load}>Xem trước</Button>
          </div>

          {preview && (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <StatCard value={preview.eligible_count} label="Job đủ điều kiện" />
                <StatCard value={preview.sample_count} label="Job sẽ lấy mẫu" />
                <StatCard value={preview.estimated_frames} label="Frame ước tính" />
                <StatCard value={preview.estimated_objects} label="Cuboid ước tính" />
              </div>
              <div className="overflow-hidden rounded-xl ring-1 ring-secondary">
                <table className="w-full text-sm">
                  <thead className="bg-secondary text-xs font-semibold text-quaternary">
                    <tr><th className="px-4 py-2 text-left">Job</th><th className="px-4 py-2 text-left">Nhóm</th><th className="px-4 py-2 text-left">Annotator</th><th className="px-4 py-2 text-right">Cuboid</th></tr>
                  </thead>
                  <tbody>
                    {preview.samples.map((s) => (
                      <tr key={s.job.id} className="border-t border-secondary">
                        <td className="px-4 py-2.5 font-medium text-primary">{s.job.name}</td>
                        <td className="px-4 py-2.5 text-tertiary">{s.stratum || '—'}</td>
                        <td className="px-4 py-2.5 text-tertiary">{s.job.annotator?.full_name ?? '—'}</td>
                        <td className="px-4 py-2.5 text-right text-tertiary tabular-nums">{s.job.object_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </SectionCard>
  )
}

function HistorySection({ strategy, className }: { strategy: AuditStrategy; className?: string }) {
  return (
    <SectionCard title="Lịch sử thay đổi chiến thuật" className={className}>
      {strategy.history.length === 0 ? (
        <PageState kind="empty" title="Chưa có thay đổi nào" description="Chiến thuật đang dùng giá trị mặc định của dự án." />
      ) : (
        <ol className="flex flex-col">
          {strategy.history.map((h, i) => (
            <li key={`${h.at}-${i}`} className="relative flex gap-3 pb-5 last:pb-0">
              {i < strategy.history.length - 1 && <span aria-hidden className="absolute top-3 bottom-0 left-[5px] w-px bg-border-secondary" />}
              <span className="mt-1.5 size-2.5 shrink-0 rounded-full bg-brand-solid ring-4 ring-brand-primary_alt" />
              <div className="text-sm">
                <p className="text-secondary">
                  <span className="font-semibold">{h.actor?.full_name ?? 'Hệ thống'}</span>
                  <span className="text-quaternary"> · {formatDateTime(h.at)}</span>
                </p>
                {(Object.keys(h.after) as (keyof typeof FIELD_LABELS)[]).map((field) => (
                  <p key={field} className="text-tertiary">
                    {FIELD_LABELS[field]}: <span className="line-through">{describeValue(field, h.before[field])}</span> → <span className="font-medium text-secondary">{describeValue(field, h.after[field])}</span>
                  </p>
                ))}
              </div>
            </li>
          ))}
        </ol>
      )}
    </SectionCard>
  )
}
