import { describe, expect, it } from 'vitest'
import {
  batchForecast, deadlineStatus, defaultStepDue, hoursLeft, jobDeadline, onTimeStats, overdueJobs, stepDue, stepOfStage,
} from './deadline'
import { applyAction, type Action } from './logic'
import { createSeedState } from './seed'
import { batchHistory, eventsOfJob } from './selectors'
import type { Batch, DashboardState, Job, JobEvent, JobStage } from './types'

const NOW = '2026-11-18T09:00:00.000Z'
const H = 3_600_000
const D = 24 * H
const at = (offsetMs: number, base = NOW) => new Date(new Date(base).getTime() + offsetMs).toISOString()

const mkBatch = (patch: Partial<Batch> = {}): Batch => ({
  id: 'bx', name: 'Batch X', datasetId: 'd1', projectId: 'p1', cvatTaskId: 1, status: 'in_progress', teamId: 't1', stepPic: {}, autoLockAt: null,
  dueAt: null, stepBufferDays: { qc1: 2, qc2: 1 }, priority: 3, ...patch,
})
const mkJob = (id: string, stage: JobStage, patch: Partial<Job> = {}): Job => ({
  id, cvatJobId: 1, batchId: 'bx', projectId: 'p1', teamId: 't1', annotatorId: 'ua', qc1Id: 'uq', qc2Id: null, stage,
  prelabelCuboids: 100, editedCuboids: 0, frames: 10, reworkCount: 0, firstSubmittedAt: null, ...patch,
})
const mkEv = (jobId: string, type: JobEvent['type'], when: string, actorId: string, toStage: JobStage, fromStage: JobStage | null = null): JobEvent => ({
  id: `e-${jobId}-${type}-${when}`, jobId, at: when, actorId, type, fromStage, toStage,
})
const mini = (batch: Batch, jobs: Job[], events: JobEvent[] = [], now = NOW) => ({ now, batches: [batch], jobs, events })

const fresh = () => createSeedState()
const run = (s: DashboardState, ...as: Action[]) => as.reduce(applyAction, s)
const as = (s: DashboardState, userId: string): DashboardState => ({ ...s, currentUserId: userId })
const pmId = (s: DashboardState) => s.users.find((u) => u.role === 'pm')!.id
const snapshot = (s: DashboardState) => JSON.stringify(s)

describe('A1 stepOfStage', () => {
  it('maps every stage per contract', () => {
    const expected: Record<JobStage, ReturnType<typeof stepOfStage>> = {
      unassigned_pool: null, team_pool: 'annotate', anno_in_progress: 'annotate', qc1_pending: 'qc1', qc1_in_progress: 'qc1',
      qc2_pending: 'qc2', qc2_in_progress: 'qc2', ready_to_deliver: null, delivered: null,
    }
    for (const [stage, step] of Object.entries(expected)) expect(stepOfStage(stage as JobStage), stage).toBe(step)
  })
})

describe('A2 defaultStepDue', () => {
  it('counts back from dueAt by buffer days', () => {
    const due = at(10 * D)
    const b = mkBatch({ dueAt: due })
    expect(defaultStepDue(b, 'qc2')).toBe(due)
    expect(defaultStepDue(b, 'qc1')).toBe(at(9 * D))
    expect(defaultStepDue(b, 'annotate')).toBe(at(7 * D))
  })
  it('returns null without batch dueAt', () => {
    expect(defaultStepDue(mkBatch(), 'qc2')).toBeNull()
  })
})

