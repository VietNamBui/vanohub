import { describe, expect, it } from 'vitest'
import { applyAction } from '../../mock/logic'
import { createSeedState } from '../../mock/seed'
import { HOME_ROUTE, visibleBatches, visibleProjects } from '../../mock/selectors'
import type { DashboardState, Role } from '../../mock/types'
import { assignedJobs, leadBatches, leadJobsOfBatch, levelAllowed, queueEntry, rootProjects } from './queueScope'

const s0 = createSeedState()
const as = (s: DashboardState, userId: string) => applyAction(s, { kind: 'setCurrentUser', userId })
const first = (role: Role) => s0.users.find((u) => u.role === role)!

describe('queueEntry / levelAllowed (plan 06)', () => {
  it('điểm vào theo vai', () => {
    expect(queueEntry('admin')).toBe('projects')
    expect(queueEntry('pm')).toBe('projects')
    expect(queueEntry('lead')).toBe('batches')
    expect(queueEntry('annotator')).toBe('jobs')
  })
  it('cấp URL được vào theo vai', () => {
    for (const l of [0, 1, 2, 3]) { expect(levelAllowed('admin', l)).toBe(true); expect(levelAllowed('pm', l)).toBe(true) }
    expect([0, 1, 2, 3].map((l) => levelAllowed('lead', l))).toEqual([true, false, false, true])
    expect([0, 1, 2, 3].map((l) => levelAllowed('annotator', l))).toEqual([true, false, false, false])
  })
  it('HOME_ROUTE: mọi vai về /queue', () => {
    expect(Object.values(HOME_ROUTE)).toEqual(['/queue', '/queue', '/queue', '/queue'])
  })
})

describe('phạm vi gốc theo vai', () => {
  it('admin thấy mọi dự án; pm chỉ dự án được giao', () => {
    const admin = first('admin')
    expect(rootProjects(s0, admin)).toHaveLength(s0.projects.length)
    for (const pm of s0.users.filter((u) => u.role === 'pm')) {
      const ps = rootProjects(s0, pm)
      expect(ps.map((p) => p.id)).toEqual(visibleProjects(s0, pm).map((p) => p.id))
      expect(ps.every((p) => p.pmIds.includes(pm.id))).toBe(true)
    }
  })
  it('lead: batch của team, không có released; job chỉ của team', () => {
    for (const lead of s0.users.filter((u) => u.role === 'lead')) {
      const bs = leadBatches(s0, lead)
      expect(bs.every((b) => b.status !== 'released')).toBe(true)
      expect(bs.map((b) => b.id)).toEqual(visibleBatches(s0, lead).filter((b) => b.status !== 'released').map((b) => b.id))
      for (const b of bs) {
        const js = leadJobsOfBatch(s0, lead, b.id)
        expect(js.length).toBeGreaterThan(0)
        expect(js.every((j) => j.teamId !== null && lead.teamIds.includes(j.teamId))).toBe(true)
      }
    }
    expect(s0.users.some((u) => u.role === 'lead' && leadBatches(s0, u).length > 0)).toBe(true)
  })
  it('annotator: đúng job của mình (+ QC1 khi isQc), không job người khác', () => {
    for (const a of s0.users.filter((u) => u.role === 'annotator')) {
      const js = assignedJobs(s0, a)
      const expected = s0.jobs.filter((j) => j.annotatorId === a.id || (a.isQc && j.qc1Id === a.id))
      expect(js.map((j) => j.id)).toEqual(expected.map((j) => j.id))
    }
    expect(s0.users.some((u) => u.role === 'annotator' && assignedJobs(s0, u).length > 0)).toBe(true)
  })
  it('hàm phạm vi trả rỗng khi sai vai', () => {
    expect(leadBatches(s0, first('admin'))).toEqual([])
    expect(assignedJobs(s0, first('lead'))).toEqual([])
    expect(rootProjects(s0, first('annotator'))).toEqual([])
  })
  it('kết quả chỉ phụ thuộc user truyền vào, không phụ thuộc currentUser', () => {
    const lead = first('lead')
    expect(leadBatches(as(s0, lead.id), lead).map((b) => b.id)).toEqual(leadBatches(s0, lead).map((b) => b.id))
  })
})
