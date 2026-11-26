import { Lock01 } from '@untitledui/icons'
import { useState } from 'react'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { InputNumber } from '@/components/base/input/input-number'
import { getErrorMessage } from '../../../shared/api/errors'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import StatCard from '../../../shared/components/ui/StatCard'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import { updateSettings } from '../../projects/api'
import { useProject } from '../../projects/projectContext'
import { getAuditStrategy } from '../api'
import type { AuditStrategy } from '../types'

/**
 * QC2-02 Quy tắc QC2 (chỉ PM). Chốt 2026-11-25: MỌI job qua QC1 đều được QC2 kiểm,
 * mỗi job kiểm ngẫu nhiên N% số frame (làm tròn lên, ít nhất 1 frame). PM chỉnh N ở đây.
 */
export default function AuditStrategyPage() {
  const { projectId } = useProject()
  const [version, setVersion] = useState(0)
  const { data, error, isLoading, retry } = useRequest(`audit-strategy:${projectId}:${version}`, () => getAuditStrategy(projectId))

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Quy tắc QC2</h1>
          <p className="mt-1 text-sm text-tertiary">Mọi job qua QC1 đều được QC2 kiểm lại một phần frame.</p>
        </div>
        {data && !data.can_edit && (
          <Badge type="pill-color" size="md" color="gray"><span className="flex items-center gap-1"><Lock01 className="size-3.5" />Chỉ xem</span></Badge>
        )}
      </header>

      {error != null ? (
        <SectionCard><PageState kind="error" description={getErrorMessage(error)} onRetry={retry} /></SectionCard>
      ) : isLoading || !data ? (
        <SectionCard><PageState kind="loading" /></SectionCard>
      ) : (
        <>
          <RateForm key={version} strategy={data} projectId={projectId} onSaved={() => setVersion((v) => v + 1)} />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <StatCard value={data.stats.pending} label="Lượt QC2 đang chờ kiểm" />
            <StatCard value={data.stats.passed} label="Pass" />
            <StatCard value={data.stats.rejected} label="Reject" tone={data.stats.rejected ? 'error' : undefined} />
          </div>
          <HistorySection strategy={data} />
        </>
      )}
    </div>
  )
}

function RateForm({ strategy, projectId, onSaved }: { strategy: AuditStrategy; projectId: number; onSaved: () => void }) {
  const [rate, setRate] = useState(strategy.sampling_rate)
  const { run, pending } = useAction()
  const changed = rate !== strategy.sampling_rate
  const example = (frames: number) => Math.min(frames, Math.max(1, Math.ceil((frames * rate) / 100)))

  async function save() {
    if (await run(() => updateSettings(projectId, { sampling_rate: rate }), 'Đã lưu tỉ lệ QC2')) onSaved()
  }

  return (
    <SectionCard title="Tỉ lệ frame QC2 kiểm trong mỗi job"
      description="Frame được chọn ngẫu nhiên khi job vào Chờ QC2. Đổi tỉ lệ chỉ áp dụng cho các lượt QC2 tạo sau đó.">
      <div className="flex flex-wrap items-end gap-4">
        <InputNumber className="max-w-40" label="Tỉ lệ (%)" minValue={1} maxValue={100} value={rate}
          isDisabled={!strategy.can_edit} onChange={(v) => setRate(Number.isNaN(v) ? strategy.sampling_rate : v)} />
        {strategy.can_edit && <Button size="md" isDisabled={!changed} isLoading={pending} onPress={save}>Lưu</Button>}
      </div>
      <p className="mt-4 text-sm text-tertiary">
        Ví dụ với {rate}%: job 1 frame → kiểm {example(1)} frame · job 10 frame → {example(10)} frame · job 100 frame → {example(100)} frame.
      </p>
    </SectionCard>
  )
}

function HistorySection({ strategy }: { strategy: AuditStrategy }) {
  return (
    <SectionCard title="Lịch sử thay đổi">
      {strategy.history.length === 0 ? (
        <p className="text-sm text-tertiary">Chưa thay đổi lần nào.</p>
      ) : (
        <ol className="flex flex-col gap-3 text-sm">
          {strategy.history.map((h, i) => (
            <li key={i} className="flex flex-wrap items-baseline gap-x-2">
              <span className="font-medium text-secondary">{h.before.sampling_rate ?? '—'}% → {h.after.sampling_rate ?? '—'}%</span>
              <span className="text-quaternary">{h.actor?.full_name ?? 'Hệ thống'} · {formatDateTime(h.at)}</span>
            </li>
          ))}
        </ol>
      )}
    </SectionCard>
  )
}
