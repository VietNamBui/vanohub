import { describe, expect, it } from 'vitest'
import { applyAction, isBatchLocked, type Action } from './logic'
import { createSeedState } from './seed'
import {
  auditableBatches, batchHistory, batchStats, canAccessPath, visibleProjects, datasetStats, isJobLocked, jobsOfBatch, keyMetrics, nextAuditLevel,
  queueRowsForUser, statsByStage, workingHours,
} from './selectors'
import type { DashboardState, JobStage } from './types'

const fresh = () => createSeedState()
const run = (s: DashboardState, ...as: Action[]) => as.reduce(applyAction, s)
const stageOf = (s: DashboardState, id: string) => s.jobs.find((j) => j.id === id)!.stage
const batch = (s: DashboardState, id: string) => s.batches.find((b) => b.id === id)!

describe('seed: datasets & batches', () => {
  const s = fresh()
  it('shape and coherence', () => {
    expect(s.datasets).toHaveLength(4)
    expect(s.batches).toHaveLength(10)
    expect(new Set(s.batches.map((b) => b.status))).toEqual(new Set(['pending', 'in_progress', 'in_audit', 'ready', 'delivered', 'released']))
    for (const j of s.jobs) expect(s.batches.some((b) => b.id === j.batchId)).toBe(true)
    expect(s.batches.filter((b) => b.status === 'pending')).toHaveLength(1)
    expect(jobsOfBatch(s, 'b06')).toHaveLength(0)
    expect(s.users.find((u) => u.id === s.currentUserId)!.employeeId).toBe(2828)
    expect(s.teams.some((t) => t.canQa)).toBe(true)
  })
  it('locks: one past, one future', () => {
    expect(isBatchLocked(s, batch(s, 'b09'))).toBe(true)
    expect(isBatchLocked(s, batch(s, 'b01'))).toBe(false)
    expect(batch(s, 'b01').autoLockAt).not.toBeNull()
  })
  it('ready/delivered batches match their jobs; audits history', () => {
    expect(jobsOfBatch(s, 'b04').every((j) => j.stage === 'ready_to_deliver')).toBe(true)
    expect(jobsOfBatch(s, 'b03').every((j) => j.stage === 'delivered')).toBe(true)
    expect(s.audits.map((a) => [a.status, s.audits[0].levels[a.currentLevelIndex]])).toEqual([
      ['passed', 100], ['passed', 30], ['failed', 100], ['open', 100],
    ])
    expect(nextAuditLevel(s, 'p1').percent).toBe(100) // sau audit trượt
  })
})

describe('locked jobs', () => {
  const s = { ...fresh(), currentUserId: 'u01' }
  const job = s.jobs.find((j) => j.batchId === 'b09' && j.stage === 'anno_in_progress')!
  it('selector + submit/qc throw', () => {
    expect(isJobLocked(s, job.id)).toBe(true)
    expect(() => applyAction({ ...s, currentUserId: job.annotatorId! }, { kind: 'submitJob', jobId: job.id })).toThrow('Batch đã bị khoá')
    const q = s.jobs.find((j) => j.batchId === 'b09' && j.stage === 'qc1_pending')
    if (q) expect(() => applyAction({ ...s, currentUserId: q.qc1Id! }, { kind: 'qc1Pass', jobId: q.id })).toThrow('Batch đã bị khoá')
  })
  it('setAutoLock(null) unlocks and logs event', () => {
    const n = run(s, { kind: 'setAutoLock', batchId: 'b09', autoLockAt: null })
    expect(isJobLocked(n, job.id)).toBe(false)
    expect(batchHistory(n, 'b09')[0]).toMatchObject({ type: 'autolock_reset' })
    expect(() => run({ ...n, currentUserId: job.annotatorId! }, { kind: 'submitJob', jobId: job.id })).not.toThrow()
  })
  it('setAutoLock types and validation', () => {
    const n = run(s, { kind: 'setAutoLock', batchId: 'b10', autoLockAt: '2027-01-01T00:00:00Z' })
    expect(batchHistory(n, 'b10')[0].type).toBe('autolock_set')
    expect(() => run(s, { kind: 'setAutoLock', batchId: 'b10', autoLockAt: 'zzz' })).toThrow()
  })
})