describe('A3 override wins (I3)', () => {
  it('uses job.due then falls back to batch default after clearing', () => {
    const s0 = fresh()
    const job = s0.jobs.find((j) => j.stage === 'anno_in_progress' && !j.due && s0.batches.find((b) => b.id === j.batchId)!.dueAt)!
    expect(stepDue(s0, job, 'annotate')!.source).toBe('batch')
    const iso = at(5 * D, s0.now)
    const s1 = run(as(s0, pmId(s0)), { kind: 'setJobDue', jobId: job.id, step: 'annotate', dueAt: iso })
    const j1 = s1.jobs.find((j) => j.id === job.id)!
    expect(stepDue(s1, j1, 'annotate')).toEqual({ step: 'annotate', dueAt: iso, source: 'job' })
    expect(jobDeadline(s1, j1)!.source).toBe('job')
    const s2 = run(s1, { kind: 'setJobDue', jobId: job.id, step: 'annotate', dueAt: null })
    const j2 = s2.jobs.find((j) => j.id === job.id)!
    expect(stepDue(s2, j2, 'annotate')!.source).toBe('batch')
    expect(stepDue(s2, j2, 'annotate')!.dueAt).toBe(stepDue(s0, job, 'annotate')!.dueAt)
  })
  it('is none when neither batch nor job has a due', () => {
    const j = mkJob('j1', 'qc2_pending')
    expect(stepDue(mini(mkBatch(), [j]), j, 'qc2')).toBeNull()
    expect(deadlineStatus(mini(mkBatch(), [j]), j)).toBe('none')
  })
})

describe('A4 deadlineStatus boundaries', () => {
  const status = (offsetMs: number | null) => {
    const b = mkBatch({ dueAt: offsetMs === null ? null : at(offsetMs) })
    const j = mkJob('j1', 'qc2_pending')
    return deadlineStatus(mini(b, [j]), j)
  }
  it('24h05 / 23h59 / 0 / -1min / no due', () => {
    expect(status(24 * H + 5 * 60_000)).toBe('on_track')
    expect(status(24 * H)).toBe('on_track')
    expect(status(23 * H + 59 * 60_000)).toBe('due_soon')
    expect(status(0)).toBe('overdue')
    expect(status(-60_000)).toBe('overdue')
    expect(status(null)).toBe('none')
  })
  it('hoursLeft is negative when late and null without due; stage without step is none', () => {
    const b = mkBatch({ dueAt: at(-2 * H) })
    const j = mkJob('j1', 'qc2_pending')
    expect(hoursLeft(mini(b, [j]), j)).toBeCloseTo(-2, 6)
    expect(hoursLeft(mini(mkBatch(), [j]), j)).toBeNull()
    const done = mkJob('j2', 'delivered')
    expect(deadlineStatus(mini(b, [done]), done)).toBe('none')
  })
})

describe('A5 setBatchDue errors', () => {
  const s0 = fresh()
  const target = s0.batches.find((b) => b.id === 'b10')!
  const call = (s: DashboardState, patch: Partial<Extract<Action, { kind: 'setBatchDue' }>> = {}) =>
    applyAction(s, { kind: 'setBatchDue', batchId: target.id, dueAt: at(3 * D, s.now), ...patch })
  it('throws for annotator and lead, state untouched', () => {
    const before = snapshot(s0)
    for (const role of ['annotator', 'lead'] as const) {
      const u = s0.users.find((x) => x.role === role)!
      expect(() => call(as(s0, u.id)), role).toThrow(/quyền/)
    }
    expect(snapshot(s0)).toBe(before)
  })
  it('throws for released/delivered batch, invalid date and negative buffer', () => {
    const pm = as(s0, 'u04')
    for (const id of ['b06', 'b03']) expect(() => applyAction(pm, { kind: 'setBatchDue', batchId: id, dueAt: at(D, pm.now) })).toThrow()
    expect(() => call(pm, { dueAt: 'khong-hop-le' })).toThrow(/không hợp lệ/)
    expect(() => call(pm, { stepBufferDays: { qc1: -1, qc2: 1 } })).toThrow(/không âm/)
    expect(() => call(pm, { stepBufferDays: { qc1: 1, qc2: -0.5 } })).toThrow(/không âm/)
    expect(snapshot(pm)).toBe(snapshot(as(s0, 'u04')))
  })
  it('succeeds for pm and admin', () => {
    const iso = at(3 * D, s0.now)
    for (const role of ['pm', 'admin'] as const) {
      const u = s0.users.find((x) => x.role === role && (role !== 'pm' || x.id === 'u04'))!
      const s1 = call(as(s0, u.id), { dueAt: iso, stepBufferDays: { qc1: 3, qc2: 2 } })
      const b = s1.batches.find((x) => x.id === target.id)!
      expect(b.dueAt).toBe(iso)
      expect(b.stepBufferDays).toEqual({ qc1: 3, qc2: 2 })
    }
  })
})

