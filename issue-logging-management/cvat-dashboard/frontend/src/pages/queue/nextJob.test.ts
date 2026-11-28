import { describe, expect, it } from 'vitest'
import { can } from '../../mock/policy'
import { createSeedState } from '../../mock/seed'
import type { Batch, DashboardState, Job, User } from '../../mock/types'
import { canCheckQc1, canWorkOn, nextJob, rankNextJobs } from './queueScope'

const s0 = createSeedState()
const hoursFromNow = (h: number) => new Date(new Date(s0.now).getTime() + h * 3_600_000).toISOString()

/** Dựng state có kiểm soát: 5 batch riêng (không hạn, không khoá, ★ cho trước) + job đang làm của một annotator. */
function scenario() {
  const anno = s0.users.find((u) => u.role === 'annotator' && !u.isQc)!
  const base = s0.batches[0]
  const batches: Batch[] = [1, 2, 3, 4, 5].map((n) => ({ ...base, id: `tb${n}`, name: `TB${n}`, dueAt: null, autoLockAt: null, priority: n as 1 | 2 | 3 | 4 | 5 }))
  batches[4] = { ...batches[4], autoLockAt: hoursFromNow(-1) } // tb5 ★5 nhưng đã khoá
  const tpl = s0.jobs[0]
  const mk = (id: string, cvatJobId: number, batchId: string, due?: string, over: Partial<Job> = {}): Job => ({
    ...tpl, id, cvatJobId, batchId, annotatorId: anno.id, stage: 'anno_in_progress', due: due ? { annotate: due } : undefined, ...over,
  })
  const jobs: Job[] = [
    mk('free-p1', 11, 'tb1'),
    mk('free-p4', 12, 'tb4'),
    mk('soon', 13, 'tb1', hoursFromNow(5)),
    mk('late-p1', 14, 'tb1', hoursFromNow(-30)),
    mk('late-p3', 15, 'tb3', hoursFromNow(-2)),
    mk('locked-late', 16, 'tb5', hoursFromNow(-50)),
    mk('other-user', 17, 'tb4', hoursFromNow(-60), { annotatorId: 'someone-else' }),
  ]
  const s: DashboardState = { ...s0, batches, jobs }
  return { s, anno, jobs }
}

describe('job tiếp theo (W1-A)', () => {
  it('trễ → sắp trễ → còn lại; cùng mức thì ★ cao trước; bỏ job khoá / không phải việc của mình', () => {
    const { s, anno, jobs } = scenario()
    expect(rankNextJobs(s, anno, jobs).map((j) => j.id)).toEqual(['late-p3', 'late-p1', 'soon', 'free-p4', 'free-p1'])
    expect(nextJob(s, anno, jobs)?.id).toBe('late-p3')
  })

  it('cùng mức và cùng ★ ⇒ ít giờ còn lại trước, không hạn sau cùng', () => {
    const { s, anno } = scenario()
    const t = s.jobs[0]
    const jobs = [
      { ...t, id: 'a', cvatJobId: 1, batchId: 'tb2', annotatorId: anno.id, stage: 'anno_in_progress' as const, due: undefined },
      { ...t, id: 'b', cvatJobId: 2, batchId: 'tb2', annotatorId: anno.id, stage: 'anno_in_progress' as const, due: { annotate: hoursFromNow(200) } },
      { ...t, id: 'c', cvatJobId: 3, batchId: 'tb2', annotatorId: anno.id, stage: 'anno_in_progress' as const, due: { annotate: hoursFromNow(100) } },
    ]
    expect(rankNextJobs({ ...s, jobs }, anno, jobs).map((j) => j.id)).toEqual(['c', 'b', 'a'])
  })

  it('không còn job làm được ⇒ undefined', () => {
    const { s, anno, jobs } = scenario()
    expect(nextJob(s, anno, jobs.filter((j) => j.id === 'locked-late' || j.id === 'other-user'))).toBeUndefined()
  })

  it('canCheckQc1 / canWorkOn bám đúng policy `can(workJob)` (không tự quyết theo role ở UI)', () => {
    const lead = s0.users.find((u) => u.role === 'lead')!
    const qc = s0.users.find((u) => u.role === 'annotator' && u.isQc)!
    const plain: User = s0.users.find((u) => u.role === 'annotator' && !u.isQc)!
    const job: Job = { ...s0.jobs[0], stage: 'qc1_pending', teamId: lead.teamIds[0], qc1Id: qc.id }
    // Bước QC1 + thành viên team do policy `workJob qc1Pass` quyết định; UI chỉ phản ánh đúng kết quả đó.
    expect(canCheckQc1(s0, lead, job)).toBe(can(s0, lead, { kind: 'workJob', jobId: job.id, op: 'qc1Pass' }).ok)
    expect(canCheckQc1(s0, qc, job)).toBe(can(s0, qc, { kind: 'workJob', jobId: job.id, op: 'qc1Pass' }).ok)
    expect(canCheckQc1(s0, plain, { ...job, qc1Id: plain.id })).toBe(can(s0, plain, { kind: 'workJob', jobId: job.id, op: 'qc1Pass' }).ok)
    expect(canWorkOn(s0, qc, job)).toBe(can(s0, qc, { kind: 'workJob', jobId: job.id, op: 'submit' }).ok || canCheckQc1(s0, qc, job))
    // Loại bỏ trường hợp canCheckQc1 tự quyết role thay cho policy: lead phải là lead của team job.
    expect(canCheckQc1(s0, lead, { ...job, teamId: 'khac' })).toBe(can(s0, lead, { kind: 'workJob', jobId: job.id, op: 'qc1Pass' }).ok)
  })
})