describe('batch actions', () => {
  const s = { ...fresh(), currentUserId: 'u01' }
  it('reassignBatch qc1 updates batch + open jobs + event', () => {
    const newQc = s.users.find((u) => u.isQc && u.id !== batch(s, 'b01').stepPic.qc1)!.id
    const n = run(s, { kind: 'reassignBatch', batchId: 'b01', step: 'qc1', picId: newQc })
    expect(batch(n, 'b01').stepPic.qc1).toBe(newQc)
    expect(jobsOfBatch(n, 'b01').filter((j) => j.stage === 'qc1_pending').every((j) => j.qc1Id === newQc)).toBe(true)
    expect(batchHistory(n, 'b01')[0].type).toBe('reassign')
    expect(() => run(s, { kind: 'reassignBatch', batchId: 'b05', step: 'qc1', picId: newQc })).toThrow()
    expect(() => run(s, { kind: 'reassignBatch', batchId: 'b01', step: 'annotate', picId: 'nope' })).toThrow()
  })
  it('releaseBatch removes jobs + their events; guards', () => {
    const n = run(s, { kind: 'releaseBatch', batchId: 'b10' })
    expect(batch(n, 'b10').status).toBe('released')
    expect(jobsOfBatch(n, 'b10')).toHaveLength(0)
    expect(n.events.every((e) => n.jobs.some((j) => j.id === e.jobId))).toBe(true)
    expect(batchHistory(n, 'b10')[0].type).toBe('release')
    expect(() => run(n, { kind: 'releaseBatch', batchId: 'b10' })).toThrow()
    expect(() => run(s, { kind: 'releaseBatch', batchId: 'b07' })).toThrow() // in_audit
  })
  it('stats selectors', () => {
    expect(datasetStats(s, 'd2')).toMatchObject({ batchTotal: 3, batchDone: 2 })
    const st = batchStats(s, 'b04')
    expect(st.progressPct).toBe(100)
    expect(st.picNames.qc2).toBeTruthy()
    expect(batchStats(s, 'b09').locked).toBe(true)
  })
})

describe('teams & users', () => {
  // plan 09: seed có 6 team (t1–t6) ⇒ team tạo mới là t7
  const s = { ...fresh(), currentUserId: 'u01' }
  const team = { name: 'Team Zeta', allowedSteps: ['annotate' as const], canQa: false }
  it('createTeam / updateTeam validation', () => {
    const n = run(s, { kind: 'createTeam', ...team })
    expect(n.teams.at(-1)).toMatchObject({ id: 't7', name: 'Team Zeta', canQa: false })
    expect(() => run(s, { kind: 'createTeam', ...team, name: ' ' })).toThrow()
    expect(() => run(s, { kind: 'createTeam', ...team, allowedSteps: [] })).toThrow()
    const u = run(n, { kind: 'updateTeam', teamId: 't7', patch: { canQa: true, allowedSteps: ['annotate', 'qc2'] } })
    expect(u.teams.at(-1)).toMatchObject({ canQa: true, allowedSteps: ['annotate', 'qc2'] })
  })
  it('add/remove member keeps user.teamIds in sync; lead protected', () => {
    const n0 = run(s, { kind: 'createTeam', ...team })
    const user = s.users.find((x) => x.role === 'annotator')!
    const detached = run({ ...n0, currentUserId: s.users.find((u) => u.role === 'admin')!.id }, { kind: 'moveMember', userId: user.id, toTeamId: null })
    const n1 = run(detached, { kind: 'addTeamMember', teamId: 't7', userId: user.id })
    expect(n1.users.find((x) => x.id === user.id)!.teamIds).toContain('t7')
    expect(() => run(n1, { kind: 'addTeamMember', teamId: 't7', userId: user.id })).toThrow()
    const n2 = run(n1, { kind: 'removeTeamMember', teamId: 't7', userId: user.id })
    expect(n2.teams.at(-1)!.memberIds).toEqual([])
    expect(() => run(s, { kind: 'removeTeamMember', teamId: 't1', userId: s.teams[0].leadId })).toThrow()
  })
  it('deleteTeam: Vietnamese error with active jobs; ok when empty', () => {
    expect(() => run(s, { kind: 'deleteTeam', teamId: 't1' })).toThrow(/còn thành viên hoặc batch/)
    const n = run(s, { kind: 'createTeam', ...team }, { kind: 'deleteTeam', teamId: 't7' })
    expect(n.teams).toHaveLength(6)
  })
  it('updateUser', () => {
    const u = s.users[10]
    expect(run(s, { kind: 'updateUser', userId: u.id, patch: { name: 'Tên Mới', isQc: true } }).users[10]).toMatchObject({ name: 'Tên Mới', isQc: true, id: u.id })
    expect(() => run(s, { kind: 'updateUser', userId: u.id, patch: { name: ' ' } })).toThrow()
  })
})

