import { describe, expect, it } from 'vitest'
import { applyAction, type Action } from './logic'
import { createSeedState } from './seed'
import { isJobLocked, eventsOfJob, projectStats, qcStats, reworkByTeam, topErrorCategories, userStats, visibleProjects, visibleTeams, projectTeamIds } from './selectors'
import type { DashboardState, Job, JobStage } from './types'

const fresh = () => { const s = createSeedState(); return { ...s, currentUserId: s.users.find((u) => u.role === 'admin')!.id } }
const run = (s: DashboardState, ...as: Action[]) => as.reduce((state, action) => {
  // Workflow fixtures act as the assigned worker at each step.
  const job = 'jobId' in action ? state.jobs.find(j => j.id === action.jobId) : undefined
  const actor = action.kind === 'submitJob' ? job?.annotatorId : ['startQc1', 'qc1Pass', 'qc1Return'].includes(action.kind) ? job?.qc1Id : null
  return applyAction(actor ? { ...state, currentUserId: actor } : state, action)
}, s)
// Mặc định bỏ qua job của batch đang bị khoá (autoLockAt quá hạn) — thao tác trên đó bị chặn có chủ đích.
const find = (s: DashboardState, stage: JobStage, pred: (j: Job) => boolean = () => true) => {
  const j = s.jobs.find((x) => x.stage === stage && !isJobLocked(s, x.id) && pred(x))
  if (!j) throw new Error('no job at ' + stage)
  return j
}
const get = (s: DashboardState, id: string) => s.jobs.find((j) => j.id === id)!
const lastEvent = (s: DashboardState, id: string) => eventsOfJob(s, id).at(-1)!
const today = (s: DashboardState, userId: string) => s.kpiDaily.find((k) => k.userId === userId && k.date === s.now.slice(0, 10))?.editedCuboids ?? 0

describe('seed', () => {
  it('is deterministic and has expected shape', () => {
    expect(createSeedState()).toEqual(createSeedState())
    const s = fresh()
    expect(s.users.length).toBeGreaterThanOrEqual(38)
    expect(s.jobs.length).toBeGreaterThanOrEqual(80) // plan 09: batch 8–10 job
    expect(s.teams.length).toBe(6) // plan 09: thêm t6 để p2 có 2 team
    expect(s.kpiDaily.length).toBe(s.users.filter((u) => u.role === 'annotator').length * 14)
    const b = s.batches.find((x) => x.status === 'pending')!
    expect(s.jobs.filter((j) => j.batchId === b.id && j.stage === 'unassigned_pool').length).toBe(10)
    expect(s.jobs.filter((j) => j.cvatDrift).length).toBeGreaterThan(0)
    expect(new Set(s.jobs.map((j) => j.stage)).size).toBe(9)
    expect(s.jobs.some((j) => j.reworkCount > 0)).toBe(true)
  })
  it('job events replay to the job stage', () => {
    const s = fresh()
    for (const j of s.jobs.filter((x) => x.stage !== 'unassigned_pool')) expect(lastEvent(s, j.id).toStage).toBe(j.stage)
  })
})

describe('assign / submit / KPI', () => {
  it('assignJob: team_pool -> anno_in_progress with event', () => {
    const s0 = fresh()
    const j = find(s0, 'team_pool')
    const team = s0.teams.find((t) => t.id === j.teamId)!
    const annotatorId = team.memberIds.find((id) => id !== team.leadId)!
    const qc1Id = team.leadId
    const s = run(s0, { kind: 'assignJob', jobId: j.id, annotatorId, qc1Id })
    expect(get(s, j.id)).toMatchObject({ stage: 'anno_in_progress', annotatorId, qc1Id })
    expect(lastEvent(s, j.id)).toMatchObject({ type: 'assign', fromStage: 'team_pool', toStage: 'anno_in_progress' })
    expect(s.events.length).toBe(s0.events.length + 1)
  })
  it('assignJob rejects wrong stage', () => {
    const s = fresh()
    expect(() => applyAction(s, { kind: 'assignJob', jobId: find(s, 'delivered').id, annotatorId: 'a', qc1Id: 'b' })).toThrow()
  })
  it('first submit credits KPI once; resubmit after rework adds none', () => {
    const s0 = fresh()
    const j = find(s0, 'anno_in_progress', (x) => x.firstSubmittedAt === null)
    const before = today(s0, j.annotatorId!)
    const s1 = run(s0, { kind: 'submitJob', jobId: j.id, editedCuboids: 500 })
    expect(get(s1, j.id)).toMatchObject({ stage: 'qc1_pending', editedCuboids: 500 })
    expect(get(s1, j.id).firstSubmittedAt).not.toBeNull()
    expect(today(s1, j.annotatorId!)).toBe(before + 500)
    expect(lastEvent(s1, j.id).type).toBe('submit')
    const s2 = run(s1, { kind: 'qc1Return', jobId: j.id, reason: 'Box lệch', errorCategory: 'Box lệch' },
      { kind: 'submitJob', jobId: j.id, editedCuboids: 9999 })
    expect(today(s2, j.annotatorId!)).toBe(before + 500)
    expect(get(s2, j.id).editedCuboids).toBe(500)
    expect(lastEvent(s2, j.id).type).toBe('resubmit')
  })
  it('submit creates a KPI row when none exists for today', () => {
    const s0 = fresh()
    const s = { ...s0, kpiDaily: s0.kpiDaily.filter((k) => k.date !== s0.now.slice(0, 10)) }
    const j = find(s, 'anno_in_progress', (x) => x.firstSubmittedAt === null)
    expect(today(run(s, { kind: 'submitJob', jobId: j.id, editedCuboids: 10 }), j.annotatorId!)).toBe(10)
  })
})

