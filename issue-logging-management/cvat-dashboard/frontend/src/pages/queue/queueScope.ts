import { deadlineStatus, hoursLeft, jobsOfBatch, visibleBatches, visibleProjects } from '../../mock/selectors'
import { isBatchLocked } from '../../mock/logic'
import { can } from '../../mock/policy'
import type { DeadlineStatus, DashboardState, Batch, Job, Project, Role, User } from '../../mock/types'

/** Cấp gốc của Hàng đợi theo vai: admin/pm bắt đầu ở Dự án, lead ở Batch, annotator ở Job. */
export type QueueEntry = 'projects' | 'batches' | 'jobs'
export const queueEntry = (role: Role): QueueEntry => (role === 'lead' ? 'batches' : role === 'annotator' ? 'jobs' : 'projects')

/**
 * Cấp URL: 0 = /queue, 1 = /:p, 2 = /:p/:d, 3 = /:p/:d/:b.
 * Lead chỉ được vào cấp 0 và 3; annotator chỉ cấp 0; admin/pm cả 4 cấp.
 */
export function levelAllowed(role: Role, level: number): boolean {
  if (role === 'annotator') return level === 0
  if (role === 'lead') return level === 0 || level === 3
  return true
}

/** Dự án hiển thị ở gốc của admin/pm (admin tất cả, pm chỉ dự án được giao). */
export const rootProjects = (s: DashboardState, user: User): Project[] => (queueEntry(user.role) === 'projects' ? visibleProjects(s, user) : [])

/** Batch ở gốc của lead: batch có job của team mình, bỏ batch đã released. */
export const leadBatches = (s: DashboardState, user: User): Batch[] =>
  (user.role === 'lead' ? visibleBatches(s, user).filter((b) => b.status !== 'released') : [])

/** Job được giao cho annotator: là người làm, hoặc là QC1 khi user.isQc. */
export const assignedJobs = (s: DashboardState, user: User): Job[] =>
  (user.role === 'annotator' ? s.jobs.filter((j) => j.annotatorId === user.id || (user.isQc && j.qc1Id === user.id)) : [])

/** Job của một batch thuộc phạm vi của lead (chỉ job của team mình). */
export const leadJobsOfBatch = (s: DashboardState, user: User, batchId: string): Job[] =>
  jobsOfBatch(s, batchId).filter((j) => j.teamId !== null && user.teamIds.includes(j.teamId))

/** Được Check QC1: policy `workJob qc1Pass` quyết định (gồm bước QC1 và thành viên team). */
export const canCheckQc1 = (s: DashboardState, user: User, job: Job): boolean =>
  can(s, user, { kind: 'workJob', jobId: job.id, op: 'qc1Pass' }).ok

/** Job user làm được ngay: annotator — submit job của mình đang làm; QC1 — check (qc1Pass). */
export const canWorkOn = (s: DashboardState, user: User, job: Job): boolean =>
  can(s, user, { kind: 'workJob', jobId: job.id, op: 'submit' }).ok || canCheckQc1(s, user, job)

const URGENCY: Record<DeadlineStatus, number> = { overdue: 0, due_soon: 1, on_track: 2, none: 2 }

/**
 * Thứ tự "job tiếp theo": chỉ job user làm được ngay và batch chưa khoá;
 * trễ → sắp trễ → còn lại, cùng mức thì batch ★ cao trước, rồi ít giờ còn lại trước (không hạn cuối), rồi CVAT job id.
 */
export function rankNextJobs(s: DashboardState, user: User, jobs: Job[]): Job[] {
  const prio = (j: Job) => s.batches.find((b) => b.id === j.batchId)?.priority ?? 0
  const locked = (j: Job) => { const b = s.batches.find((x) => x.id === j.batchId); return !!b && isBatchLocked(s, b) }
  const key = (j: Job) => ({ u: URGENCY[deadlineStatus(s, j)], p: prio(j), h: hoursLeft(s, j) ?? Infinity })
  return jobs
    .filter((j) => canWorkOn(s, user, j) && !locked(j))
    .map((j) => ({ j, k: key(j) }))
    .sort((a, b) => a.k.u - b.k.u || b.k.p - a.k.p || a.k.h - b.k.h || a.j.cvatJobId - b.j.cvatJobId)
    .map((x) => x.j)
}

export const nextJob = (s: DashboardState, user: User, jobs: Job[]): Job | undefined => rankNextJobs(s, user, jobs)[0]