describe('audits', () => {
  const s = fresh()
  const auditOn = (st: DashboardState, ids: string[]) => run(st, { kind: 'createAudit', batchIds: ids })
  it('first audit samples ceil(100%) of qc2_pending, batches -> in_audit', () => {
    const eligible = jobsOfBatch(s, 'b02').filter((j) => j.stage === 'qc2_pending')
    expect(auditableBatches(s, s.users.find((u) => u.id === s.currentUserId)!).map((b) => b.id)).toContain('b02')
    expect(nextAuditLevel(s, 'p1').percent).toBe(100)
    const n = auditOn(s, ['b02'])
    const au = n.audits.at(-1)!
    expect(au).toMatchObject({ status: 'open', currentLevelIndex: 0, projectId: 'p1' })
    expect(au.sampledJobIds).toHaveLength(eligible.length)
    expect(batch(n, 'b02').status).toBe('in_audit')
    expect(batchHistory(n, 'b02')[0].type).toBe('audit_create')
  })
  it('custom percent overrides suggested level; invalid percent rejected', () => {
    const eligible = jobsOfBatch(s, 'b02').filter((j) => j.stage === 'qc2_pending')
    const n = run(s, { kind: 'createAudit', batchIds: ['b02'], percent: 50 })
    const au = n.audits.at(-1)!
    expect(au.percent).toBe(50)
    expect(au.currentLevelIndex).toBe(0)
    expect(au.sampledJobIds).toHaveLength(Math.ceil(0.5 * eligible.length))
    expect(auditOn(s, ['b02']).audits.at(-1)!.percent).toBe(100)
    for (const bad of [0, 101, 12.5]) expect(() => run(s, { kind: 'createAudit', batchIds: ['b02'], percent: bad })).toThrow()
  })
  it('level 30% = ceil(0.3 × eligible), deterministic; level progression 100→30→10, failed→100', () => {
    const base = { ...s, audits: s.audits.filter((a) => a.projectId !== 'p1') }
    expect(nextAuditLevel(base, 'p1').percent).toBe(100)
    const passed = (lvl: number, st: 'passed' | 'failed') => ({ ...s.audits[0], id: 'x' + lvl + st, currentLevelIndex: lvl, status: st, createdAt: `2026-11-1${lvl}T00:00:00Z` })
    expect(nextAuditLevel({ ...base, audits: [passed(0, 'passed')] }, 'p1').percent).toBe(30)
    expect(nextAuditLevel({ ...base, audits: [passed(0, 'passed'), passed(1, 'passed')] }, 'p1').percent).toBe(10)
    expect(nextAuditLevel({ ...base, audits: [passed(0, 'passed'), passed(1, 'passed'), passed(2, 'passed')] }, 'p1').percent).toBe(10)
    expect(nextAuditLevel({ ...base, audits: [passed(0, 'passed'), passed(1, 'failed')] }, 'p1').percent).toBe(100)
    const at30 = { ...base, audits: [passed(0, 'passed')] }
    const n = auditOn(at30, ['b02'])
    const total = jobsOfBatch(at30, 'b02').filter((j) => j.stage === 'qc2_pending').length
    expect(n.audits.at(-1)!.sampledJobIds).toHaveLength(Math.ceil(total * 0.3))
    expect(auditOn(at30, ['b02']).audits.at(-1)!.sampledJobIds).toEqual(n.audits.at(-1)!.sampledJobIds)
  })
  it('validation', () => {
    expect(() => auditOn(s, [])).toThrow()
    expect(() => auditOn(s, ['b07'])).toThrow() // already in_audit
    expect(() => auditOn(s, ['b01', 'b09'])).toThrow() // khác dự án
  })
  it('pass all samples + close -> ready_to_deliver, passed, next level 30', () => {
    let n = auditOn(s, ['b02'])
    const au = n.audits.at(-1)!
    expect(() => run(n, { kind: 'closeAudit', auditId: au.id })).toThrow(/chưa chấm/)
    for (const id of au.sampledJobIds) n = run(n, { kind: 'auditJobPass', auditId: au.id, jobId: id })
    expect(() => run(n, { kind: 'auditJobPass', auditId: au.id, jobId: au.sampledJobIds[0] })).toThrow()
    n = run(n, { kind: 'closeAudit', auditId: au.id })
    expect(n.audits.at(-1)).toMatchObject({ status: 'passed' })
    const stages = new Set<JobStage>(jobsOfBatch(n, 'b02').map((j) => j.stage))
    expect(stages.has('qc2_pending')).toBe(false)
    expect(stages.has('qc2_in_progress')).toBe(false)
    expect(jobsOfBatch(n, 'b02').filter((j) => !['ready_to_deliver', 'delivered'].includes(j.stage)).length === 0)
      .toBe(batch(n, 'b02').status === 'ready')
    expect(nextAuditLevel(n, 'p1').percent).toBe(30)
  })
  it('batch with only qc2 jobs becomes ready on pass (b07 open seed audit)', () => {
    let n = { ...s, currentUserId: s.users.find((u) => u.role === 'admin')!.id }
    const au = s.audits.find((a) => a.status === 'open')!
    for (const id of au.sampledJobIds) n = run(n, { kind: 'auditJobPass', auditId: au.id, jobId: id })
    n = run(n, { kind: 'closeAudit', auditId: au.id })
    expect(batch(n, 'b07').status).toBe('ready')
    expect(jobsOfBatch(n, 'b07').every((j) => j.stage === 'ready_to_deliver')).toBe(true)
  })
  it('return applies qc2 rework rules; audit fails; batch back to in_progress', () => {
    let n = auditOn(s, ['b02'])
    const au = n.audits.at(-1)!
    const [a, b] = au.sampledJobIds
    const before = n.jobs.find((j) => j.id === a)!
    expect(() => run(n, { kind: 'auditJobReturn', auditId: au.id, jobId: a, target: 'qc1', reason: ' ', errorCategory: 'Sai nhãn' })).toThrow()
    n = run(n, { kind: 'auditJobReturn', auditId: au.id, jobId: a, target: 'anno', reason: 'Sai hướng', errorCategory: 'Sai hướng' })
    const ja = n.jobs.find((j) => j.id === a)!
    expect(ja).toMatchObject({ stage: 'anno_in_progress', reworkCount: before.reworkCount + 1, qc2Id: s.currentUserId })
    expect(n.events.at(-1)!.reworkAgainst).toEqual([before.annotatorId, before.qc1Id])
    n = run(n, { kind: 'auditJobReturn', auditId: au.id, jobId: b, target: 'qc1', reason: 'QC1 bỏ sót', errorCategory: 'Thiếu object' })
    expect(stageOf(n, b)).toBe('qc1_in_progress')
    for (const id of au.sampledJobIds.slice(2)) n = run(n, { kind: 'auditJobPass', auditId: au.id, jobId: id })
    n = run(n, { kind: 'closeAudit', auditId: au.id })
    expect(n.audits.at(-1)!.status).toBe('failed')
    expect(batch(n, 'b02').status).toBe('in_progress')
    expect(jobsOfBatch(n, 'b02').some((j) => j.stage === 'ready_to_deliver')).toBe(false)
    expect(nextAuditLevel(n, 'p1').percent).toBe(100)
  })
  it('old per-job qc2 actions still work', () => {
    // plan 09: b01 chỉ 10 job, không còn job chờ QC2 ⇒ dùng b02 (cũng đang chạy, không khoá)
    const j = s.jobs.find((x) => x.stage === 'qc2_pending' && x.batchId === 'b02')!
    expect(stageOf(run(s, { kind: 'qc2Pass', jobId: j.id }), j.id)).toBe('ready_to_deliver')
  })
})

