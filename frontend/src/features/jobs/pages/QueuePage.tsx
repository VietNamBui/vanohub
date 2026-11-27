import { InfoCircle } from '@untitledui/icons'
import { Link, useSearchParams } from 'react-router'
import { Tabs } from '@/components/application/tabs/tabs'
import type { BadgeColors } from '@/components/base/badges/badge-types'
import { Badge } from '@/components/base/badges/badges'
import { Select, type SelectItemType } from '@/components/base/select/select'
import { getErrorMessage } from '../../../shared/api/errors'
import StateView from '../../../shared/components/StateView'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useRequest } from '../../../shared/hooks/useRequest'
import { listBatches } from '../../projects/api'
import { useProject } from '../../projects/projectContext'
import { getJobQueue } from '../api'
import { JOB_STATUS_LABELS, STAGE_LABELS } from '../constants'
import { buildQueueJobsUrl, parseQueueUrlParams } from '../jobHelpers'
import type { JobStatus, QueueStage } from '../types'

type QueueStageFilter = '' | QueueStage['stage']

const ALL_BATCHES = '__all__'
const ALL_STAGE_TAB = 'all'

const STAGE_TABS: { id: string; label: string }[] = [
  { id: ALL_STAGE_TAB, label: 'Tất cả stage' },
  { id: 'annotation', label: STAGE_LABELS.annotation },
  { id: 'qc1', label: STAGE_LABELS.qc1 },
  { id: 'qc2', label: STAGE_LABELS.qc2 },
]

const STATUS_BADGE_COLORS: Record<JobStatus, BadgeColors> = {
  pending_annotation: 'gray',
  annotating: 'blue',
  pending_qc1: 'warning',
  qc1_reviewing: 'warning',
  qc1_passed: 'indigo',
  rework: 'orange',
  pending_qc2: 'purple',
  approved: 'success',
  delivered: 'sky',
}

/**
 * Data Queue — xem backlog job theo từng stage (Annotation, QC1, QC2) và chuyển thẳng sang danh sách job tương ứng.
 */
