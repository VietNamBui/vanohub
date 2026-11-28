import { describe, expect, it } from 'vitest'
import { applyAction } from './logic'
import { STORAGE_KEY, clearState, loadState, saveState } from './persist'
import { createSeedState } from './seed'

const memory = () => {
  const m = new Map<string, string>()
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k), m }
}

describe('R10 persistence', () => {
  it('round-trips a changed state (reload keeps data)', () => {
    const st = memory()
    const s0 = createSeedState()
    const admin = s0.users.find((u) => u.role === 'admin')!
    const pm3 = s0.users.filter((u) => u.role === 'pm')[2]
    const changed = applyAction({ ...s0, currentUserId: admin.id }, { kind: 'assignProject', projectId: 'p1', pmIds: [...s0.projects[0].pmIds, pm3.id] })
    saveState(changed, st)
    expect(st.m.has(STORAGE_KEY)).toBe(true)
    const loaded = loadState(st)
    expect(loaded).toEqual(changed)
    expect(loaded.projects[0].pmIds).toContain(pm3.id)
  })
  it('falls back to seed when missing, corrupt, or another schemaVersion', () => {
    const seed = createSeedState()
    expect(loadState(memory())).toEqual(seed)
    expect(loadState(null)).toEqual(seed)
    const st = memory()
    st.setItem(STORAGE_KEY, '{not json')
    expect(loadState(st)).toEqual(seed)
    st.setItem(STORAGE_KEY, JSON.stringify({ ...seed, schemaVersion: 1, currentUserId: 'zzz' }))
    expect(loadState(st)).toEqual(seed)
    st.setItem(STORAGE_KEY, 'null')
    expect(loadState(st)).toEqual(seed)
  })
  it('clearState removes the key; storage errors are swallowed', () => {
    const st = memory()
    saveState(createSeedState(), st)
    clearState(st)
    expect(st.m.has(STORAGE_KEY)).toBe(false)
    const broken = { getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('quota') }, removeItem: () => { throw new Error('x') } }
    expect(() => saveState(createSeedState(), broken)).not.toThrow()
    expect(() => clearState(broken)).not.toThrow()
    expect(loadState(broken)).toEqual(createSeedState())
  })
})
