import { expect, it } from 'vitest'
import { createSeedState } from './seed'
import { can } from './policy'
import { applyAction } from './logic'
import { pastWorkersOfJob, projectTeamIds } from './selectors'

for (const [code, type] of [['N1b', 'submit'], ['M3', 'resubmit'], ['N2', 'qc1_pass'], ['N3', 'qc1_return']] as const) {
  it(code + ' blocks historical workers at every final review boundary', () => {
    const s = createSeedState()
    const user = s.users.find(u => u.role === 'admin')!
    const job = s.jobs[0]
    job.annotatorId = null
    job.qc1Id = null
    expect(can(s, user, { kind: 'qc2', jobId: job.id }).ok).toBe(true)
    s.events.push({ id: 'history', jobId: job.id, actorId: user.id, type, at: s.now, fromStage: null, toStage: job.stage })
    expect(can(s, user, { kind: 'qc2', jobId: job.id }).ok).toBe(false)
    expect(can(s, user, { kind: 'audit', batchIds: [job.batchId] }).ok).toBe(false)
    expect(can(s, user, { kind: 'deliver', jobIds: [job.id] }).ok).toBe(false)
  })
}
for (const code of ['N5', 'N6']) {
  it(code + ' returns departed assignees to the team pool', () => {
    let s = createSeedState()
    const job = s.jobs.find(j => j.batchId === 'b02' && j.stage === 'qc2_pending')!
    const memberId = code === 'N5' ? job.annotatorId! : job.qc1Id!
    s.currentUserId = s.users.find(u => u.role === 'admin')!.id
    s = applyAction(s, { kind: 'moveMember', userId: memberId, toTeamId: null })
    s = applyAction(s, { kind: 'qc2ReturnToAnno', jobId: job.id, reason: 'Invalid labels', errorCategory: 'other' })
    expect(s.jobs.find(j => j.id === job.id)).toMatchObject({ stage: 'team_pool', annotatorId: null, qc1Id: null, teamId: job.teamId })
  })
}
it('N7 blocks revoked QC eligibility, departed members and invalid stages', () => {
  const s = createSeedState()
  const job = s.jobs.find(j => j.batchId === 'b02' && j.stage === 'qc2_pending')!
  const user = s.users.find(u => u.id === job.qc1Id)!
  job.stage = 'qc1_pending'
  expect(can(s, user, { kind: 'workJob', jobId: job.id, op: 'qc1Pass' }).ok).toBe(true)
  user.isQc = false
  expect(can(s, user, { kind: 'workJob', jobId: job.id, op: 'qc1Pass' }).ok).toBe(false)
  user.isQc = true
  job.stage = 'qc2_pending'
  expect(can(s, user, { kind: 'workJob', jobId: job.id, op: 'qc1Pass' }).ok).toBe(false)
})
it('M4 first annotator on the new team after a batch transfer counts as a past worker (resubmit)', () => {
  let s = createSeedState()
  const admin = s.users.find(u => u.role === 'admin')!
  s.currentUserId = admin.id
  const job = s.jobs.find(j => j.batchId === 'b02' && j.stage === 'qc2_pending')!
  const batch = s.batches.find(b => b.id === 'b02')!
  const toTeam = projectTeamIds(s, batch.projectId).find(t => t !== batch.teamId && s.teams.find(x => x.id === t)!.pmId === s.teams.find(x => x.id === batch.teamId)!.pmId)!
  s = applyAction(s, { kind: 'assignBatchTeam', batchId: 'b02', teamId: toTeam })
  s = applyAction(s, { kind: 'qc2ReturnToAnno', jobId: job.id, reason: 'Invalid labels', errorCategory: 'other' })
  const team = s.teams.find(t => t.id === toTeam)!
  const annotator = s.users.find(u => u.teamIds.includes(toTeam) && u.role === 'annotator' && !u.isQc)!
  const qc1 = s.users.find(u => u.teamIds.includes(toTeam) && u.isQc && u.id !== annotator.id)!
  s.currentUserId = team.leadId
  s = applyAction(s, { kind: 'assignJob', jobId: job.id, annotatorId: annotator.id, qc1Id: qc1.id })
  s.currentUserId = annotator.id
  s = applyAction(s, { kind: 'submitJob', jobId: job.id })
  expect(s.events.filter(e => e.jobId === job.id).at(-1)).toMatchObject({ type: 'resubmit', actorId: annotator.id })
  // QC1 trả về rồi lead đổi sang người khác: A không còn là annotator hiện tại nhưng vẫn là người đã gán nhãn
  s.currentUserId = qc1.id
  s = applyAction(s, { kind: 'qc1Return', jobId: job.id, reason: 'Missing boxes', errorCategory: 'other' })
  const other = s.users.find(u => u.teamIds.includes(toTeam) && u.role === 'annotator' && !u.isQc && u.id !== annotator.id)!
  s.currentUserId = team.leadId
  s = applyAction(s, { kind: 'reassignJob', jobId: job.id, annotatorId: other.id })
  expect(s.jobs.find(j => j.id === job.id)!.annotatorId).toBe(other.id)
  expect(pastWorkersOfJob(s, job.id).has(annotator.id)).toBe(true)
})