describe('favorites & queue', () => {
  const s = fresh()
  it('toggleFavorite per current user', () => {
    const n = run(s, { kind: 'toggleFavorite', targetId: 'b01' })
    expect(n.favorites[s.currentUserId]).toEqual(['b01'])
    expect(run(n, { kind: 'toggleFavorite', targetId: 'b01' }).favorites[s.currentUserId]).toEqual([])
    expect(queueRowsForUser(n, s.currentUserId).find((r) => r.batch.id === 'b01')!.favorite).toBe(true)
  })
  it('QC rows only for QC users; QC2 only for pm/admin/canQa', () => {
    const anno = s.users.find((u) => u.role === 'annotator' && !u.isQc && !s.teams.find((t) => u.teamIds.includes(t.id))!.canQa)!
    for (const r of queueRowsForUser(s, anno.id)) expect(r.steps.map((x) => x.step)).toEqual(['annotate'])
    const qc = s.users.find((u) => u.isQc && !s.teams.find((t) => u.teamIds.includes(t.id))!.canQa)!
    const qcRows = queueRowsForUser(s, qc.id)
    expect(qcRows.length).toBeGreaterThan(0)
    expect(qcRows.every((r) => r.steps.map((x) => x.step).join() === 'annotate,qc1')).toBe(true)
    const pmRows = queueRowsForUser(s, s.currentUserId)
    expect(pmRows.every((r) => r.steps.length === 3)).toBe(true)
    expect(pmRows.some((r) => r.batch.status === 'pending' || r.batch.status === 'released')).toBe(false)
    const b07 = pmRows.find((r) => r.batch.id === 'b07')
    expect(pmRows.length === 0 || b07 === undefined || b07.steps[2].pending + b07.steps[2].processing === jobsOfBatch(s, 'b07').length).toBe(true)
    const canQa = s.users.find((u) => u.role === 'annotator' && !u.isQc && s.teams.find((t) => u.teamIds.includes(t.id))!.canQa)!
    expect(queueRowsForUser(s, canQa.id).some((r) => r.steps.length === 3)).toBe(true)
  })
})