describe('QC1', () => {
  it('start -> pass', () => {
    const s0 = fresh()
    const j = find(s0, 'qc1_pending')
    const s = run(s0, { kind: 'startQc1', jobId: j.id })
    expect(get(s, j.id).stage).toBe('qc1_in_progress')
    expect(get(run(s, { kind: 'qc1Pass', jobId: j.id }), j.id).stage).toBe('qc2_pending')
  })
  it('return: rework +1 against annotator, reason required', () => {
    const s0 = fresh()
    const j = find(s0, 'qc1_in_progress')
    expect(() => applyAction(s0, { kind: 'qc1Return', jobId: j.id, reason: '  ', errorCategory: 'Sai nhãn' })).toThrow()
    expect(() => applyAction(s0, { kind: 'qc1Return', jobId: j.id, reason: 'x', errorCategory: '' })).toThrow()
    const s = run(s0, { kind: 'qc1Return', jobId: j.id, reason: 'Sai nhãn xe', errorCategory: 'Sai nhãn' })
    expect(get(s, j.id)).toMatchObject({ stage: 'anno_in_progress', reworkCount: j.reworkCount + 1 })
    expect(lastEvent(s, j.id)).toMatchObject({ type: 'qc1_return', reason: 'Sai nhãn xe', errorCategory: 'Sai nhãn', reworkAgainst: [j.annotatorId] })
  })
})

describe('QC2', () => {
  it('pass -> ready_to_deliver, sets qc2Id', () => {
    const s0 = fresh()
    const j = find(s0, 'qc2_pending')
    const s = run(s0, { kind: 'startQc2', jobId: j.id }, { kind: 'qc2Pass', jobId: j.id })
    expect(get(s, j.id)).toMatchObject({ stage: 'ready_to_deliver', qc2Id: s0.currentUserId })
  })
  it('return to QC1: rework against qc1 only', () => {
    const s0 = fresh()
    const j = find(s0, 'qc2_in_progress')
    const s = run(s0, { kind: 'qc2ReturnToQc1', jobId: j.id, reason: 'QC1 bỏ sót', errorCategory: 'Thiếu object' })
    expect(get(s, j.id)).toMatchObject({ stage: 'qc1_in_progress', reworkCount: j.reworkCount + 1 })
    expect(lastEvent(s, j.id).reworkAgainst).toEqual([j.qc1Id])
  })
  it('return to anno: rework against annotator + qc1, then must pass QC1 again', () => {
    const s0 = fresh()
    const j = find(s0, 'qc2_in_progress')
    expect(() => applyAction(s0, { kind: 'qc2ReturnToAnno', jobId: j.id, reason: '', errorCategory: 'Sai nhãn' })).toThrow()
    const s = run(s0, { kind: 'qc2ReturnToAnno', jobId: j.id, reason: 'Sai hướng', errorCategory: 'Sai hướng' })
    expect(get(s, j.id).stage).toBe('anno_in_progress')
    expect(lastEvent(s, j.id).reworkAgainst).toEqual([j.annotatorId, j.qc1Id])
    expect(get(s, j.id).qc2Id).toBe(s0.currentUserId)
    const s2 = run(s, { kind: 'submitJob', jobId: j.id }, { kind: 'qc1Pass', jobId: j.id })
    expect(get(s2, j.id).stage).toBe('qc2_pending')
    expect(eventsOfJob(s2, j.id).map((e) => e.type).slice(-3)).toEqual(['qc2_return_anno', 'resubmit', 'qc1_pass'])
  })
})