describe('A6 setJobDue permissions', () => {
  const s0 = fresh()
  const job = s0.jobs.find((j) => j.stage === 'anno_in_progress' && j.teamId)!
  const call = (s: DashboardState, jobId = job.id) => applyAction(s, { kind: 'setJobDue', jobId, step: 'annotate', dueAt: at(2 * D, s.now) })
  it('throws for lead of another team and annotator', () => {
    const otherLead = s0.users.find((u) => u.role === 'lead' && !u.teamIds.includes(job.teamId!))!
    expect(() => call(as(s0, otherLead.id))).toThrow(/quyền/)
    expect(() => call(as(s0, job.annotatorId!))).toThrow(/quyền/)
  })
  it('allows lead of the job team, pm and admin; throws on delivered job', () => {
    const lead = s0.users.find((u) => u.role === 'lead' && u.teamIds.includes(job.teamId!))!
    expect(() => call(as(s0, lead.id))).not.toThrow()
    expect(() => call(as(s0, pmId(s0)))).not.toThrow()
    expect(() => call(as(s0, s0.users.find((u) => u.role === 'admin')!.id))).not.toThrow()
    const delivered = s0.jobs.find((j) => j.stage === 'delivered')!
    expect(() => call(as(s0, pmId(s0)), delivered.id)).toThrow(/đã giao/)
  })
})

describe('A7 every change appends exactly one event (I5)', () => {
  it('batch due_set / due_clear and job due_override', () => {
    const s0 = as(fresh(), pmId(fresh()))
    const n0 = s0.batchEvents.length
    const s1 = run({ ...s0, currentUserId: 'u04' }, { kind: 'setBatchDue', batchId: 'b10', dueAt: at(4 * D, s0.now) })
    expect(s1.batchEvents.length).toBe(n0 + 1)
    expect(s1.batchEvents.at(-1)).toMatchObject({ batchId: 'b10', type: 'due_set' })
    expect(s1.batchEvents.at(-1)!.detail).toMatch(/^Đặt hạn giao \d{2}\/\d{2}\/\d{4} \d{2}:\d{2}$/)
    const s2 = run(s1, { kind: 'setBatchDue', batchId: 'b10', dueAt: null })
    expect(s2.batchEvents.length).toBe(n0 + 2)
    expect(s2.batchEvents.at(-1)!.type).toBe('due_clear')
    expect(s2.batches.find((b) => b.id === 'b10')!.dueAt).toBeNull()
    expect(batchHistory(s2, 'b10')[0].type).toBe('due_clear')

    const job = s0.jobs.find((j) => j.stage === 'qc1_pending' && !j.due)!
    const e0 = s0.events.length
    const s3 = run({ ...s0, currentUserId: 'u01' }, { kind: 'setJobDue', jobId: job.id, step: 'qc1', dueAt: at(2 * D, s0.now) })
    expect(s3.events.length).toBe(e0 + 1)
    expect(s3.events.at(-1)).toMatchObject({ jobId: job.id, type: 'due_override', fromStage: job.stage, toStage: job.stage })
    expect(s3.events.at(-1)!.reason).toMatch(/^Hạn qc1: /)
    const s4 = run(s3, { kind: 'setJobDue', jobId: job.id, step: 'qc1', dueAt: null })
    expect(s4.events.length).toBe(e0 + 2)
    expect(s4.events.at(-1)!.reason).toBe('Bỏ hạn riêng qc1')
    expect(eventsOfJob(s4, job.id).filter((e) => e.type === 'due_override').length).toBe(2)
    expect(s4.jobs.find((j) => j.id === job.id)!.due?.qc1).toBeUndefined()
  })
})

