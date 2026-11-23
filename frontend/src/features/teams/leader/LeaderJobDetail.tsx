import { Calendar, LinkExternal01, UserRight01 } from '@untitledui/icons'
import { Button } from '@/components/base/buttons/button'
import { getErrorMessage } from '../../../shared/api/errors'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import JobStatusBadge from '../../jobs/components/JobStatusBadge'
import { ACTION_LABELS } from '../../jobs/constants'
import type { JobDetail, JobStatus } from '../../jobs/types'
import { getLeaderJob } from './api'
import type { LeaderDialogState } from './LeaderJobDialogs'
import { cx } from '@/utils/cx'

const STAGES: { label: string; statuses: JobStatus[] }[] = [
  { label: 'Annotate', statuses: ['pending_annotation', 'annotating'] },
  { label: 'QC1 Check', statuses: ['pending_qc1', 'qc1_reviewing'] },
  { label: 'Rework', statuses: ['rework'] },
  { label: 'QC2 Audit', statuses: ['pending_qc2'] },
  { label: 'Deliver', statuses: ['approved', 'delivered'] },
]

/** Khung chi tiết job (TL-02): thông tin, tiến độ stage, dòng thời gian, lỗi đã ghi, lịch sử deadline. */
export default function LeaderJobDetail({ projectId, jobId, version, openDialog }: {
  projectId: number
  jobId: number
  version: number
  openDialog: (state: LeaderDialogState) => void
}) {
  const { data: job, error, isLoading, retry } = useRequest(`leader-job:${projectId}:${jobId}:${version}`, () => getLeaderJob(projectId, jobId))

  if (error != null) return <SectionCard><PageState kind="error" description={getErrorMessage(error)} onRetry={retry} /></SectionCard>
  if (isLoading || !job) return <SectionCard><PageState kind="loading" /></SectionCard>

  const editable = !job.is_locked && job.status !== 'delivered'
  const deadlineHistory = job.timeline.filter((e) => e.action === 'job.deadline')

  return (
    <SectionCard
      title={job.name}
      description={`${job.dataset_name} / ${job.batch_name}`}
      actions={job.cvat_url && <Button size="sm" color="secondary" iconTrailing={LinkExternal01} href={job.cvat_url} target="_blank" rel="noreferrer">CVAT</Button>}
    >
      <div className="flex flex-col gap-5">
        <JobStatusBadge status={job.status} escalated={job.is_escalated} overdue={job.is_overdue} locked={job.is_locked} />

        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
          <Info label="Người đang giữ" value={job.annotator?.full_name ?? 'Chưa giao'} />
          <Info label="QC1" value={job.qc1_reviewer?.full_name ?? '—'} />
          <Info label="Deadline" value={formatDateTime(job.deadline)} />
          <Info label="Round rework" value={`${job.rework_round} / ${job.max_rework_rounds}`} />
          <Info label="Số cuboid" value={String(job.object_count)} />
          <Info label="Số frame" value={String(job.frame_count)} />
        </dl>

        <StageProgress status={job.status} />

        {editable ? (
          <div className="flex gap-2">
            <Button size="sm" iconLeading={UserRight01} onPress={() => openDialog({ type: 'assign', jobIds: [job.id], label: job.name })}>Giao lại</Button>
            <Button size="sm" color="secondary" iconLeading={Calendar}
              onPress={() => openDialog({ type: 'deadline', jobIds: [job.id], label: job.name, current: job.deadline })}>Đặt deadline</Button>
          </div>
        ) : <p className="text-sm text-tertiary">{job.is_locked ? 'Job đang bị PM khoá.' : 'Job đã bàn giao.'}</p>}

        <Errors job={job} />

        <section>
          <h3 className="mb-2 text-sm font-semibold text-primary">Lịch sử deadline</h3>
          {deadlineHistory.length === 0 ? <p className="text-sm text-tertiary">Chưa đổi deadline lần nào.</p> : (
            <ul className="flex flex-col gap-1.5 text-sm">
              {deadlineHistory.map((e) => (
                <li key={e.id} className="text-tertiary">
                  {formatDateTime(String(e.before?.deadline ?? '') || null)} → <span className="font-medium text-secondary">{formatDateTime(String(e.after?.deadline ?? '') || null)}</span>
                  <span className="text-quaternary"> · {e.actor?.full_name ?? 'Hệ thống'}, {formatDateTime(e.created_at)}</span>
                  {e.note && <span className="block text-xs">Lý do: {e.note}</span>}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section>
          <h3 className="mb-2 text-sm font-semibold text-primary">Dòng thời gian</h3>
          <ol className="flex flex-col">
            {job.timeline.map((e, i) => (
              <li key={e.id} className="relative flex gap-3 pb-4 last:pb-0">
                {i < job.timeline.length - 1 && <span aria-hidden className="absolute top-3 bottom-0 left-[4px] w-px bg-border-secondary" />}
                <span className="mt-1.5 size-2.5 shrink-0 rounded-full bg-brand-solid" />
                <div className="text-sm">
                  <p className="font-medium text-secondary">{ACTION_LABELS[e.action] ?? e.action}</p>
                  <p className="text-xs text-quaternary">{e.actor?.full_name ?? 'Hệ thống'} · {formatDateTime(e.created_at)}</p>
                  {e.note && <p className="text-xs text-tertiary">{e.note}</p>}
                </div>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </SectionCard>
  )
}

function StageProgress({ status }: { status: JobStatus }) {
  const current = STAGES.findIndex((s) => s.statuses.includes(status))
  return (
    <div>
      <p className="mb-2 text-xs font-medium text-quaternary">Stage hiện tại</p>
      <ol className="flex gap-1">
        {STAGES.map((s, i) => (
          <li key={s.label} className="flex-1">
            <div className={cx('h-1.5 rounded-full', i < current ? 'bg-brand-solid' : i === current ? 'bg-brand-solid_hover' : 'bg-secondary')} />
            <p className={cx('mt-1 truncate text-xs', i === current ? 'font-semibold text-brand-secondary' : 'text-quaternary')}>{s.label}</p>
          </li>
        ))}
      </ol>
      {status === 'rework' && <p className="mt-1 text-xs text-tertiary">↺ Job đang ở vòng rework, sẽ quay lại QC1 sau khi sửa.</p>}
    </div>
  )
}

function Errors({ job }: { job: JobDetail }) {
  return (
    <section>
      <h3 className="mb-2 text-sm font-semibold text-primary">Lỗi đã ghi <span className="font-normal text-tertiary">(theo Danh mục lỗi)</span></h3>
      {job.errors.length === 0 ? <p className="text-sm text-tertiary">Chưa có lỗi nào.</p> : (
        <ul className="flex flex-col gap-2">
          {job.errors.map((e) => (
            <li key={e.id} className="rounded-lg p-3 text-sm ring-1 ring-secondary ring-inset">
              <p className="font-medium text-secondary">{e.category} <span className="text-xs font-normal text-quaternary">· {e.stage.toUpperCase()} · vòng {e.rework_round}</span></p>
              {(e.location || e.description) && <p className="text-tertiary">{[e.location, e.description].filter(Boolean).join(' — ')}</p>}
            </li>
          ))}
        </ul>
      )}
    </section>
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