export default function QueuePage() {
  const { projectId } = useProject()
  const [searchParams, setSearchParams] = useSearchParams()
  const { batch, stage: selectedStage } = parseQueueUrlParams(searchParams)

  const { data, error, isLoading, retry } = useRequest(`queue:${projectId}:${batch ?? ''}`, () =>
    getJobQueue(projectId, batch),
  )
  const { data: batches } = useRequest(`batches:${projectId}`, () => listBatches(projectId))

  function updateQuery(patch: { batch?: number; stage?: QueueStageFilter }) {
    const nextBatch = 'batch' in patch ? patch.batch : batch
    const nextStage = 'stage' in patch ? patch.stage : selectedStage
    const params = new URLSearchParams()
    if (nextStage) params.set('stage', nextStage)
    if (nextBatch) params.set('batch', String(nextBatch))
    setSearchParams(params, { replace: true })
  }

  const jobsUrl = (extra: Record<string, string | number | undefined>) => buildQueueJobsUrl(batch, extra)

  const batchItems: SelectItemType[] = [
    { id: ALL_BATCHES, label: 'Tất cả task' },
    ...(batches ?? []).map((b) => ({ id: String(b.id), label: b.name })),
  ]

  const visibleStages = data
    ? selectedStage
      ? data.stages.filter((s) => s.stage === selectedStage)
      : data.stages
    : []

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Data Queue</h1>
          <p className="mt-1 text-sm text-tertiary">Backlog theo từng stage. Bấm số liệu để mở danh sách job tương ứng.</p>
        </div>
        <Select
          className="w-56"
          size="sm"
          aria-label="Lọc theo task"
          placeholder="Tất cả task"
          items={batchItems}
          selectedKey={batch != null ? String(batch) : ALL_BATCHES}
          onSelectionChange={(key) => {
            const nextBatch = key === ALL_BATCHES || key == null ? undefined : Number(key)
            updateQuery({ batch: nextBatch })
          }}
        >
          {(item) => <Select.Item id={item.id} label={item.label} />}
        </Select>
      </header>

      <div className="flex items-start gap-3 rounded-xl bg-brand-primary_alt p-4 ring-1 ring-brand ring-inset">
        <InfoCircle className="mt-0.5 size-5 shrink-0 text-fg-brand-primary" aria-hidden="true" />
        <p className="text-sm text-secondary">
          Hiện PM giao việc thủ công ở trang Jobs / Tải công việc; Annotator có thể tự nhận việc từ hàng chờ trong giới hạn WIP.
        </p>
      </div>

      <Tabs
        selectedKey={selectedStage || ALL_STAGE_TAB}
        onSelectionChange={(key) => updateQuery({ stage: key === ALL_STAGE_TAB ? '' : (key as QueueStageFilter) })}
      >
        <Tabs.List type="underline" size="sm" aria-label="Lọc theo stage" className="gap-6">
          {STAGE_TABS.map((t) => (
            <Tabs.Item key={t.id} id={t.id} label={t.label} />
          ))}
        </Tabs.List>
      </Tabs>

      {isLoading && <StateView kind="loading" />}
      {error != null && (
        <StateView kind="error" description={getErrorMessage(error)} action={{ label: 'Thử lại', onClick: retry }} />
      )}

      {data && (
        <>
          <div className={selectedStage ? 'grid grid-cols-1 gap-4' : 'grid grid-cols-1 gap-4 lg:grid-cols-3'}>
            {visibleStages.map((stage) => (
              <SectionCard key={stage.stage} title={`Hàng đợi ${STAGE_LABELS[stage.stage]}`}>
                <div>
                  <div className="text-xs font-medium text-tertiary">Job đang ở stage</div>
                  <div className="mt-1 text-display-sm font-semibold text-primary tabular-nums">{stage.total}</div>
                </div>

                <dl className="mt-4 divide-y divide-secondary rounded-xl border border-secondary bg-secondary_subtle text-sm">
                  {stage.stage !== 'qc2' && (
                    <div className="flex items-center justify-between px-3.5 py-2.5">
                      <dt className="text-tertiary">
                        {stage.stage === 'annotation' ? 'Chưa có annotator' : 'Chưa có người QC1'}
                      </dt>
                      <dd className="font-semibold text-primary tabular-nums">{stage.unassigned}</dd>
                    </div>
                  )}
                  {stage.stage === 'annotation' && (
                    <div className="flex items-center justify-between px-3.5 py-2.5">
                      <dt className="text-tertiary">Rework</dt>
                      <dd className="font-semibold text-primary tabular-nums">{stage.rework}</dd>
                    </div>
                  )}
                  <div className="flex items-center justify-between px-3.5 py-2.5">
                    <dt className="text-tertiary">Escalated</dt>
                    <dd className="font-semibold text-primary tabular-nums">{stage.escalated}</dd>
                  </div>
                  <div className="flex items-center justify-between px-3.5 py-2.5">
                    <dt className="text-tertiary">Quá hạn</dt>
                    <dd className="font-semibold text-primary tabular-nums">{stage.overdue}</dd>
                  </div>
                  <div className="flex items-center justify-between px-3.5 py-2.5">
                    <dt className="text-tertiary">Đang khoá</dt>
                    <dd className="font-semibold text-primary tabular-nums">{stage.locked}</dd>
                  </div>
                </dl>

                <div className="mt-4 flex flex-wrap gap-1.5">
                  {Object.entries(stage.by_status).map(([status, n]) => (
                    <Link
                      key={status}
                      to={jobsUrl({ stage: stage.stage, status })}
                      relative="path"
                      className="transition hover:opacity-80"
                    >
                      <Badge type="pill-color" size="sm" color={STATUS_BADGE_COLORS[status as JobStatus] ?? 'gray'}>
                        {JOB_STATUS_LABELS[status as JobStatus] ?? status}: {n}
                      </Badge>
                    </Link>
                  ))}
                </div>

                <div className="mt-4 border-t border-secondary pt-3">
                  <Link
                    to={jobsUrl({ stage: stage.stage })}
                    relative="path"
                    className="text-sm font-semibold text-brand-secondary hover:underline"
                  >
                    Xem danh sách job →
                  </Link>
                </div>
              </SectionCard>
            ))}
          </div>

          <SectionCard>
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <div className="text-xs font-medium text-tertiary">Job đã hoàn tất (Đã duyệt / Đã bàn giao)</div>
                <div className="mt-1 flex items-baseline gap-1.5">
                  <span className="text-display-sm font-semibold text-primary tabular-nums">{data.done}</span>
                  <span className="text-sm font-medium text-tertiary tabular-nums">/ {data.total}</span>
                </div>
              </div>
              <Link
                to={jobsUrl({ stage: 'done' })}
                relative="path"
                className="text-sm font-semibold text-brand-secondary hover:underline"
              >
                Xem job hoàn tất →
              </Link>
            </div>
          </SectionCard>
        </>
      )}
    </div>
  )
}
