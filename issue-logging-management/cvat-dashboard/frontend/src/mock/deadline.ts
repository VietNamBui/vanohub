import type { Batch, DashboardState, DeadlineStatus, Job, JobEvent, JobStage, WorkStep } from './types'

/**
 * Selector hạn (I1: nguồn duy nhất tính hạn). Hàm thuần; "bây giờ" = `s.now` (CẤM Date.now()).
 * Không import `selectors.ts` (selectors re-export file này) để tránh vòng phụ thuộc.
 */

export const DUE_SOON_HOURS = 24
const HOUR_MS = 3_600_000
const DAY_MS = 24 * HOUR_MS

type S = Pick<DashboardState, 'now' | 'batches' | 'jobs' | 'events'>

/** Bước đang chịu hạn của job, theo stage. */
export function stepOfStage(stage: JobStage): WorkStep | null {
  switch (stage) {
    case 'team_pool':
    case 'anno_in_progress':
      return 'annotate'
    case 'qc1_pending':
    case 'qc1_in_progress':
      return 'qc1'
    case 'qc2_pending':
    case 'qc2_in_progress':
      return 'qc2'
    default:
      return null
  }
}

/** Hạn mặc định của bước từ batch: qc2 = dueAt; qc1 = dueAt − buffer.qc2; annotate = dueAt − buffer.qc2 − buffer.qc1 (ngày). */
export function defaultStepDue(batch: Batch, step: WorkStep): string | null {
  if (!batch.dueAt) return null
  const due = new Date(batch.dueAt).getTime()
  if (Number.isNaN(due)) return null
  const { qc1, qc2 } = batch.stepBufferDays
  const back = step === 'qc2' ? 0 : step === 'qc1' ? qc2 : qc2 + qc1
  return new Date(due - back * DAY_MS).toISOString()
}

export interface EffectiveDue { step: WorkStep; dueAt: string; source: 'job' | 'batch' }

/** Hạn hiệu lực của một bước (I3): ghi đè của job thắng mặc định từ batch. */
export function stepDue(s: Pick<S, 'batches'>, job: Job, step: WorkStep): EffectiveDue | null {
  const own = job.due?.[step]
  if (own) return { step, dueAt: own, source: 'job' }
  const batch = s.batches.find((b) => b.id === job.batchId)
  const def = batch ? defaultStepDue(batch, step) : null
  return def ? { step, dueAt: def, source: 'batch' } : null
}

/** Hạn của bước hiện tại; null nếu stage không chịu hạn hoặc không có hạn. */
export function jobDeadline(s: Pick<S, 'batches'>, job: Job): EffectiveDue | null {
  const step = stepOfStage(job.stage)
  return step ? stepDue(s, job, step) : null
}

/** Số giờ còn lại tới hạn của bước hiện tại (âm khi trễ); null khi không có hạn. */
export function hoursLeft(s: Pick<S, 'now' | 'batches'>, job: Job): number | null {
  const d = jobDeadline(s, job)
  if (!d) return null
  return (new Date(d.dueAt).getTime() - new Date(s.now).getTime()) / HOUR_MS
}

export function deadlineStatus(s: Pick<S, 'now' | 'batches'>, job: Job): DeadlineStatus {
  const d = jobDeadline(s, job)
  if (!d) return 'none'
  const diff = new Date(d.dueAt).getTime() - new Date(s.now).getTime()
  if (diff <= 0) return 'overdue'
  if (diff < DUE_SOON_HOURS * HOUR_MS) return 'due_soon'
  return 'on_track'
}

// ---------- đúng hạn (bảng D)
export interface OnTimeStats { total: number; onTime: number; late: number; rate: number }
export interface OnTimeFilter {
  userIds?: string[]; teamId?: string; projectId?: string; batchId?: string; from?: string; to?: string; step?: WorkStep
}

/** Đầu/cuối khoảng lọc: 'YYYY-MM-DD' (to tính hết ngày) hoặc ISO. */
function rangeMs(f: OnTimeFilter): [number, number] {
  const day = /^\d{4}-\d{2}-\d{2}$/
  const lo = f.from ? (day.test(f.from) ? new Date(`${f.from}T00:00:00.000Z`).getTime() : new Date(f.from).getTime()) : -Infinity
  const hi = f.to ? (day.test(f.to) ? new Date(`${f.to}T00:00:00.000Z`).getTime() + DAY_MS - 1 : new Date(f.to).getTime()) : Infinity
  return [lo, hi]
}

/** Sự kiện đánh dấu hoàn thành mỗi bước của một job (bảng D). */
function completionEvent(evs: JobEvent[], step: WorkStep): JobEvent | undefined {
  if (step === 'annotate') return evs.find((e) => e.type === 'submit')
  const type = step === 'qc1' ? 'qc1_pass' : 'qc2_pass'
  return [...evs].reverse().find((e) => e.type === type)
}

