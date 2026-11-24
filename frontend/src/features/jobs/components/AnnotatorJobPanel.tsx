import { AlertTriangle, LinkExternal01 } from '@untitledui/icons'
import { useState } from 'react'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { Input } from '@/components/base/input/input'
import { TextArea } from '@/components/base/textarea/textarea'
import { getErrorMessage } from '../../../shared/api/errors'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import { SEVERITY_LABELS } from '../../quality/constants'
import type { Severity } from '../../quality/types'
import { getAnnotatorJob, startAnnotatorJob, submitAnnotatorJob } from '../api'
import { ACTION_LABELS, JOB_STATUS_LABELS } from '../constants'
import type { JobDetail, JobStatus } from '../types'
import JobStatusBadge from './JobStatusBadge'

const SEVERITY_BADGE_COLORS: Record<string, 'gray' | 'warning' | 'error'> = {
  minor: 'gray',
  major: 'warning',
  critical: 'error',
}

interface Props {
  projectId: number
  jobId: number
  version: number
  onDone: () => void
}

/** Khung chi tiết job của Annotator: mở CVAT, bắt đầu làm / nộp bài, xem lỗi cần sửa và dòng thời gian. */
export default function AnnotatorJobPanel({ projectId, jobId, version, onDone }: Props) {
  const { data: job, error, isLoading, retry } = useRequest(`annotator-job:${projectId}:${jobId}:${version}`, () =>
    getAnnotatorJob(projectId, jobId),
  )

  if (error != null) return <SectionCard><PageState kind="error" description={getErrorMessage(error)} onRetry={retry} /></SectionCard>
  if (isLoading || !job) return <SectionCard><PageState kind="loading" /></SectionCard>

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
          <Info label="Người QC1" value={job.qc1_reviewer?.full_name ?? 'Chưa phân công'} />
          <Info label="Deadline" value={formatDateTime(job.deadline)} />
          <Info label="Object / frame" value={`${job.object_count} / ${job.frame_count}`} />
          <Info label="Vòng rework" value={`${job.rework_round} / ${job.max_rework_rounds}`} />
        </dl>

        <ActionSection key={`${job.id}:${job.status}:${job.updated_at}`} projectId={projectId} job={job} onDone={onDone} />

        <section className="border-t border-secondary pt-4">
          <h3 className="mb-2 text-sm font-semibold text-primary">
            Lỗi cần sửa / Lịch sử lỗi <span className="font-normal text-tertiary">({job.errors.length})</span>
          </h3>
          {job.errors.length === 0 ? (
            <p className="text-sm text-tertiary">Chưa có lỗi nào được ghi nhận.</p>
          ) : (
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
                  <p className="mt-1 text-xs text-quaternary">
                    {e.reported_by?.full_name ?? 'Hệ thống'} · {formatDateTime(e.created_at)}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="border-t border-secondary pt-4">
          <h3 className="mb-2 text-sm font-semibold text-primary">Dòng thời gian</h3>
          {job.timeline.length === 0 ? (
            <p className="text-sm text-tertiary">Chưa có hoạt động nào.</p>
          ) : (
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
          )}
        </section>
      </div>
    </SectionCard>
  )
}

function ActionSection({ projectId, job, onDone }: { projectId: number; job: JobDetail; onDone: () => void }) {
  const { run, pending } = useAction()
  const [note, setNote] = useState('')
  const [objectCount, setObjectCount] = useState(job.object_count > 0 ? String(job.object_count) : '')
  const [countError, setCountError] = useState<string | undefined>()

  if (job.is_locked) {
    return <Notice text="Job đang bị khoá — không thể thay đổi trạng thái." />
  }
  if (job.is_escalated) {
    return <Notice text="Job đang ở trạng thái Escalated (vượt số vòng rework), vui lòng chờ PM xử lý." />
  }

  if (job.status === 'pending_annotation' || job.status === 'rework') {
    const isRework = job.status === 'rework'
    return (
      <div className="flex flex-col gap-3 border-t border-secondary pt-4">
        <TextArea
          label="Ghi chú (không bắt buộc)"
          placeholder={isRework ? 'Ghi chú trước khi sửa lỗi…' : 'Ghi chú khi bắt đầu…'}
          rows={2}
          value={note}
          onChange={setNote}
        />
        <div className="flex justify-end">
          <Button
            color="primary"
            isLoading={pending}
            onPress={async () => {
              const ok = await run(
                () => startAnnotatorJob(projectId, job.id, note.trim()),
                isRework ? `Đã bắt đầu sửa Rework ${job.name}` : `Đã bắt đầu làm ${job.name}`,
              )
              if (ok) onDone()
            }}
          >
            {isRework ? 'Bắt đầu sửa Rework' : 'Bắt đầu gán nhãn'}
          </Button>
        </div>
      </div>
    )
  }

  if (job.status === 'annotating') {
    async function submit() {
      const trimmed = objectCount.trim()
      let parsed: number | undefined
      if (trimmed !== '') {
        if (!/^\d+$/.test(trimmed)) {
          setCountError('Số object phải là số nguyên không âm.')
          return
        }
        parsed = Number(trimmed)
      }
      setCountError(undefined)
      const ok = await run(
        () => submitAnnotatorJob(projectId, job.id, { note: note.trim(), ...(parsed !== undefined ? { object_count: parsed } : {}) }),
        `Đã nộp ${job.name} sang hàng chờ QC1`,
      )
      if (ok) onDone()
    }

    return (
      <div className="flex flex-col gap-3 border-t border-secondary pt-4">
        <Input
          label="Số object đã gán (không bắt buộc)"
          size="sm"
          placeholder="Để trống để giữ nguyên"
          value={objectCount}
          isInvalid={!!countError}
          hint={countError}
          onChange={(v) => {
            setObjectCount(v)
            if (countError) setCountError(undefined)
          }}
        />
        <TextArea label="Ghi chú nộp bài (không bắt buộc)" placeholder="Nhập ghi chú cho QC1…" rows={2} value={note} onChange={setNote} />
        <div className="flex justify-end">
          <Button color="primary" isLoading={pending} onPress={submit}>
            Nộp bài sang QC1
          </Button>
        </div>
      </div>
    )
  }

  return (
    <p className="rounded-lg bg-secondary p-3 text-sm text-tertiary">
      {job.status === 'approved' || job.status === 'delivered'
        ? 'Job đã hoàn tất kiểm duyệt.'
        : 'Job đã nộp và đang chờ QC kiểm tra.'}
    </p>
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