describe('deliver / reassign / data type', () => {
  it('markDelivered batch; rejects ineligible', () => {
    const s0 = fresh()
    const ids = s0.jobs.filter((j) => j.stage === 'ready_to_deliver').slice(0, 3).map((j) => j.id)
    const s = run(s0, { kind: 'markDelivered', jobIds: ids })
    ids.forEach((id) => expect(get(s, id).stage).toBe('delivered'))
    expect(() => applyAction(s0, { kind: 'markDelivered', jobIds: [find(s0, 'team_pool').id] })).toThrow()
  })
  it('reassignJob keeps history and stage', () => {
    const s0 = fresh()
    const j = find(s0, 'anno_in_progress')
    const annotatorId = s0.teams.find((t) => t.id === j.teamId)!.memberIds.find((id) => id !== j.qc1Id && id !== j.annotatorId)!
    const s = run(s0, { kind: 'reassignJob', jobId: j.id, annotatorId })
    expect(get(s, j.id)).toMatchObject({ annotatorId, qc1Id: j.qc1Id, stage: j.stage })
    expect(eventsOfJob(s, j.id).length).toBe(eventsOfJob(s0, j.id).length + 1)
    expect(lastEvent(s, j.id).type).toBe('reassign')
    expect(() => applyAction(s0, { kind: 'reassignJob', jobId: j.id })).toThrow()
  })
  it('updateDataType', () => {
    const s0 = fresh()
    const dt = { ...s0.dataTypes[0], kpiPerDay: 1500 }
    expect(run(s0, { kind: 'updateDataType', dataType: dt }).dataTypes[0].kpiPerDay).toBe(1500)
  })
  it('setCurrentUser', () => {
    const s0 = fresh()
    expect(run(s0, { kind: 'setCurrentUser', userId: s0.users[5].id }).currentUserId).toBe(s0.users[5].id)
  })
})

describe('assign batch to one team (plan 09 R2/R3)', () => {
  const s0 = fresh()
  const task = s0.batches.find((b) => b.status === 'pending')!
  it('admin assigns a pending batch to one team of the project: all pool jobs go to that team', () => {
    const admin = s0.users.find((u) => u.role === 'admin')!
    const teamId = projectTeamIds(s0, task.projectId)[0]
    const s = run({ ...s0, currentUserId: admin.id }, { kind: 'assignBatchTeam', batchId: task.id, teamId })
    const jobs = s.jobs.filter((j) => j.batchId === task.id)
    expect(jobs.length).toBeGreaterThan(0)
    expect(jobs.every((j) => j.stage === 'team_pool' && j.teamId === teamId)).toBe(true)
    expect(s.batches.find((b) => b.id === task.id)).toMatchObject({ status: 'in_progress', teamId })
    expect(s.batchEvents.at(-1)).toMatchObject({ batchId: task.id, type: 'distribute' })
  })
})

describe('selectors', () => {
  const s = fresh()
  it('projectStats definitions', () => {
    const st = projectStats(s, 'p1')
    const jobs = s.jobs.filter((j) => j.projectId === 'p1')
    const assigned = jobs.filter((j) => j.annotatorId)
    const done = assigned.filter((j) => j.stage === 'ready_to_deliver' || j.stage === 'delivered')
    expect(st.totalJobs).toBe(jobs.length)
    expect(st.completionPct).toBeCloseTo((done.length / assigned.length) * 100, 0)
    expect(st.editedCuboids).toBe(jobs.reduce((n, j) => n + j.editedCuboids, 0))
  })
  it('userStats: week has 7 days, today matches kpi', () => {
    const u = s.users.find((x) => x.role === 'annotator')!
    const st = userStats(s, u.id)
    expect(st.kpiWeek).toHaveLength(7)
    expect(st.kpiToday).toBe(today(s, u.id))
    expect(st.kpiTarget).toBeGreaterThan(0)
  })
  it('rework + error categories + qc stats', () => {
    expect(reworkByTeam(s, 'p1').reduce((n, r) => n + r.reworkCount, 0)).toBeGreaterThan(0)
    const top = topErrorCategories(s, 'p1')
    expect(top[0].count).toBeGreaterThanOrEqual(top.at(-1)!.count)
    const qc = s.users.find((u) => u.isQc)!
    const q = qcStats(s, qc.id)
    expect(q.qc2Returned).toBeLessThanOrEqual(q.qc1Passed)
  })
  it('scope by role', () => {
    const pm = s.users.find((u) => u.role === 'pm')!
    expect(visibleProjects(s, pm).every((p) => p.pmIds.includes(pm.id))).toBe(true)
    const lead = s.users.find((u) => u.role === 'lead')!
    expect(visibleTeams(s, lead)).toHaveLength(1)
    expect(visibleTeams(s, s.users.find((u) => u.role === 'admin')!)).toHaveLength(6)
  })
})