describe('statistics', () => {
  const s = fresh()
  const f = { from: '2026-10-01', to: '2026-11-30' }
  it('workingHours: gaps ≤3h counted, each session +0.5h', () => {
    const h = 3600_000
    expect(workingHours([0])).toBe(0.5)
    expect(workingHours([0, 2 * h])).toBeCloseTo(2.5)
    expect(workingHours([0, 5 * h])).toBeCloseTo(1)
  })
  it('statsByStage annotate: totals consistent with events', () => {
    const rows = statsByStage(s, { ...f, stage: 'annotate', projectId: 'p1' })
    expect(rows.length).toBeGreaterThan(0)
    const submitted = new Set(s.events.filter((e) => (e.type === 'submit' || e.type === 'resubmit') && s.jobs.find((j) => j.id === e.jobId)!.projectId === 'p1').map((e) => e.jobId))
    expect(rows.reduce((n, r) => n + r.jobs, 0)).toBeGreaterThanOrEqual(submitted.size)
    for (const r of rows) {
      expect(r.fpy).toBeGreaterThanOrEqual(0)
      expect(r.fpy).toBeLessThanOrEqual(100)
      expect(r.cuboidPerHour).toBeGreaterThan(0)
      expect(r.reworkJobs).toBeLessThanOrEqual(r.jobs)
      expect(r.repairTime).toBeGreaterThanOrEqual(0)
    }
    expect(rows.some((r) => r.reworkJobs > 0 && r.avgRepairTime > 0)).toBe(true)
  })
  it('statsByStage qc1/qc2 and batch/date filters', () => {
    expect(statsByStage(s, { ...f, stage: 'qc1' }).length).toBeGreaterThan(0)
    expect(statsByStage(s, { ...f, stage: 'qc2' }).length).toBeGreaterThan(0)
    expect(statsByStage(s, { from: '2020-01-01', to: '2020-01-02', stage: 'annotate' })).toEqual([])
    const all = statsByStage(s, { ...f, stage: 'annotate' }).reduce((n, r) => n + r.jobs, 0)
    const one = statsByStage(s, { ...f, stage: 'annotate', batchId: 'b01' }).reduce((n, r) => n + r.jobs, 0)
    expect(one).toBeLessThan(all)
  })
  it('keyMetrics', () => {
    const m = keyMetrics(s, f)
    expect(m.activeWorkers).toBeGreaterThan(0)
    expect(m.annotate.jobs).toBeGreaterThan(0)
    expect(m.annotate.cuboids).toBeGreaterThan(0)
    expect(m.qc1.jobs).toBeGreaterThan(0)
    expect(m.ready.jobs).toBeGreaterThan(0)
    expect(m.reworkRate).toBeGreaterThan(0)
    expect(m.errorRate).toBeGreaterThan(0)
    expect(keyMetrics(s, { ...f, batchId: 'b05' })).toMatchObject({ activeWorkers: 0, reworkRate: 0 })
  })
})

