import { describe, it, expect } from 'vitest'
import { createSeedState } from './seed'
import { notificationsFor } from './notifications'
import { visibleBatches, visibleJobs } from './selectors'
describe('notifications', () => {
  it('returns nothing for unknown user', () => expect(notificationsFor(createSeedState(),'missing')).toEqual([]))
  for (const role of ['admin','pm','lead','annotator'] as const) it(`stable scoped notifications for ${role}`, () => {
    const s = createSeedState(); const u = s.users.find(u => u.role === role)!
    const before = JSON.stringify(s); const n = notificationsFor(s,u.id)
    expect(notificationsFor(s,u.id)).toEqual(n)
    expect(new Set(n.map(v => v.id)).size).toBe(n.length)
    expect(JSON.stringify(s)).toBe(before)
    for (const item of n) {
      if (item.type === 'risk') expect(visibleBatches(s,u).some(b => item.link.endsWith('/'+b.id))).toBe(true)
      if (item.type === 'drift') expect(visibleJobs(s,u).some(j => item.link === `/jobs/${j.id}`)).toBe(true)
      if (role === 'lead' || role === 'annotator') expect(['risk','drift']).not.toContain(item.type)
    }
  })
  it('uses latest targeted return inside inclusive seven-day window; ignores future', () => {
    const s = createSeedState(); const j = s.jobs.find(j => j.annotatorId)!
    const uid = j.annotatorId!; s.events = []
    const at = new Date(new Date(s.now).getTime()-7*86400000).toISOString()
    const event = { id:'r1',jobId:j.id,at,actorId:uid,type:'qc1_return' as const,fromStage:j.stage,toStage:j.stage,reworkAgainst:[uid] }
    s.events.push(event)
    expect(notificationsFor(s,uid).filter(n => n.type === 'return').map(n=>n.id)).toEqual(['return:r1'])
    s.events.push({...event,id:'future',at:'2099-01-01T00:00:00Z'})
    expect(notificationsFor(s,uid).filter(n => n.type === 'return').map(n=>n.id)).toEqual(['return:r1'])
    s.events[0].at = new Date(new Date(at).getTime()-1).toISOString()
    expect(notificationsFor(s,uid).filter(n => n.type === 'return')).toEqual([])
  })
  it('notifies assigned QC1 and only current deadline owner', () => {
    const s = createSeedState(); const j = s.jobs.find(j => j.qc1Id && j.annotatorId && j.qc1Id !== j.annotatorId)!
    s.jobs = [j]; j.stage = 'qc1_pending'; j.due = {qc1:s.now}
    expect(notificationsFor(s,j.qc1Id!).filter(n => n.link === `/jobs/${j.id}`).map(n => n.type)).toEqual(expect.arrayContaining(['qc1','deadline']))
    expect(notificationsFor(s,j.annotatorId!).filter(n => n.type === 'deadline')).toEqual([])
  })
  it('notifies lead about recent distribution only for its team', () => {
    const s = createSeedState(); const lead = s.users.find(u=>u.role==='lead')!
    const b = visibleBatches(s,lead)[0]; b.teamId = lead.teamIds[0]
    s.batchEvents = [{id:'dist',batchId:b.id,at:s.now,actorId:s.currentUserId,type:'distribute',detail:''}]
    expect(notificationsFor(s,lead.id)).toContainEqual(expect.objectContaining({id:'distribution:dist',type:'distribution'}))
    b.teamId = 'other'
    expect(notificationsFor(s,lead.id).filter(n=>n.type==='distribution')).toEqual([])
  })
})