export function onTimeStats(s: S, f: OnTimeFilter = {}): OnTimeStats {
  const [lo, hi] = rangeMs(f)
  const steps: WorkStep[] = f.step ? [f.step] : ['annotate', 'qc1', 'qc2']
  const byJob = new Map<string, JobEvent[]>()
  for (const e of s.events) {
    const arr = byJob.get(e.jobId)
    if (arr) arr.push(e); else byJob.set(e.jobId, [e])
  }
  let total = 0
  let late = 0
  for (const job of s.jobs) {
    if (f.teamId && job.teamId !== f.teamId) continue
    if (f.projectId && job.projectId !== f.projectId) continue
    if (f.batchId && job.batchId !== f.batchId) continue
    const evs = (byJob.get(job.id) ?? []).slice().sort((a, b) => a.at.localeCompare(b.at) || a.id.localeCompare(b.id))
    for (const step of steps) {
      const ev = completionEvent(evs, step)
      if (!ev) continue
      if (f.userIds && !f.userIds.includes(ev.actorId)) continue
      const at = new Date(ev.at).getTime()
      if (at < lo || at > hi) continue
      const due = stepDue(s, job, step)
      if (!due) continue
      total += 1
      if (at > new Date(due.dueAt).getTime()) late += 1
    }
  }
  const onTime = total - late
  return { total, onTime, late, rate: total === 0 ? 1 : onTime / total }
}

// ---------- dự báo batch
export interface BatchForecast {
  dueAt: string | null
  remainingJobs: number
  /** Job vào ready_to_deliver trong 7 ngày gần nhất / 7. */
  throughputPerDay: number
  etaAt: string | null
  verdict: 'no_due' | 'done' | 'on_track' | 'at_risk' | 'late'
  daysLate: number
}

export function batchForecast(s: S, batchId: string): BatchForecast {
  const batch = s.batches.find((b) => b.id === batchId)
  const dueAt = batch?.dueAt ?? null
  const now = new Date(s.now).getTime()
  const jobs = s.jobs.filter((j) => j.batchId === batchId)
  const ids = new Set(jobs.map((j) => j.id))
  const remainingJobs = jobs.filter((j) => j.stage !== 'ready_to_deliver' && j.stage !== 'delivered').length
  const since = now - 7 * DAY_MS
  const arrived = s.events.filter((e) => ids.has(e.jobId) && e.toStage === 'ready_to_deliver' && e.fromStage !== 'ready_to_deliver'
    && new Date(e.at).getTime() > since && new Date(e.at).getTime() <= now).length
  const throughputPerDay = arrived / 7
  const etaMs = remainingJobs > 0 && throughputPerDay > 0 ? now + (remainingJobs / throughputPerDay) * DAY_MS : null
  const etaAt = etaMs === null ? null : new Date(etaMs).toISOString()
  const base = { dueAt, remainingJobs, throughputPerDay, etaAt }
  if (!dueAt) return { ...base, verdict: 'no_due', daysLate: 0 }
  if (remainingJobs === 0) return { ...base, verdict: 'done', daysLate: 0 }
  const due = new Date(dueAt).getTime()
  const isLate = now > due
  const lateRef = Math.max(etaMs ?? now, now)
  const daysLate = isLate || (etaMs !== null && etaMs > due) ? Math.max(0, Math.ceil((lateRef - due) / DAY_MS)) : 0
  if (isLate) return { ...base, verdict: 'late', daysLate }
  if (etaMs === null || etaMs > due) return { ...base, verdict: 'at_risk', daysLate }
  return { ...base, verdict: 'on_track', daysLate: 0 }
}

// ---------- job trễ
export interface OverdueScope { userId?: string; teamId?: string; projectId?: string; batchIds?: string[] }

/** Người chịu trách nhiệm bước hiện tại của job. */
function responsibleOf(job: Job): string | null {
  switch (stepOfStage(job.stage)) {
    case 'annotate': return job.annotatorId
    case 'qc1': return job.qc1Id
    case 'qc2': return job.qc2Id
    default: return null
  }
}

/** Job đang trễ hạn bước hiện tại, trễ nhất trước. */
export function overdueJobs(s: Pick<S, 'now' | 'batches' | 'jobs'>, scope: OverdueScope = {}): Job[] {
  const rows: { job: Job; left: number }[] = []
  for (const job of s.jobs) {
    if (scope.teamId && job.teamId !== scope.teamId) continue
    if (scope.projectId && job.projectId !== scope.projectId) continue
    if (scope.batchIds && !scope.batchIds.includes(job.batchId)) continue
    if (scope.userId && responsibleOf(job) !== scope.userId) continue
    if (deadlineStatus(s, job) !== 'overdue') continue
    rows.push({ job, left: hoursLeft(s, job)! })
  }
  return rows.sort((a, b) => a.left - b.left || a.job.id.localeCompare(b.job.id)).map((r) => r.job)
}