describe('route access by role', () => {
  it('admin/pm open everything; lead/annotator only their menu pages', () => {
    for (const p of ['/admin', '/admin/teams', '/pm/config', '/pm/distribute', '/stats']) {
      expect(canAccessPath('admin', p)).toBe(true)
      expect(canAccessPath('pm', p)).toBe(true)
      expect(canAccessPath('lead', p)).toBe(false)
      expect(canAccessPath('annotator', p)).toBe(false)
    }
    for (const p of ['/', '/queue', '/queue/p1/d1', '/jobs/j002', '/profile', '/me', '/audits/au1']) {
      expect(canAccessPath('lead', p)).toBe(true)
      expect(canAccessPath('annotator', p)).toBe(true)
    }
    expect(canAccessPath('lead', '/lead/members')).toBe(true)
    expect(canAccessPath('lead', '/pm/users/u1')).toBe(true)
    expect(canAccessPath('annotator', '/lead/members')).toBe(false)
    expect(canAccessPath('annotator', '/pm/users/u1')).toBe(false)
    expect(canAccessPath('annotator', '/meow')).toBe(false)
  })
})

describe('assignProject (admin giao dự án cho PM)', () => {
  const s = fresh()
  const admin = s.users.find((u) => u.role === 'admin')!
  const pms = s.users.filter((u) => u.role === 'pm')
  const asAdmin = { ...s, currentUserId: admin.id, batches: s.batches.map((b) => ({ ...b, status: 'ready' as const })) }
  const p2 = s.projects.find((p) => p.id === 'p2')!
  const newPm = pms.find((u) => !p2.pmIds.includes(u.id))!

  it('seed: every project has an assigned date before now', () => {
    for (const p of s.projects) expect(new Date(p.assignedAt).getTime()).toBeLessThanOrEqual(new Date(s.now).getTime())
  })
  it('admin sets PMs: list replaced, assigned date = now; new PM sees it, removed PM does not', () => {
    const n = run(asAdmin, { kind: 'assignProject', projectId: 'p2', pmIds: [newPm.id] })
    const p = n.projects.find((x) => x.id === 'p2')!
    expect(p.pmIds).toEqual([newPm.id])
    expect(p.assignedAt).toBe(n.now)
    expect(p.dueAt).toBe(p2.dueAt)
    expect(visibleProjects(n, newPm).map((x) => x.id)).toContain('p2')
    expect(visibleProjects(n, s.users.find((u) => u.id === p2.pmIds[0])!).map((x) => x.id)).not.toContain('p2')
  })
  it('works for a project already past its due date', () => {
    const late = { ...asAdmin, projects: asAdmin.projects.map((p) => (p.id === 'p2' ? { ...p, dueAt: '2026-01-01T00:00:00.000Z' } : p)) }
    expect(run(late, { kind: 'assignProject', projectId: 'p2', pmIds: [newPm.id] }).projects.find((x) => x.id === 'p2')!.pmIds).toEqual([newPm.id])
  })
  it('several PMs per project, first = main; duplicates removed', () => {
    const n = run(asAdmin, { kind: 'assignProject', projectId: 'p2', pmIds: [newPm.id, p2.pmIds[0], newPm.id] })
    expect(n.projects.find((x) => x.id === 'p2')!.pmIds).toEqual([newPm.id, p2.pmIds[0]])
    for (const u of [newPm, s.users.find((x) => x.id === p2.pmIds[0])!]) expect(visibleProjects(n, u).map((x) => x.id)).toContain('p2')
  })
  it('rejects non-admin, empty list and non-PM ids; same list is a no-op', () => {
    expect(() => run({ ...s, currentUserId: pms[0].id }, { kind: 'assignProject', projectId: 'p2', pmIds: [newPm.id] })).toThrow('Chỉ sếp tổng')
    expect(() => run(asAdmin, { kind: 'assignProject', projectId: 'p2', pmIds: [] })).toThrow('ít nhất một PM')
    expect(() => run(asAdmin, { kind: 'assignProject', projectId: 'p2', pmIds: [admin.id] })).toThrow('không phải PM')
    expect(run(asAdmin, { kind: 'assignProject', projectId: 'p2', pmIds: p2.pmIds })).toBe(asAdmin)
  })
})
