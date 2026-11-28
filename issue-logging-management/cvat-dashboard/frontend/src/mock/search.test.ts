import { describe, it, expect } from 'vitest'
import { createSeedState } from './seed'
import { searchFor } from './search'
import { visibleJobs, visibleBatches, visibleProjects } from './selectors'
describe('global search', () => {
  it('handles blank and unknown users', () => {
    const s = createSeedState()
    expect(searchFor(s, s.currentUserId, ' ')).toEqual([])
    expect(searchFor(s, 'missing', 'j')).toEqual([])
  })
  for (const role of ['admin', 'pm', 'lead', 'annotator'] as const) it(`scopes ${role}`, () => {
    const s = createSeedState(); const u = s.users.find(u => u.role === role)!
    const results = searchFor(s, u.id, 'j')
    expect(results.filter(r => r.type === 'Job').map(r => r.id).sort()).toEqual(visibleJobs(s,u).filter(j => j.id.includes('j')).map(j => j.id).sort())
    for (const b of s.batches) expect(searchFor(s,u.id,b.id).some(r => r.type === 'Batch' && r.id === b.id)).toBe(role !== 'annotator' && visibleBatches(s,u).some(v => v.id === b.id))
    for (const p of s.projects) expect(searchFor(s,u.id,p.code).some(r => r.type === 'Dự án' && r.id === p.id)).toBe((role === 'admin' || role === 'pm') && visibleProjects(s,u).some(v => v.id === p.id))
  })
  it('matches CVAT IDs and normalized dataset names with correct links', () => {
    const s = createSeedState(); const u = s.users.find(u => u.role === 'admin')!
    const j = s.jobs[0]
    expect(searchFor(s,u.id,String(j.cvatJobId))).toContainEqual(expect.objectContaining({id:j.id,link:`/jobs/${j.id}`}))
    s.datasets[0].name = 'Dữ liệu mới'
    expect(searchFor(s,u.id,'DU LIEU MOI')).toContainEqual(expect.objectContaining({id:s.datasets[0].id,type:'Dataset',link:`/queue/${s.datasets[0].projectId}/${s.datasets[0].id}`}))
  })
})
