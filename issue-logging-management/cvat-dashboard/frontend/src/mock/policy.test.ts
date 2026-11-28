import { describe, expect, it } from 'vitest'
import { can, requireCan, type PolicyAction, type Verdict } from './policy'
import { createSeedState } from './seed'
import { projectTeamIds, qc2OwnerOf, teamsOfPm } from './selectors'
import type { DashboardState, JobStage, User } from './types'

// Seed (plan 09 SPEC-P1 §1): Trần Minh PM → t1,t2 · Lê Thu PM → t3,t4 · Phạm Quốc PM → t5,t6.
// p1 = [Trần Minh, Lê Thu], p2 = [Phạm Quốc]. b01 t1 · b02 t2 · b03 t3 (delivered) · b04 t4 (ready) · b05 pending
// b07 t5 (in_audit) · b08 t6 (delivered) · b09 t5 · b10 t6.
const s0 = createSeedState()
const byName = (s: DashboardState, name: string): User => s.users.find((u) => u.name === name)!
const admin = s0.users.find((u) => u.role === 'admin')!
const pmA = byName(s0, 'Trần Minh PM')
const pmB = byName(s0, 'Lê Thu PM')
const pmC = byName(s0, 'Phạm Quốc PM')
const team = (id: string) => s0.teams.find((t) => t.id === id)!
const userOf = (id: string) => s0.users.find((u) => u.id === id)!
const leadOf = (teamId: string) => userOf(team(teamId).leadId)
const plainAnnotators = (teamId: string) => team(teamId).memberIds.map(userOf).filter((u) => u.role === 'annotator' && !u.isQc)
const qcOf = (teamId: string) => team(teamId).memberIds.map(userOf).find((u) => u.isQc)!
const jobIn = (batchId: string, stage: JobStage) => s0.jobs.find((j) => j.batchId === batchId && j.stage === stage)!

const allow = (v: Verdict) => expect(v).toEqual({ ok: true })
const block = (v: Verdict, reason: RegExp) => {
  expect(v.ok).toBe(false)
  if (!v.ok) expect(v.reason).toMatch(reason)
}
const as = (u: User, act: PolicyAction, s: DashboardState = s0) => can(s, u, act)

describe('selectors R1/R4', () => {
  it('projectTeamIds follows project PMs; adding a PM brings their teams immediately', () => {
    expect(projectTeamIds(s0, 'p1')).toEqual(['t1', 't2', 't3', 't4'])
    expect(projectTeamIds(s0, 'p2')).toEqual(['t5', 't6'])
    const s = { ...s0, projects: s0.projects.map((p) => (p.id === 'p1' ? { ...p, pmIds: [...p.pmIds, pmC.id] } : p)) }
    expect(projectTeamIds(s, 'p1')).toEqual(['t1', 't2', 't3', 't4', 't5', 't6'])
    expect(teamsOfPm(s0, pmB.id).map((t) => t.id)).toEqual(['t3', 't4'])
  })
  it('qc2OwnerOf = PM of the team holding the batch', () => {
    expect(qc2OwnerOf(s0, jobIn('b02', 'qc2_pending'))).toBe(pmA.id)
    expect(qc2OwnerOf(s0, jobIn('b07', 'qc2_pending'))).toBe(pmC.id)
    expect(qc2OwnerOf(s0, jobIn('b05', 'unassigned_pool'))).toBeNull()
  })
})