describe('A8 onTimeStats', () => {
  const due = at(10 * D)
  const b = mkBatch({ dueAt: due }) // annotate +7d, qc1 +9d, qc2 +10d
  const j = mkJob('j1', 'ready_to_deliver')
  const evs = [
    mkEv('j1', 'submit', at(6 * D), 'ua', 'qc1_pending'),
    mkEv('j1', 'qc1_pass', at(9 * D + H), 'uq', 'qc2_pending'), // trễ
    mkEv('j1', 'qc2_pass', at(9 * D), 'upm', 'ready_to_deliver'),
  ]
  it('3 steps done, 1 late', () => {
    const r = onTimeStats(mini(b, [j], evs), {})
    expect(r).toMatchObject({ total: 3, onTime: 2, late: 1 })
    expect(r.rate).toBeCloseTo(2 / 3, 6)
  })
  it('filters by user, step and range; empty => rate 1', () => {
    const s = mini(b, [j], evs)
    expect(onTimeStats(s, { userIds: ['uq'] })).toMatchObject({ total: 1, late: 1, rate: 0 })
    expect(onTimeStats(s, { step: 'annotate' })).toMatchObject({ total: 1, late: 0, rate: 1 })
    expect(onTimeStats(s, { userIds: ['nobody'] })).toEqual({ total: 0, onTime: 0, late: 0, rate: 1 })
    expect(onTimeStats(s, { teamId: 'tx' }).total).toBe(0)
    expect(onTimeStats(s, { batchId: 'bx', from: at(0).slice(0, 10), to: at(7 * D).slice(0, 10) }).total).toBe(1)
  })
  it('skips steps with no effective due', () => {
    expect(onTimeStats(mini(mkBatch(), [j], evs), {}).total).toBe(0)
  })
  it('uses first submit and last qc pass', () => {
    const more = [...evs, mkEv('j1', 'submit', at(8 * D), 'ua', 'qc1_pending'), mkEv('j1', 'qc2_pass', at(11 * D), 'upm', 'ready_to_deliver')]
    const r = onTimeStats(mini(b, [j], more), { step: 'qc2' })
    expect(r).toMatchObject({ total: 1, late: 1 })
    expect(onTimeStats(mini(b, [j], more), { step: 'annotate' }).late).toBe(0)
  })
})

describe('A9 batchForecast', () => {
  /** remaining job chưa xong + `ready` job đã vào ready_to_deliver trong 7 ngày qua. */
  const scen = (dueMs: number | null, remaining: number, ready: number, extra: Partial<Batch> = {}) => {
    const jobs: Job[] = []
    const events: JobEvent[] = []
    for (let i = 0; i < remaining; i++) jobs.push(mkJob(`r${i}`, 'anno_in_progress'))
    for (let i = 0; i < ready; i++) {
      jobs.push(mkJob(`d${i}`, 'ready_to_deliver'))
      events.push(mkEv(`d${i}`, 'qc2_pass', at(-(i + 1) * H), 'upm', 'ready_to_deliver', 'qc2_in_progress'))
    }
    return batchForecast(mini(mkBatch({ dueAt: dueMs === null ? null : at(dueMs), ...extra }), jobs, events), 'bx')
  }
  it('no_due', () => expect(scen(null, 3, 2).verdict).toBe('no_due'))
  it('done', () => {
    const f = scen(5 * D, 0, 3)
    expect(f.verdict).toBe('done')
    expect(f.remainingJobs).toBe(0)
  })
  it('on_track: eta before due', () => {
    const f = scen(10 * D, 7, 7) // 1 job/ngày => 7 ngày
    expect(f.verdict).toBe('on_track')
    expect(f.throughputPerDay).toBeCloseTo(1, 6)
    expect(new Date(f.etaAt!).getTime()).toBe(new Date(NOW).getTime() + 7 * D)
    expect(f.daysLate).toBe(0)
  })
  it('at_risk: eta after due, daysLate rounded up', () => {
    const f = scen(3 * D + 1, 7, 7)
    expect(f.verdict).toBe('at_risk')
    expect(f.daysLate).toBe(4)
  })
  it('late: past due with remaining jobs', () => {
    const f = scen(-D, 4, 7)
    expect(f.verdict).toBe('late')
    expect(f.daysLate).toBeGreaterThanOrEqual(1)
  })
  it('throughput 0 => etaAt null and at_risk (or late)', () => {
    const f = scen(10 * D, 3, 0)
    expect(f).toMatchObject({ verdict: 'at_risk', etaAt: null, throughputPerDay: 0, remainingJobs: 3 })
    expect(scen(-2 * D, 3, 0)).toMatchObject({ verdict: 'late', etaAt: null, daysLate: 2 })
  })
  it('ignores arrivals older than 7 days', () => {
    const jobs = [mkJob('r', 'anno_in_progress'), mkJob('d', 'ready_to_deliver')]
    const ev = [mkEv('d', 'qc2_pass', at(-8 * D), 'upm', 'ready_to_deliver', 'qc2_in_progress')]
    expect(batchForecast(mini(mkBatch({ dueAt: at(5 * D) }), jobs, ev), 'bx').throughputPerDay).toBe(0)
  })
})

