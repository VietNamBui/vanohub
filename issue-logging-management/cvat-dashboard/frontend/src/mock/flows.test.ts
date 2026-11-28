import { expect, it } from 'vitest'
import { applyAction as act } from './logic'
import { createSeedState } from './seed'
import { projectTeamIds, visibleProjects } from './selectors'

const fresh = () => {
  const s = createSeedState()
  return { ...s, currentUserId: s.users.find((u) => u.role === 'admin')!.id }
}
const setup = () => {
  let s = fresh()
  const team = s.teams.find((t) => t.allowedSteps.includes('annotate'))!
  const other = s.teams.find((t) => t.pmId !== team.pmId && t.allowedSteps.includes('annotate'))!
  const batch = s.batches.find((b) => b.teamId === team.id && b.status === 'in_progress')!
  const project = s.projects.find((p) => p.id === batch.projectId)!
  s = act(s, { kind: 'assignProject', projectId: project.id, pmIds: [...project.pmIds, other.pmId] })
  return { s, team, other, batch, project }
}

it('F1 admin transfers early jobs and preserves QC2 and annotations', () => {
  const { s, other, batch } = setup()
  const before = structuredClone(s)
  const n = act(s, { kind: 'assignBatchTeam', batchId: batch.id, teamId: other.id })
  const early = ['unassigned_pool', 'team_pool', 'anno_in_progress', 'qc1_pending', 'qc1_in_progress']
  const jobs = s.jobs.filter((j) => j.batchId === batch.id)
  expect(jobs.some((j) => early.includes(j.stage))).toBe(true)
  for (const j of jobs) {
    const after = n.jobs.find((x) => x.id === j.id)!
    expect(after).toEqual(early.includes(j.stage) ? { ...j, teamId: other.id, stage: 'team_pool', annotatorId: null, qc1Id: null } : j)
  }
  expect(n.batchEvents.at(-1)?.type).toBe('transfer')
  expect(s).toEqual(before)
})

it('F2 PM cannot transfer across owners but can transfer within own teams', () => {
  const { s, team, other, batch } = setup()
  const own = s.teams.find((t) => t.id !== team.id && t.pmId === team.pmId && t.allowedSteps.includes('annotate'))!
  const pm = act(s, { kind: 'setCurrentUser', userId: team.pmId })
  expect(() => act(pm, { kind: 'assignBatchTeam', batchId: batch.id, teamId: other.id })).toThrow('Chỉ sếp tổng')
  expect(act(pm, { kind: 'assignBatchTeam', batchId: batch.id, teamId: own.id }).batches.find((b) => b.id === batch.id)?.teamId).toBe(own.id)
})

it('F3 adding the missing PM enables team assignment', () => {
  let s = fresh()
  const batch = s.batches.find((b) => b.status === 'pending')!
  const p = s.projects.find((p) => p.id === batch.projectId)!
  const team = s.teams.find((t) => !p.pmIds.includes(t.pmId) && t.allowedSteps.includes('annotate'))!
  expect(() => act(s, { kind: 'assignBatchTeam', batchId: batch.id, teamId: team.id })).toThrow('không thuộc PM')
  s = act(s, { kind: 'assignProject', projectId: p.id, pmIds: [...p.pmIds, team.pmId] })
  expect(act(s, { kind: 'assignBatchTeam', batchId: batch.id, teamId: team.id }).batches.find((b) => b.id === batch.id)?.teamId).toBe(team.id)
})

it('F4 unfinished batches block PM removal until audit completes', () => {
  let { s } = setup()
  const { team, other, project } = setup()
  const ids = s.batches.filter((b) => b.projectId === project.id && s.teams.find((t) => t.id === b.teamId)?.pmId === team.pmId && !['ready', 'delivered', 'released'].includes(b.status)).map((b) => b.id)
  expect(() => act(s, { kind: 'assignProject', projectId: project.id, pmIds: [other.pmId] })).toThrow(s.batches.find((b) => b.id === ids[0])!.name)
  // Prepare every outstanding job through the action pipeline.
  for (const id of ids) {
    s = act(s, { kind: 'setAutoLock', batchId: id, autoLockAt: null })
    for (const original of s.jobs.filter((j) => j.batchId === id)) {
      let j = s.jobs.find((j) => j.id === original.id)!
      if (j.stage === 'team_pool') {
        const t = s.teams.find((t) => t.id === j.teamId)!
        s = act(s, { kind: 'assignJob', jobId: j.id, annotatorId: t.memberIds.find((id) => id !== t.leadId)!, qc1Id: t.leadId })
      }
      j = s.jobs.find((j) => j.id === original.id)!
      if (j.stage === 'anno_in_progress') s = act({ ...s, currentUserId: j.annotatorId! }, { kind: 'submitJob', jobId: j.id })
      j = s.jobs.find((j) => j.id === original.id)!
      if (['qc1_pending', 'qc1_in_progress'].includes(j.stage)) s = act({ ...s, currentUserId: j.qc1Id! }, { kind: 'qc1Pass', jobId: j.id })
    }
    s = act({ ...s, currentUserId: 'u01' }, { kind: 'createAudit', batchIds: [id], percent: 100 })
    const au = s.audits.at(-1)!
    for (const jobId of au.sampledJobIds) s = act(s, { kind: 'auditJobPass', auditId: au.id, jobId })
    s = act(s, { kind: 'closeAudit', auditId: au.id })
  }
  expect(act(s, { kind: 'assignProject', projectId: project.id, pmIds: [other.pmId] }).projects.find((p) => p.id === project.id)?.pmIds).toEqual([other.pmId])
})

