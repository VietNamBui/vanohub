import { describe, expect, it } from 'vitest'
import { ApiError } from '../../api/client'
import { isDemoModeEnabled, shouldFallbackToMockLogin } from './LoginPage'

describe('LoginPage hardening guards', () => {
  it('enables demo mode only in dev or explicit VITE_USE_MOCK', () => {
    expect(isDemoModeEnabled({ DEV: false, VITE_USE_MOCK: undefined })).toBe(false)
    expect(isDemoModeEnabled({ DEV: false, VITE_USE_MOCK: 'false' })).toBe(false)
    expect(isDemoModeEnabled({ DEV: true, VITE_USE_MOCK: undefined })).toBe(true)
    expect(isDemoModeEnabled({ DEV: false, VITE_USE_MOCK: 'true' })).toBe(true)
  })

  it('never falls back to mock login on 4xx ApiError (401/403/400/429), even in demo mode', () => {
    expect(shouldFallbackToMockLogin(new ApiError('Unauthorized', 401), true)).toBe(false)
    expect(shouldFallbackToMockLogin(new ApiError('Forbidden', 403), true)).toBe(false)
    expect(shouldFallbackToMockLogin(new ApiError('Bad Request', 400), true)).toBe(false)
    expect(shouldFallbackToMockLogin(new ApiError('Too Many Requests', 429), true)).toBe(false)
  })

  it('never falls back to mock login in production mode on any error', () => {
    expect(shouldFallbackToMockLogin(new TypeError('Failed to fetch'), false)).toBe(false)
    expect(shouldFallbackToMockLogin(new ApiError('Bad Gateway', 502), false)).toBe(false)
  })

  it('allows offline/network fallback only when demo mode is explicitly enabled', () => {
    expect(shouldFallbackToMockLogin(new TypeError('Failed to fetch'), true)).toBe(true)
    expect(shouldFallbackToMockLogin(new ApiError('Bad Gateway', 502), true)).toBe(true)
  })
})
