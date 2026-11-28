import { describe, expect, it } from 'vitest'
import { applyAction, type Action } from './logic'
import { createSeedState, stableHash } from './seed'
import type { DashboardState } from './types'

type Prio = 1 | 2 | 3 | 4 | 5
const fresh = () => createSeedState()
const asUser = (s: DashboardState, userId: string) => applyAction(s, { kind: 'setCurrentUser', userId })
const run = (s: DashboardState, ...as: Action[]) => as.reduce(applyAction, s)
const setP = (batchId: string, priority: Prio): Action => ({ kind: 'setBatchPriority', batchId, priority })
const other = (p: number): Prio => ((p % 5) + 1) as Prio
const prioEvents = (s: DashboardState, batchId: string) => s.batchEvents.filter((e) => e.batchId === batchId && e.type === 'priority_set')

describe('setBatchPriority (Q-I3)', () => {
  const s0 = fresh()
  const batch = s0.batches.find((b) => b.id === 'b01')! // thuộc p1
  const target = other(batch.priority)
  const p1 = s0.projects.find((p) => p.id === 'p1')!
  const pmOwn = s0.users.find((u) => u.role === 'pm' && p1.pmIds.includes(u.id))!
  const pmOther = s0.users.find((u) => u.role === 'pm' && !p1.pmIds.includes(u.id))!
  const admin = s0.users.find((u) => u.role === 'admin')!
  const lead = s0.users.find((u) => u.role === 'lead')!
  const anno = s0.users.find((u) => u.role === 'annotator')!

  it('annotator, lead, pm của dự án khác ⇒ throw', () => {
    for (const u of [anno, lead, pmOther]) expect(() => run(asUser(s0, u.id), setP('b01', target))).toThrow()
  })
  it('pm đúng dự án và admin ⇒ ok, đúng 1 sự kiện priority_set', () => {
    for (const u of [pmOwn, admin]) {
      const n = run(asUser(s0, u.id), setP('b01', target))
      expect(n.batches.find((b) => b.id === 'b01')!.priority).toBe(target)
      const evs = prioEvents(n, 'b01')
      expect(evs).toHaveLength(1)
      expect(evs[0].detail).toBe(`Đổi ưu tiên ★${batch.priority} → ★${target}`)
    }
  })
  it('đặt lại cùng mức ⇒ không sự kiện, state không đổi', () => {
    const a = asUser(s0, pmOwn.id)
    const n = run(a, setP('b01', batch.priority))
    expect(n).toBe(a)
    expect(prioEvents(n, 'b01')).toHaveLength(0)
  })
  it('đổi hai lần khác mức ⇒ 2 sự kiện', () => {
    const n = run(asUser(s0, pmOwn.id), setP('b01', target), setP('b01', batch.priority))
    expect(prioEvents(n, 'b01')).toHaveLength(2)
  })
  it('batch released ⇒ throw', () => {
    const rel = s0.batches.find((b) => b.status === 'released')!
    expect(() => run(asUser(s0, admin.id), setP(rel.id, other(rel.priority)))).toThrow()
  })
})

describe('seed: trường mới của mô hình', () => {
  const s = fresh()
  it('project có code/partner/dueAt/status hợp lệ', () => {
    for (const p of s.projects) {
      expect(p.code).toMatch(/^PRJ-/)
      expect(p.partner.name.length).toBeGreaterThan(0)
      expect(new Date(p.dueAt).getTime()).toBeGreaterThan(new Date(s.now).getTime())
      expect(['running', 'paused', 'done']).toContain(p.status)
    }
  })
  it('dataset: 0 ≤ onCvatPct ≤ preprocessedPct ≤ 100, scene > 0, có ít nhất 1 dataset không hạn', () => {
    for (const d of s.datasets) {
      expect(d.onCvatPct).toBeGreaterThanOrEqual(0)
      expect(d.onCvatPct).toBeLessThanOrEqual(d.preprocessedPct)
      expect(d.preprocessedPct).toBeLessThanOrEqual(100)
      expect(d.sceneCount).toBeGreaterThan(0)
    }
    expect(s.datasets.some((d) => d.dueAt === null)).toBe(true)
  })
  it('batch priority ∈ 1..5 và có nhiều hơn một mức', () => {
    for (const b of s.batches) expect([1, 2, 3, 4, 5]).toContain(b.priority)
    expect(new Set(s.batches.map((b) => b.priority)).size).toBeGreaterThan(1)
  })
  it('mỗi dataset không có quá 2 batch cùng mức ★ (đa dạng ưu tiên)', () => {
    for (const d of s.datasets) {
      const levels = s.batches.filter((b) => b.datasetId === d.id).map((b) => b.priority)
      const counts = new Map<number, number>()
      for (const l of levels) counts.set(l, (counts.get(l) ?? 0) + 1)
      for (const c of counts.values()) expect(c).toBeLessThanOrEqual(2)
    }
  })
  it('seed xác định; hash tách được id gần nhau', () => {
    expect(fresh().projects).toEqual(s.projects)
    expect(fresh().datasets).toEqual(s.datasets)
    expect(stableHash('dataset:d1')).not.toBe(stableHash('dataset:d2'))
  })
})
