import { LinkExternal01, XClose } from '@untitledui/icons'
import { useEffect } from 'react'
import { Link } from 'react-router'
import { Badge, BadgeWithDot } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { ProgressBarBase } from '@/components/base/progress-indicators/progress-indicators'
import { getErrorMessage } from '../../../shared/api/errors'
import PageState from '../../../shared/components/ui/PageState'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime, formatNumber } from '../../../shared/utils/format'
import { getAnnotatorJob } from '../api'
import { ACTION_LABELS, formatDeadlineCountdown, JOB_STATUS_LABELS } from '../constants'
import type { JobStatus } from '../types'
import JobStatusBadge from './JobStatusBadge'

interface Props {
  projectId: number
  jobId: number | null
  onClose: () => void
}

const SEVERITY_COLOR: Record<string, 'gray' | 'warning' | 'error'> = {
  minor: 'gray',
  major: 'warning',
  critical: 'error',
}

/** Drawer trượt phải xem nhanh chi tiết job: tiến độ, lịch sử xử lý, lỗi theo object-frame và liên kết CVAT. */
export default function AnnotatorJobDrawer({ projectId, jobId, onClose }: Props) {
  const { data: job, error, isLoading, retry } = useRequest(
    jobId ? `annotator-job-drawer:${projectId}:${jobId}` : 'annotator-job-drawer:none',
    () => (jobId ? getAnnotatorJob(projectId, jobId) : Promise.resolve(null)),
  )

  useEffect(() => {
    if (!jobId) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [jobId, onClose])

  if (!jobId) return null

  const countdown = formatDeadlineCountdown(job?.hours_remaining)
  const volume = job ? job.target_object_count || job.object_count : 0
  const progressPct = job?.progress_percent ?? 0

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label={job?.name ?? 'Chi tiết Job'}>
      <div className="fixed inset-0 bg-overlay/70 backdrop-blur-[2px]" onClick={onClose} />

      <aside className="relative z-10 flex h-full w-full max-w-[560px] flex-col border-l border-secondary bg-primary shadow-2xl">
        <div className="flex items-center justify-between gap-3 border-b border-secondary px-6 py-5">
          <div className="flex flex-wrap items-center gap-2.5">
            <h2 className="text-lg font-semibold text-primary">{job?.name ?? 'Chi tiết job'}</h2>
            {job && (
              <>
                <JobStatusBadge
                  status={job.status}
                  escalated={job.is_escalated}
                  overdue={job.is_overdue}
                  locked={job.is_locked}
                />
                {job.rework_round > 0 && (
                  <Badge size="sm" type="pill-color" color="warning">
                    Vòng sửa {job.rework_round}/{job.max_rework_rounds}
                  </Badge>
                )}
              </>
            )}
          </div>
          <Button color="tertiary" size="sm" iconLeading={XClose} aria-label="Đóng" onPress={onClose} />
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {isLoading ? (
            <PageState kind="loading" />
          ) : error != null ? (
            <PageState kind="error" description={getErrorMessage(error)} onRetry={retry} />
          ) : job ? (
            <div className="flex flex-col gap-6">
              <dl className="grid grid-cols-2 gap-x-6 gap-y-4">
                <MetaField label="Project" value={job.dataset_name} />
                <MetaField label="Task" value={job.batch_name ?? '—'} />
                <MetaField label="Người đang giữ" value={job.annotator ? `${job.annotator.full_name} (Annotator)` : 'Chưa giao'} />
                <MetaField
                  label="Deadline"
                  value={
                    job.deadline
                      ? `${formatDateTime(job.deadline)}${countdown ? ` · ${countdown.text.toLowerCase()}` : ''}`
                      : 'Chưa đặt'
                  }
                />
                <MetaField label="Khối lượng" value={`${formatNumber(volume)} object-frame`} />
                <div>
                  <dt className="text-xs text-tertiary">Tiến độ gán nhãn</dt>
                  <dd className="mt-1 flex items-center gap-2.5">
                    <ProgressBarBase value={progressPct} />
                    <span className="shrink-0 text-xs font-semibold text-secondary tabular-nums">{progressPct}%</span>
                  </dd>
                </div>
              </dl>

              <section className="border-t border-secondary pt-5">
                <h3 className="text-sm font-semibold text-primary">Lịch sử xử lý</h3>
                {job.timeline.length === 0 ? (
                  <p className="mt-2 text-sm text-tertiary">Chưa có lịch sử xử lý.</p>
                ) : (
                  <ol className="mt-4 flex flex-col">
                    {job.timeline.map((ev, i) => {
                      const nextStatus = ev.after?.status as JobStatus | undefined
                      const isLatest = i === job.timeline.length - 1
                      return (
                        <li key={ev.id} className="relative flex gap-3 pb-5 last:pb-0">
                          {i < job.timeline.length - 1 && (
                            <span className="absolute top-3.5 bottom-0 left-[6px] w-px bg-border-secondary" />
                          )}
                          <span
                            className={`mt-1 size-3.5 shrink-0 rounded-full ${
                              isLatest ? 'border border-primary bg-primary' : 'bg-brand-solid'
                            }`}
                          />
                          <div className="min-w-0">
                            <p className="text-sm font-medium text-primary">
                              {ACTION_LABELS[ev.action] ?? ev.action}
                              {nextStatus ? ` → ${JOB_STATUS_LABELS[nextStatus] ?? nextStatus}` : ''}
                            </p>
                            <p className="text-xs text-tertiary">
                              {ev.actor?.full_name ?? 'Hệ thống'} · {formatDateTime(ev.created_at)}
                            </p>
                            {ev.note && <p className="mt-0.5 text-xs text-secondary">{ev.note}</p>}
                          </div>
                        </li>
                      )
                    })}
                  </ol>
                )}
              </section>

              <section className="border-t border-secondary pt-5">
                <h3 className="text-sm font-semibold text-primary">Lỗi đã ghi theo object-frame</h3>
                {job.errors.length === 0 ? (
                  <p className="mt-2 text-sm text-tertiary">Chưa có lỗi nào được ghi nhận.</p>
                ) : (
                  <ul className="mt-3 flex flex-col gap-2.5">
                    {job.errors.map((e) => (
                      <li key={e.id} className="flex items-center justify-between gap-3">
                        <BadgeWithDot size="sm" type="pill-color" color={SEVERITY_COLOR[e.severity] ?? 'warning'}>
                          {e.category}
                        </BadgeWithDot>
                        <span className="text-xs text-tertiary">{e.location || `Vòng ${e.rework_round}`}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <p className="text-xs text-tertiary">
                Phạm vi xem theo vai trò · thao tác trên CVAT được ghi log.
              </p>
            </div>
          ) : null}
        </div>

        <footer className="flex items-center justify-between gap-3 border-t border-secondary px-6 py-4">
          <div className="flex items-center gap-2">
            <Button color="secondary" size="md" onPress={onClose}>
              Đóng
            </Button>
            {job && (
              <Link
                to={`/projects/${projectId}/annotator/jobs/${job.id}`}
                onClick={onClose}
                className="inline-flex items-center rounded-lg px-3 py-2 text-sm font-semibold text-brand-secondary transition hover:bg-brand-primary"
              >
                Mở trang chi tiết
              </Link>
            )}
          </div>
          {job?.cvat_url ? (
            <Button
              color="primary"
              size="md"
              iconLeading={LinkExternal01}
              href={job.cvat_url}
              target="_blank"
              rel="noreferrer"
            >
              Mở trên CVAT
            </Button>
          ) : (
            <Button color="primary" size="md" isDisabled>
              Chưa liên kết CVAT
            </Button>
          )}
        </footer>
      </aside>
    </div>
  )
}

function MetaField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-tertiary">{label}</dt>
      <dd className="mt-0.5 text-sm font-medium text-primary">{value}</dd>
    </div>
  )
}