it('F5 changing team PM requires every running project', () => {
  let s = fresh()
  const batch = s.batches.find((b) => b.status === 'in_progress' && b.teamId && s.projects.find((p) => p.id === b.projectId)!.pmIds.length === 1)!
  const team = s.teams.find((t) => t.id === batch.teamId)!
  const other = s.users.find((u) => u.role === 'pm' && !s.projects.find((p) => p.id === batch.projectId)!.pmIds.includes(u.id))!
  expect(() => act(s, { kind: 'setTeamPm', teamId: team.id, pmId: other.id })).toThrow('chưa phụ trách')
  for (const p of s.projects) s = act(s, { kind: 'assignProject', projectId: p.id, pmIds: [...p.pmIds, other.id] })
  expect(act(s, { kind: 'setTeamPm', teamId: team.id, pmId: other.id }).teams.find((t) => t.id === team.id)?.pmId).toBe(other.id)
})

it('F6 departing annotator returns work and hands QC1 to old lead', () => {
  let s = fresh()
  const t = s.teams[0]
  const batch = s.batches.find((b) => b.status === 'pending')!
  s = act(s, { kind: 'assignBatchTeam', batchId: batch.id, teamId: t.id })
  const member = t.memberIds.find((id) => id !== t.leadId && s.users.find((u) => u.id === id)?.isQc)!
  const jobs = s.jobs.filter((j) => j.teamId === t.id && j.stage === 'team_pool').slice(0, 2)
  expect(jobs).toHaveLength(2)
  s = act(s, { kind: 'assignJob', jobId: jobs[0].id, annotatorId: member, qc1Id: t.leadId })
  s = act(s, { kind: 'assignJob', jobId: jobs[1].id, annotatorId: t.leadId, qc1Id: member })
  const n = act(s, { kind: 'removeTeamMember', teamId: t.id, userId: member })
  expect(n.jobs.find((j) => j.id === jobs[0].id)).toMatchObject({ stage: 'team_pool', annotatorId: null })
  expect(n.jobs.find((j) => j.id === jobs[1].id)?.qc1Id).toBeNull()
  expect(n.users.find((u) => u.id === member)?.teamIds).toEqual([])
  expect(n.teams[0].memberIds).not.toContain(member)
})

it('F7 rejects outsiders and self-QC then assigns a valid pair', () => {
  const s = fresh()
  const j = s.jobs.find((j) => j.stage === 'team_pool')!
  const t = s.teams.find((t) => t.id === j.teamId)!
  expect(() => act(s, { kind: 'assignJob', jobId: j.id, annotatorId: 'outside', qc1Id: t.leadId })).toThrow('Annotator phải')
  expect(() => act(s, { kind: 'assignJob', jobId: j.id, annotatorId: t.leadId, qc1Id: t.leadId })).toThrow('QC1 không')
  expect(act(s, { kind: 'assignJob', jobId: j.id, annotatorId: t.memberIds.find((id) => id !== t.leadId)!, qc1Id: t.leadId }).jobs.find((x) => x.id === j.id)?.stage).toBe('anno_in_progress')
})

it('F8 QC2 permits owner PM and admin, rejects another PM', () => {
  let s = fresh()
  const j = s.jobs.find((j) => j.stage === 'qc2_pending')!
  const b = s.batches.find((b) => b.id === j.batchId)!
  const t = s.teams.find((t) => t.id === b.teamId)!
  s = act(s, { kind: 'setAutoLock', batchId: b.id, autoLockAt: null })
  const other = s.users.find((u) => u.role === 'pm' && u.id !== t.pmId)!
  expect(() => act({ ...s, currentUserId: other.id }, { kind: 'startQc2', jobId: j.id })).toThrow('Chỉ PM')
  const started = act({ ...s, currentUserId: t.pmId }, { kind: 'startQc2', jobId: j.id })
  expect(started.jobs.find((x) => x.id === j.id)?.qc2Id).toBe(t.pmId)
  expect(act({ ...started, currentUserId: s.currentUserId }, { kind: 'qc2Pass', jobId: j.id }).jobs.find((x) => x.id === j.id)).toMatchObject({ stage: 'ready_to_deliver', qc2Id: s.currentUserId })
})