describe('A10 overdueJobs', () => {
  const b = mkBatch({ dueAt: at(-1 * H) }) // qc2 trễ 1h, qc1 trễ 25h, annotate trễ 73h
  const jobs = [
    mkJob('jq2', 'qc2_pending', { qc2Id: 'pm1' }),
    mkJob('jq1', 'qc1_pending', { qc1Id: 'qcA' }),
    mkJob('ja', 'anno_in_progress', { annotatorId: 'anA', teamId: 't9' }),
    mkJob('jown', 'qc2_pending', { due: { qc2: at(10 * H) } }),
    mkJob('jdone', 'delivered'),
  ]
  const s = mini(b, jobs)
  it('sorts most overdue first and drops on-time/none', () => {
    expect(overdueJobs(s, {}).map((j) => j.id)).toEqual(['ja', 'jq1', 'jq2'])
  })
  it('respects scope', () => {
    expect(overdueJobs(s, { teamId: 't9' }).map((j) => j.id)).toEqual(['ja'])
    expect(overdueJobs(s, { userId: 'qcA' }).map((j) => j.id)).toEqual(['jq1'])
    expect(overdueJobs(s, { userId: 'anA' }).map((j) => j.id)).toEqual(['ja'])
    expect(overdueJobs(s, { batchIds: ['other'] })).toEqual([])
    expect(overdueJobs(s, { projectId: 'p1', batchIds: ['bx'] }).length).toBe(3)
    expect(overdueJobs(s, { projectId: 'p2' })).toEqual([])
  })
})

describe('A11 seed covers contract §E', () => {
  const s = fresh()
  const statusCount = (batchId: string) => {
    const c: Record<string, number> = {}
    for (const j of s.jobs.filter((x) => x.batchId === batchId)) c[deadlineStatus(s, j)] = (c[deadlineStatus(s, j)] ?? 0) + 1
    return c
  }
  it('is deterministic', () => expect(createSeedState()).toEqual(createSeedState()))
  it('b01 on_track (forecast + most jobs on time)', () => {
    expect(batchForecast(s, 'b01').verdict).toBe('on_track')
    const c = statusCount('b01')
    expect(c.on_track).toBeGreaterThan(c.overdue ?? 0)
    const left = (new Date(s.batches.find((b) => b.id === 'b01')!.dueAt!).getTime() - new Date(s.now).getTime()) / D
    expect(left).toBeGreaterThan(7.5)
    expect(left).toBeLessThan(8.5)
  })
  it('b02 has due_soon and overdue jobs, due in ~20h', () => {
    const c = statusCount('b02')
    expect(c.due_soon).toBeGreaterThan(0)
    expect(c.overdue).toBeGreaterThan(0)
    // hạn giờ lẻ 20h15m (không tròn) — giá trị seed cũ 20h đã đổi cho dữ liệu thực tế hơn
    expect(new Date(s.batches.find((b) => b.id === 'b02')!.dueAt!).getTime() - new Date(s.now).getTime()).toBe(20 * H + 15 * 60_000)
  })
  it('b07 late, b10 no_due, b04 future due', () => {
    expect(batchForecast(s, 'b07').verdict).toBe('late')
    expect(batchForecast(s, 'b10').verdict).toBe('no_due')
    expect(new Date(s.batches.find((b) => b.id === 'b04')!.dueAt!).getTime()).toBeGreaterThan(new Date(s.now).getTime())
  })
  it('>= 6 job overrides, each with a due_override event; due_set history exists', () => {
    const withDue = s.jobs.filter((j) => j.due && Object.keys(j.due).length > 0)
    expect(withDue.length).toBeGreaterThanOrEqual(6)
    for (const j of withDue) expect(eventsOfJob(s, j.id).some((e) => e.type === 'due_override'), j.id).toBe(true)
    const nowMs = new Date(s.now).getTime()
    const dues = withDue.flatMap((j) => Object.values(j.due!)).map((d) => new Date(d).getTime())
    expect(dues.some((d) => d < nowMs)).toBe(true)
    expect(dues.some((d) => d > nowMs)).toBe(true)
    for (const b of s.batches.filter((x) => x.dueAt)) expect(batchHistory(s, b.id).some((e) => e.type === 'due_set'), b.id).toBe(true)
  })
  it('annotator demo (cvat_user_6) and another annotator have overdue jobs', () => {
    const u6 = s.users.find((u) => u.cvatUsername === 'cvat_user_6')!
    expect(overdueJobs(s, { userId: u6.id }).length).toBeGreaterThan(0)
    const annos = s.users.filter((u) => u.role === 'annotator' && u.id !== u6.id)
    expect(annos.some((u) => overdueJobs(s, { userId: u.id }).length > 0)).toBe(true)
  })
})