describe('R3 assignBatchTeam', () => {
  it('allows admin to any valid team of the project', () => {
    allow(as(admin, { kind: 'assignBatchTeam', batchId: 'b05', teamId: 't3' }))
    allow(as(admin, { kind: 'assignBatchTeam', batchId: 'b01', teamId: 't4' })) // sang team của PM khác
  })
  it('allows PM within own teams (first assignment and transfer)', () => {
    allow(as(pmA, { kind: 'assignBatchTeam', batchId: 'b05', teamId: 't1' }))
    allow(as(pmA, { kind: 'assignBatchTeam', batchId: 'b01', teamId: 't2' }))
  })
  it('blocks PM transferring to / from a team of another PM', () => {
    block(as(pmA, { kind: 'assignBatchTeam', batchId: 'b01', teamId: 't3' }), /Chỉ sếp tổng được chuyển batch sang team của PM khác/)
    block(as(pmB, { kind: 'assignBatchTeam', batchId: 'b01', teamId: 't3' }), /Chỉ sếp tổng/)
  })
  it('blocks team outside the project, wrong batch status, missing annotate step, other roles', () => {
    block(as(admin, { kind: 'assignBatchTeam', batchId: 'b05', teamId: 't5' }), /Team Team Epsilon không thuộc PM nào của dự án/)
    block(as(admin, { kind: 'assignBatchTeam', batchId: 'b07', teamId: 't6' }), /Batch đang audit\/đã xong/)
    block(as(admin, { kind: 'assignBatchTeam', batchId: 'b03', teamId: 't4' }), /Batch đang audit\/đã xong/)
    const noAnno = { ...s0, teams: s0.teams.map((t) => (t.id === 't2' ? { ...t, allowedSteps: ['qc1' as const] } : t)) }
    block(as(admin, { kind: 'assignBatchTeam', batchId: 'b05', teamId: 't2' }, noAnno), /không làm bước gán nhãn/)
    block(as(leadOf('t1'), { kind: 'assignBatchTeam', batchId: 'b05', teamId: 't1' }), /Chỉ sếp tổng hoặc PM/)
  })
  it('blocks a PM who does not run the project', () => {
    // Team t5 cho vào p1 bằng cách đổi PM của t5 sang Lê Thu nhưng người thao tác là Phạm Quốc (không thuộc p1).
    const s = { ...s0, teams: s0.teams.map((t) => (t.id === 't5' ? { ...t, pmId: pmB.id } : t)) }
    block(as(pmC, { kind: 'assignBatchTeam', batchId: 'b05', teamId: 't5' }, s), /Bạn không phụ trách dự án/)
  })
  it('admin adding the PM to the project makes that PM team assignable (F3 premise)', () => {
    const s = { ...s0, projects: s0.projects.map((p) => (p.id === 'p1' ? { ...p, pmIds: [...p.pmIds, pmC.id] } : p)) }
    allow(as(admin, { kind: 'assignBatchTeam', batchId: 'b05', teamId: 't5' }, s))
  })
})

describe('R5 assignProject', () => {
  it('allows admin to add a PM or remove one whose batches are finished', () => {
    allow(as(admin, { kind: 'assignProject', projectId: 'p1', pmIds: [pmA.id, pmB.id, pmC.id] }))
    allow(as(admin, { kind: 'assignProject', projectId: 'p1', pmIds: [pmA.id] })) // b03 delivered, b04 ready
  })
  it('blocks removing a PM with unfinished batches, listing count and names', () => {
    const v = as(admin, { kind: 'assignProject', projectId: 'p1', pmIds: [pmB.id] })
    block(v, /PM Trần Minh PM còn 2 batch chưa xong ở dự án Dự án LiDAR Đô thị: Quận 1 – đợt 1, Quận 1 – đợt 2/)
  })
  it('blocks non-admin, empty list and non-PM users', () => {
    block(as(pmA, { kind: 'assignProject', projectId: 'p1', pmIds: [pmA.id] }), /Chỉ sếp tổng được giao dự án/)
    block(as(admin, { kind: 'assignProject', projectId: 'p1', pmIds: [] }), /ít nhất một PM/)
    block(as(admin, { kind: 'assignProject', projectId: 'p1', pmIds: [leadOf('t1').id] }), /không phải PM/)
  })
})

describe('R6 setTeamPm', () => {
  it('allows when the new PM runs every project the team is working on', () => {
    allow(as(admin, { kind: 'setTeamPm', teamId: 't1', pmId: pmB.id })) // b01 ở p1, Lê Thu thuộc p1
    allow(as(admin, { kind: 'setTeamPm', teamId: 't3', pmId: pmC.id })) // t3 chỉ còn batch đã giao
  })
  it('blocks when the new PM misses a running project, listing it', () => {
    block(as(admin, { kind: 'setTeamPm', teamId: 't5', pmId: pmA.id }), /PM Trần Minh PM chưa phụ trách dự án: Dự án Camera Giao thông/)
  })
  it('blocks non-admin and non-PM target', () => {
    block(as(pmA, { kind: 'setTeamPm', teamId: 't1', pmId: pmB.id }), /Chỉ sếp tổng/)
    block(as(admin, { kind: 'setTeamPm', teamId: 't1', pmId: leadOf('t1').id }), /không phải PM/)
  })
})