it('F9 adding a PM immediately updates project visibility and teams', () => {
  let s = fresh()
  const p = s.projects[0]
  const pm = s.users.find((u) => u.role === 'pm' && !p.pmIds.includes(u.id))!
  const teams = s.teams.filter((t) => t.pmId === pm.id)
  expect(visibleProjects(s, pm).map((p) => p.id)).not.toContain(p.id)
  s = act(s, { kind: 'assignProject', projectId: p.id, pmIds: [...p.pmIds, pm.id] })
  expect(visibleProjects(s, pm).map((p) => p.id)).toContain(p.id)
  expect(projectTeamIds(s, p.id)).toEqual(expect.arrayContaining(teams.map((t) => t.id)))
})

it('R1 R9 updateUser cannot remove PM or escalate role, including admin role edits', () => {
  const s = fresh()
  for (const actor of ['u06', 'u01']) for (const userId of ['u06', 'u03']) {
    expect(() => act({ ...s, currentUserId: actor }, { kind: 'updateUser', userId, patch: { role: 'admin' } })).toThrow()
    expect(() => act({ ...s, currentUserId: actor }, { kind: 'updateUser', userId, patch: { teamIds: ['t5'] } })).toThrow()
  }
})
it('R3 same-team transfer preserves work by rejecting', () => {
  const s = fresh()
  expect(() => act(s, { kind: 'assignBatchTeam', batchId: 'b01', teamId: 't1' })).toThrow('Batch đã ở team này')
})
it('R4 R8 batch reassignment rejects QC2 and outsiders and preserves self-QC exclusion', () => {
  const s = fresh()
  expect(() => act(s, { kind: 'reassignBatch', batchId: 'b01', step: 'qc2', picId: 'u05' })).toThrow('QC2 do PM')
  expect(() => act(s, { kind: 'reassignBatch', batchId: 'b01', step: 'qc1', picId: 'u60' })).toThrow()
  expect(() => act({ ...s, currentUserId: 'u06' }, { kind: 'reassignBatch', batchId: 'b01', step: 'qc1', picId: 'u05' })).toThrow()
  const job = s.jobs.find(j => j.batchId === 'b01' && j.stage === 'anno_in_progress')!
  job.annotatorId = 'u05'
  const n = act(s, { kind: 'reassignBatch', batchId: 'b01', step: 'qc1', picId: 'u05' })
  expect(n.jobs.find(j => j.id === job.id)?.qc1Id).toBe(job.qc1Id)
})
it('R5 R6 R9 unauthorized management is blocked and updateTeam filters runtime fields', () => {
  const s = fresh()
  const denied = { ...s, currentUserId: 'u06' }
  const actions: import('./logic').Action[] = [
    { kind: 'releaseBatch', batchId: 'b01' },
    { kind: 'setAutoLock', batchId: 'b01', autoLockAt: null },
    { kind: 'deleteTeam', teamId: 't1' },
    { kind: 'createTeam', name: 'x', allowedSteps: ['annotate'], canQa: false },
    { kind: 'updateTeam', teamId: 't1', patch: { canQa: false, allowedSteps: ['qc1'] } },
    { kind: 'updateDataType', dataType: s.dataTypes[0] },
    { kind: 'markDelivered', jobIds: [s.jobs.find(j => j.stage === 'ready_to_deliver')!.id] },
  ]
  for (const action of actions) expect(() => act(denied, action)).toThrow()
  const patch = { name: 'Safe', pmId: 'u04', memberIds: [] }
  expect(() => act(denied, { kind: 'updateTeam', teamId: 't1', patch })).toThrow()
  const n = act(s, { kind: 'updateTeam', teamId: 't1', patch })
  expect(n.teams[0]).toEqual({ ...s.teams[0], name: 'Safe' })
})
it('R7 adding a second team and removing from an unrelated team are blocked', () => {
  const s = fresh()
  for (const currentUserId of ['u06', 'u01']) expect(() => act({ ...s, currentUserId }, { kind: 'addTeamMember', teamId: 't5', userId: 'u06' })).toThrow()
  expect(() => act(s, { kind: 'removeTeamMember', teamId: 't5', userId: 'u06' })).toThrow()
})
it('R7 handover records each changed job and avoids lead self-QC', () => {
  const s = fresh()
  const job = s.jobs.find(j => j.batchId === 'b01' && j.stage === 'anno_in_progress')!
  job.annotatorId = 'u05'; job.qc1Id = 'u06'
  const n = act(s, { kind: 'moveMember', userId: 'u06', toTeamId: null })
  const changed = n.jobs.filter((j, i) => JSON.stringify(j) !== JSON.stringify(s.jobs[i]))
  expect(n.events.slice(s.events.length)).toHaveLength(changed.length)
  expect(n.events.slice(s.events.length).every(e => e.type === 'handover')).toBe(true)
  expect(n.now > s.now).toBe(true)
  expect(n.jobs.find(j => j.id === job.id)?.qc1Id).toBeNull()
})
it.each(['delivered', 'qc2_pending', 'team_pool'] as const)('R8 reassignJob blocks %s', stage => {
  const s = fresh(); const job = s.jobs.find(j => j.stage === stage)!
  expect(() => act(s, { kind: 'reassignJob', jobId: job.id, qc1Id: 'u05' })).toThrow()
})
it('R9 submit and QC1 require assigned actor', () => {
  const s = { ...fresh(), currentUserId: 'u60' }
  const job = s.jobs.find(j => j.batchId === 'b01' && j.stage === 'anno_in_progress')!
  expect(() => act(s, { kind: 'submitJob', jobId: job.id })).toThrow()
  for (const kind of ['startQc1', 'qc1Pass', 'qc1Return'] as const) expect(() => act(s, { kind, jobId: job.id, reason: 'x', errorCategory: 'x' })).toThrow()
})
it.each(['qc2ReturnToAnno', 'qc2ReturnToQc1'] as const)('R2 %s returns transferred jobs to current batch team', kind => {
  const s = fresh(); const job = s.jobs.find(j => j.batchId === 'b02' && j.stage === 'qc2_pending')!
  const moved = act(s, { kind: 'assignBatchTeam', batchId: 'b02', teamId: 't1' })
  const n = act(moved, { kind, jobId: job.id, reason: 'x', errorCategory: 'x' })
  expect(n.jobs.find(j => j.id === job.id)).toMatchObject({ teamId: 't1', stage: 'team_pool', annotatorId: null, qc1Id: null, reworkCount: job.reworkCount + 1 })
  expect(n.events.at(-1)?.jobId).toBe(job.id)
})
it('R11 self-QC2 audit and delivery are blocked even for admin', () => {
  const s = fresh(); const job = s.jobs.find(j => j.stage === 'qc2_pending')!
  job.annotatorId = s.currentUserId
  expect(() => act(s, { kind: 'qc2Pass', jobId: job.id })).toThrow()
  expect(() => act(s, { kind: 'createAudit', batchIds: [job.batchId] })).toThrow()
  job.stage = 'ready_to_deliver'
  expect(() => act(s, { kind: 'markDelivered', jobIds: [job.id] })).toThrow()
})
it.each(['annotatorId', 'qc1Id'] as const)('R11 canQa cannot approve own %s work', field => {
  const s = { ...fresh(), currentUserId: 'u11' }
  const job = s.jobs.find(j => j.batchId === 'b02' && j.stage === 'qc2_pending')!
  job[field] = 'u11'
  expect(() => act(s, { kind: 'qc2Pass', jobId: job.id })).toThrow('Không được tự duyệt')
  expect(() => act(s, { kind: 'createAudit', batchIds: ['b02'] })).toThrow('Không được tự audit')
})
it('R8 reassignJob checks each requested field at QC1', () => {
  const s = fresh(); const job = s.jobs.find(j => j.stage === 'qc1_pending')!
  const team = s.teams.find(t => t.id === job.teamId)!
  expect(() => act(s, { kind: 'reassignJob', jobId: job.id, annotatorId: team.leadId })).toThrow('Job đã qua bước này')
  expect(act(s, { kind: 'reassignJob', jobId: job.id, qc1Id: team.leadId }).jobs.find(j => j.id === job.id)?.qc1Id).toBe(team.leadId)
})
it('R2 audit return follows the transferred batch team', () => {
  let s = fresh()
  s = act(s, { kind: 'assignBatchTeam', batchId: 'b02', teamId: 't1' })
  s = act(s, { kind: 'createAudit', batchIds: ['b02'] })
  const audit = s.audits.at(-1)!
  const jobId = audit.sampledJobIds[0]
  const n = act(s, { kind: 'auditJobReturn', auditId: audit.id, jobId, target: 'anno', reason: 'x', errorCategory: 'x' })
  expect(n.jobs.find(j => j.id === jobId)).toMatchObject({ teamId: 't1', stage: 'team_pool', annotatorId: null, qc1Id: null })
})
