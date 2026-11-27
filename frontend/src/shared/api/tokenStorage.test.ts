import { afterEach, describe, expect, it, vi } from 'vitest'
import { tokenStorage } from './tokenStorage'

function createMemoryStorage(): Storage {
  const store = new Map<string, string>()
  return {
    get length() {
      return store.size
    },
    clear() {
      store.clear()
    },
    getItem(key: string) {
      return store.get(key) ?? null
    },
    key(index: number) {
      return Array.from(store.keys())[index] ?? null
    },
    removeItem(key: string) {
      store.delete(key)
    },
    setItem(key: string, value: string) {
      store.set(key, value)
    },
  }
}

describe('tokenStorage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('saves, reads, preserves refresh token on access-only update, and clears tokens', () => {
    vi.stubGlobal('localStorage', createMemoryStorage())
    expect(tokenStorage.getAccess()).toBeNull()
    expect(tokenStorage.getRefresh()).toBeNull()

    tokenStorage.save('access-1', 'refresh-1')
    expect(tokenStorage.getAccess()).toBe('access-1')
    expect(tokenStorage.getRefresh()).toBe('refresh-1')

    tokenStorage.save('access-2')
    expect(tokenStorage.getAccess()).toBe('access-2')
    expect(tokenStorage.getRefresh()).toBe('refresh-1')

    tokenStorage.clear()
    expect(tokenStorage.getAccess()).toBeNull()
    expect(tokenStorage.getRefresh()).toBeNull()
  })

  it('fails gracefully without throwing when localStorage throws SecurityError', () => {
    const blockedError = new Error('Storage access denied')
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw blockedError
      },
      setItem: () => {
        throw blockedError
      },
      removeItem: () => {
        throw blockedError
      },
    })

    expect(() => tokenStorage.save('access-x', 'refresh-x')).not.toThrow()
    expect(tokenStorage.getAccess()).toBeNull()
    expect(tokenStorage.getRefresh()).toBeNull()
    expect(() => tokenStorage.clear()).not.toThrow()
  })
})