describe('R7 moveMember', () => {
  const anno = plainAnnotators('t1')[0]
  it('allows admin anywhere and PM between / out of own teams', () => {
    allow(as(admin, { kind: 'moveMember', userId: anno.id, toTeamId: 't5' }))
    allow(as(admin, { kind: 'moveMember', userId: anno.id, toTeamId: null }))
    allow(as(pmA, { kind: 'moveMember', userId: anno.id, toTeamId: 't2' }))
    allow(as(pmA, { kind: 'moveMember', userId: anno.id, toTeamId: null }))
  })
  it('blocks PM crossing to another PM team or moving someone else’s member', () => {
    block(as(pmA, { kind: 'moveMember', userId: anno.id, toTeamId: 't3' }), /Chỉ sếp tổng hoặc PM của cả team nguồn và team đích/)
    block(as(pmB, { kind: 'moveMember', userId: anno.id, toTeamId: 't3' }), /Chỉ sếp tổng hoặc PM/)
    block(as(leadOf('t1'), { kind: 'moveMember', userId: anno.id, toTeamId: null }), /Chỉ sếp tổng hoặc PM/)
  })
  it('blocks moving the only lead, same team, PM/admin users', () => {
    block(as(admin, { kind: 'moveMember', userId: leadOf('t1').id, toTeamId: 't2' }), /lead duy nhất/)
    block(as(admin, { kind: 'moveMember', userId: anno.id, toTeamId: 't1' }), /đã ở/)
    block(as(admin, { kind: 'moveMember', userId: pmA.id, toTeamId: 't1' }), /Chỉ chuyển được lead hoặc annotator/)
  })
})

describe('R8 assignJob / reassignJob', () => {
  const job = jobIn('b10', 'team_pool') // t6 → Phạm Quốc
  const [a1, a2] = plainAnnotators('t6')
  const qc = qcOf('t6')
  it('allows lead, PM of the team and admin with members of the job team', () => {
    allow(as(leadOf('t6'), { kind: 'assignJob', jobId: job.id, annotatorId: a1.id, qc1Id: qc.id }))
    allow(as(pmC, { kind: 'assignJob', jobId: job.id, annotatorId: a1.id, qc1Id: leadOf('t6').id })) // lead làm QC1
    allow(as(admin, { kind: 'assignJob', jobId: job.id, annotatorId: a1.id, qc1Id: qc.id }))
  })
  it('blocks outsiders, non-QC QC1, QC1 = annotator, wrong actor', () => {
    block(as(leadOf('t6'), { kind: 'assignJob', jobId: job.id, annotatorId: plainAnnotators('t5')[0].id, qc1Id: qc.id }), /Annotator phải thuộc team của job/)
    block(as(leadOf('t6'), { kind: 'assignJob', jobId: job.id, annotatorId: a1.id, qc1Id: qcOf('t5').id }), /QC1 phải thuộc team của job/)
    block(as(leadOf('t6'), { kind: 'assignJob', jobId: job.id, annotatorId: a1.id, qc1Id: a2.id }), /QC1 phải là QC hoặc lead/)
    block(as(leadOf('t6'), { kind: 'assignJob', jobId: job.id, annotatorId: qc.id, qc1Id: qc.id }), /QC1 không được là người gán nhãn/)
    block(as(leadOf('t5'), { kind: 'assignJob', jobId: job.id, annotatorId: a1.id, qc1Id: qc.id }), /Chỉ lead, PM của team hoặc sếp tổng/)
    block(as(pmA, { kind: 'assignJob', jobId: job.id, annotatorId: a1.id, qc1Id: qc.id }), /Chỉ lead, PM của team hoặc sếp tổng/)
    block(as(a1, { kind: 'assignJob', jobId: job.id, annotatorId: a1.id, qc1Id: qc.id }), /Chỉ lead, PM của team hoặc sếp tổng/)
  })
  it('reassignJob checks the new person and the resulting pair', () => {
    const busy = s0.jobs.find((j) => j.batchId === 'b01' && j.stage === 'anno_in_progress')!
    const other = plainAnnotators('t1').find((u) => u.id !== busy.annotatorId)!
    allow(as(leadOf('t1'), { kind: 'reassignJob', jobId: busy.id, annotatorId: other.id }))
    block(as(leadOf('t1'), { kind: 'reassignJob', jobId: busy.id, annotatorId: plainAnnotators('t3')[0].id }), /Annotator phải thuộc team của job/)
    block(as(leadOf('t1'), { kind: 'reassignJob', jobId: busy.id, annotatorId: busy.qc1Id! }), /QC1 không được là người gán nhãn/)
    block(as(leadOf('t1'), { kind: 'reassignJob', jobId: busy.id }), /Cần chọn annotator hoặc QC1/)
  })
})

