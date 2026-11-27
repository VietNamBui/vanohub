import { InfoCircle, SearchLg } from '@untitledui/icons'
import { useState } from 'react'
import { Table } from '@/components/application/table/table'
import { Tabs } from '@/components/application/tabs/tabs'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { Input } from '@/components/base/input/input'
import { getErrorMessage } from '../../../shared/api/errors'
import EmptyRow from '../../../shared/components/ui/EmptyRow'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { useAuth } from '../../auth/useAuth'
import { useProject } from '../../projects/projectContext'
import { listAuditSamples, passSample } from '../api'
import type { AuditSample } from '../types'
import ReviewPanel, { ResultBadge } from './ReviewPanel'

type ResultFilter = 'pending' | 'pass' | 'reject' | 'all'
const FILTERS: { id: ResultFilter; label: string }[] = [
  { id: 'pending', label: 'Chờ audit' },
  { id: 'pass', label: 'Pass' },
  { id: 'reject', label: 'Reject' },
  { id: 'all', label: 'Tất cả' },
]

/**
 * QC2-03 Job audit QC2 — dùng chung cho QC2 chuyên trách và PM (PM luôn kiêm QC2).
 * QC2 chuyên trách chỉ thấy mẫu được giao cho mình (backend lọc). QC2 quyết Pass / Reject từng job.
 */
export default function AuditWorkPage() {
  const { projectId, can } = useProject()
  const { user } = useAuth()
  const isManager = can('manage_audits')
  const [result, setResult] = useState<ResultFilter>('pending')
  const [mine, setMine] = useState(true)
  const [search, setSearch] = useState('')
  const [version, setVersion] = useState(0)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const { run } = useAction()
  const { data, error, isLoading, retry } = useRequest(`qc2-work:${projectId}:${result}:${mine}:${version}`, () =>
    listAuditSamples(projectId, {
      result: result === 'all' ? undefined : result,
      mine: isManager ? mine : undefined,
      open: result === 'pending',
    }),
  )
  const reload = () => setVersion((v) => v + 1)

  const keyword = search.trim().toLowerCase()
  const samples = (data ?? []).filter((s) =>
    !keyword || [s.job.name, s.job.batch_name, s.job.annotator?.full_name ?? ''].some((v) => v.toLowerCase().includes(keyword)))
  const selected = samples.find((s) => s.id === selectedId) ?? samples[0]
  const conflict = (s: AuditSample) => !!user && (s.job.annotator?.id === user.id || s.job.qc1_reviewer?.id === user.id)

  async function quickPass(sample: AuditSample) {
    if (await run(() => passSample(projectId, sample.id), `Đã Pass ${sample.job.name}`)) reload()
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Job audit QC2</h1>
          <p className="mt-1 text-sm text-tertiary">Mở job trong CVAT để kiểm tra, rồi ghi Pass hoặc Reject kèm lỗi.</p>
        </div>
        {isManager && (
          <Tabs selectedKey={mine ? 'mine' : 'all'} onSelectionChange={(k) => { setMine(k === 'mine'); setSelectedId(null) }} className="w-auto">
            <Tabs.List type="button-border" size="sm" aria-label="Phạm vi">
              <Tabs.Item id="mine" label="Được giao cho tôi" />
              <Tabs.Item id="all" label="Tất cả mẫu" />
            </Tabs.List>
          </Tabs>
        )}
      </header>

      <div className="flex items-start gap-3 rounded-xl bg-brand-primary_alt p-4 ring-1 ring-brand ring-inset">
        <InfoCircle className="mt-0.5 size-5 shrink-0 text-fg-brand-primary" />
        <p className="text-sm text-secondary">
          <span className="font-semibold">Mỗi job qua QC1 đều được kiểm một phần frame — QC2 quyết Pass / Reject từng job.</span>{' '}
          Reject → job về Rework và tăng vòng rework. Lỗi QC2 tìm thấy được tính là lỗi QC1 bỏ sót.
        </p>
      </div>

      {error != null ? (
        <SectionCard><PageState kind="error" description={getErrorMessage(error)} onRetry={retry} /></SectionCard>
      ) : (
        <div className="grid items-start gap-5 xl:grid-cols-5">
          <SectionCard className="xl:col-span-3" bodyClassName="p-0">
            <div className="flex flex-wrap items-center gap-3 border-b border-secondary p-4">
              <Tabs selectedKey={result} onSelectionChange={(k) => { setResult(k as ResultFilter); setSelectedId(null) }} className="w-auto">
                <Tabs.List type="button-gray" size="sm" aria-label="Kết quả">
                  {FILTERS.map((f) => <Tabs.Item key={f.id} id={f.id} label={f.label} />)}
                </Tabs.List>
              </Tabs>
              <Input className="min-w-48 flex-1" size="sm" icon={SearchLg} aria-label="Tìm kiếm" placeholder="Tìm job, task, annotator…" value={search} onChange={setSearch} />
            </div>
            <Table
              aria-label="Bảng job audit"
              size="sm"
              selectionMode="single"
              selectionBehavior="replace"
              selectedKeys={selected ? [selected.id] : []}
              onSelectionChange={(keys) => keys !== 'all' && keys.size && setSelectedId(Number([...keys][0]))}
            >
              <Table.Header>
                <Table.Head id="job" label="Job" isRowHeader />
                <Table.Head id="annotator" label="Annotator" />
                <Table.Head id="sample" label="Mẫu audit" />
                <Table.Head id="result" label="Kết quả" />
                <Table.Head id="actions" label="Thao tác" />
              </Table.Header>
              <Table.Body items={samples} renderEmptyState={() => (
                <EmptyRow text={isLoading ? 'Đang tải…' : result === 'pending' ? 'Không có mẫu nào chờ bạn audit' : 'Không có mẫu nào'} />
              )}>
                {(s) => (
                  <Table.Row id={s.id} className="cursor-pointer">
                    <Table.Cell>
                      <div className="font-medium text-primary">{s.job.name}</div>
                      <div className="text-xs text-tertiary">{s.job.dataset_name} / {s.job.batch_name}</div>
                    </Table.Cell>
                    <Table.Cell>{s.job.annotator?.full_name ?? '—'}</Table.Cell>
                    <Table.Cell>
                      <div className="text-secondary tabular-nums">{s.frames.length}/{s.job.frame_count} frame</div>
                      {s.rework_round > 0 && <div className="text-xs text-tertiary">vòng rework {s.rework_round}</div>}
                    </Table.Cell>
                    <Table.Cell><ResultBadge result={s.result} /></Table.Cell>
                    <Table.Cell>
                      {s.result === 'pending' && s.audit_status === 'in_progress' && !conflict(s) ? (
                        <div className="flex gap-1.5">
                          <Button size="xs" color="secondary" onPress={() => quickPass(s)}>Pass</Button>
                          <Button size="xs" color="secondary-destructive" onPress={() => setSelectedId(s.id)}>Reject</Button>
                        </div>
                      ) : conflict(s) && s.result === 'pending' ? (
                        <Badge type="color" size="sm" color="warning">Bốn mắt</Badge>
                      ) : <span className="text-quaternary">—</span>}
                    </Table.Cell>
                  </Table.Row>
                )}
              </Table.Body>
            </Table>
          </SectionCard>

          <div className="xl:sticky xl:top-20 xl:col-span-2">
            {selected ? (
              <ReviewPanel key={selected.id} projectId={projectId} sample={selected} conflict={conflict(selected)} onDone={reload} />
            ) : (
              <SectionCard><PageState kind="empty" title="Chọn một job" description="Chọn job trong bảng để xem chi tiết và ghi kết quả audit." /></SectionCard>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