describe('A12 lock and due are independent (I2)', () => {
  it('setBatchDue leaves autoLockAt; setAutoLock leaves dueAt/buffer', () => {
    const s0 = as(fresh(), pmId(fresh()))
    const b0 = s0.batches.find((b) => b.id === 'b01')!
    const s1 = run(s0, { kind: 'setBatchDue', batchId: 'b01', dueAt: at(2 * D, s0.now), stepBufferDays: { qc1: 3, qc2: 2 } })
    const b1 = s1.batches.find((b) => b.id === 'b01')!
    expect(b1.autoLockAt).toBe(b0.autoLockAt)
    const s2 = run(s1, { kind: 'setBatchDue', batchId: 'b01', dueAt: null })
    expect(s2.batches.find((b) => b.id === 'b01')!.autoLockAt).toBe(b0.autoLockAt)
    const s3 = run(s1, { kind: 'setAutoLock', batchId: 'b01', autoLockAt: at(D, s1.now) })
    const b3 = s3.batches.find((b) => b.id === 'b01')!
    expect(b3.dueAt).toBe(b1.dueAt)
    expect(b3.stepBufferDays).toEqual({ qc1: 3, qc2: 2 })
    const s4 = run(s1, { kind: 'setAutoLock', batchId: 'b01', autoLockAt: null })
    expect(s4.batches.find((b) => b.id === 'b01')!.dueAt).toBe(b1.dueAt)
  })
})

describe('A7b re-setting the same due is a no-op (I5: one event per change)', () => {
  it('setJobDue with the current override adds no event', () => {
    const s0 = fresh()
    const job = s0.jobs.find((j) => j.stage === 'anno_in_progress')!
    const iso = at(4 * D, s0.now)
    const s1 = run(as(s0, pmId(s0)), { kind: 'setJobDue', jobId: job.id, step: 'annotate', dueAt: iso })
    const s2 = run(s1, { kind: 'setJobDue', jobId: job.id, step: 'annotate', dueAt: iso })
    expect(eventsOfJob(s2, job.id).length).toBe(eventsOfJob(s1, job.id).length)
    const s3 = run(s2, { kind: 'setJobDue', jobId: job.id, step: 'annotate', dueAt: null })
    const s4 = run(s3, { kind: 'setJobDue', jobId: job.id, step: 'annotate', dueAt: null })
    expect(eventsOfJob(s4, job.id).length).toBe(eventsOfJob(s3, job.id).length)
  })
  it('setBatchDue with the same due and buffers adds no event', () => {
    const s0 = as(fresh(), pmId(fresh()))
    const b = s0.batches.find((x) => x.status === 'in_progress' && x.dueAt)!
    const s1 = run(s0, { kind: 'setBatchDue', batchId: b.id, dueAt: b.dueAt, stepBufferDays: b.stepBufferDays })
    expect(batchHistory(s1, b.id).length).toBe(batchHistory(s0, b.id).length)
  })
})