describe('R4 qc2 / audit', () => {
  const b02Job = jobIn('b02', 'qc2_pending') // t2 → Trần Minh
  it('allows PM of the holding team, admin, and canQa member of a team of the same PM', () => {
    allow(as(pmA, { kind: 'qc2', jobId: b02Job.id }))
    allow(as(admin, { kind: 'qc2', jobId: b02Job.id }))
    allow(as(plainAnnotators('t1')[0], { kind: 'qc2', jobId: b02Job.id })) // t1 canQa, cùng PM Trần Minh
    allow(as(pmC, { kind: 'audit', batchIds: ['b07'] }))
    allow(as(admin, { kind: 'audit', batchIds: ['b07', 'b09'] }))
  })
  it('blocks another PM of the same project and canQa members under a different PM', () => {
    block(as(pmB, { kind: 'qc2', jobId: b02Job.id }), /Chỉ PM của team đang giữ batch/)
    block(as(plainAnnotators('t4')[0], { kind: 'qc2', jobId: b02Job.id }), /Chỉ PM của team đang giữ batch/) // t4 canQa nhưng PM Lê Thu
    block(as(plainAnnotators('t2')[0], { kind: 'qc2', jobId: b02Job.id }), /Chỉ PM của team đang giữ batch/) // t2 không canQa
    block(as(pmA, { kind: 'audit', batchIds: ['b07'] }), /Chỉ PM của team đang giữ batch/)
    block(as(pmA, { kind: 'audit', batchIds: ['b02', 'b04'] }), /Chỉ PM của team đang giữ batch/) // b04 là của Lê Thu
    block(as(admin, { kind: 'audit', batchIds: [] }), /ít nhất một batch/)
  })
})

describe('requireCan', () => {
  it('uses the current user and throws the Vietnamese reason', () => {
    const asPmB = { ...s0, currentUserId: pmB.id }
    expect(() => requireCan(asPmB, { kind: 'qc2', jobId: jobIn('b02', 'qc2_pending').id })).toThrow(/Chỉ PM của team đang giữ batch/)
    expect(() => requireCan({ ...s0, currentUserId: pmA.id }, { kind: 'qc2', jobId: jobIn('b02', 'qc2_pending').id })).not.toThrow()
  })
  it('can is pure (does not change state)', () => {
    const before = JSON.stringify(s0)
    as(admin, { kind: 'assignBatchTeam', batchId: 'b01', teamId: 't3' })
    as(pmA, { kind: 'assignProject', projectId: 'p1', pmIds: [] })
    expect(JSON.stringify(s0)).toBe(before)
  })
})

describe('seed invariants (plan 09)', () => {
  const s = s0
  it('every team belongs to a PM and has 10–12 people: 1 lead, 1–2 QC, rest annotators', () => {
    for (const t of s.teams) {
      expect(s.users.find((u) => u.id === t.pmId)?.role, t.id).toBe('pm')
      expect(t.memberIds.length, t.id).toBeGreaterThanOrEqual(10)
      expect(t.memberIds.length, t.id).toBeLessThanOrEqual(12)
      const members = t.memberIds.map((id) => s.users.find((u) => u.id === id)!)
      expect(members.filter((u) => u.role === 'lead').map((u) => u.id), t.id).toEqual([t.leadId])
      const qcs = members.filter((u) => u.isQc).length
      expect(qcs, t.id).toBeGreaterThanOrEqual(1)
      expect(qcs, t.id).toBeLessThanOrEqual(2)
      expect(members.every((u) => u.role === 'lead' || u.role === 'annotator'), t.id).toBe(true)
    }
  })
  it('each lead/annotator is in exactly one team, consistent with memberIds', () => {
    for (const u of s.users.filter((x) => x.role === 'lead' || x.role === 'annotator')) {
      expect(u.teamIds, u.id).toHaveLength(1)
      expect(s.teams.filter((t) => t.memberIds.includes(u.id)).map((t) => t.id), u.id).toEqual(u.teamIds)
    }
    for (const u of s.users.filter((x) => x.role === 'admin' || x.role === 'pm')) expect(u.teamIds, u.id).toEqual([])
  })
  it('PM split matches SPEC-P1 §1 and p2 has ≥2 teams', () => {
    expect(s.projects.find((p) => p.id === 'p1')!.pmIds).toEqual([pmA.id, pmB.id])
    expect(s.projects.find((p) => p.id === 'p2')!.pmIds).toEqual([pmC.id])
    expect(teamsOfPm(s, pmA.id).map((t) => t.id)).toEqual(['t1', 't2'])
    expect(teamsOfPm(s, pmB.id).map((t) => t.id)).toEqual(['t3', 't4'])
    expect(teamsOfPm(s, pmC.id).map((t) => t.id)).toEqual(['t5', 't6'])
    expect(projectTeamIds(s, 'p2').length).toBeGreaterThanOrEqual(2)
  })
  it('each batch has 8–10 jobs and exactly one team from R1 (null only when pending)', () => {
    for (const b of s.batches) {
      const jobs = s.jobs.filter((j) => j.batchId === b.id)
      if (b.status === 'released') { expect(jobs, b.id).toHaveLength(0); continue }
      expect(jobs.length, b.id).toBeGreaterThanOrEqual(8)
      expect(jobs.length, b.id).toBeLessThanOrEqual(10)
      if (b.status === 'pending') {
        expect(b.teamId, b.id).toBeNull()
        expect(jobs.every((j) => j.teamId === null), b.id).toBe(true)
        continue
      }
      expect(b.teamId, b.id).not.toBeNull()
      expect(projectTeamIds(s, b.projectId), b.id).toContain(b.teamId)
      expect(jobs.every((j) => j.teamId === b.teamId), b.id).toBe(true)
    }
  })
  it('job people belong to the job team; qc2Id only set once QC2 actually started', () => {
    const before: JobStage[] = ['unassigned_pool', 'team_pool', 'anno_in_progress', 'qc1_pending', 'qc1_in_progress', 'qc2_pending']
    for (const j of s.jobs) {
      const t = s.teams.find((x) => x.id === j.teamId)
      if (j.annotatorId) expect(t?.memberIds, j.id).toContain(j.annotatorId)
      if (j.qc1Id) expect(t?.memberIds, j.id).toContain(j.qc1Id)
      if (j.annotatorId && j.qc1Id) expect(j.annotatorId, j.id).not.toBe(j.qc1Id)
      if (j.qc2Id) expect(j.qc2Id, j.id).toBe(qc2OwnerOf(s, j))
    }
    // Job ở qc2_pending có thể đã từng qua QC2 rồi bị trả; chỉ job CHƯA từng qc2_start mới phải null.
    const started = new Set(s.events.filter((e) => e.type === 'qc2_start').map((e) => e.jobId))
    for (const j of s.jobs.filter((x) => before.includes(x.stage) && !started.has(x.id))) expect(j.qc2Id, j.id).toBeNull()
  })
  it('has schemaVersion 2', () => expect(s.schemaVersion).toBe(2))
})

it('R10 malformed saved shape falls back to seed', async () => {
  const { loadState } = await import('./persist')
  const seed = createSeedState()
  const invalid: unknown[] = [{ schemaVersion: 2, users: [], currentUserId: 'zz' }, { ...seed, currentUserId: 'zz' }]
  for (const key of ['users', 'teams', 'dataTypes', 'projects', 'jobs', 'events', 'kpiDaily', 'datasets', 'batches', 'batchEvents', 'audits']) invalid.push({ ...seed, [key]: {} })
  for (const value of invalid) expect(loadState({ getItem: () => JSON.stringify(value), setItem: () => {}, removeItem: () => {} })).toEqual(seed)
})
