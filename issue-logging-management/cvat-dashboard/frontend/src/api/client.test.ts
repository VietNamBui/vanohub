import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient, removeStoredToken, setStoredToken, setStoredWorkflowUserId } from './client'
import { createSeedState } from '../mock/seed'

describe('apiClient workflow & qc-events REST routing', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    removeStoredToken()
  })

  it('routes workflow actions to the matching Django REST endpoints with auth headers', async () => {
    const seed = createSeedState()
    const calls: { url: string; method: string; body: unknown; headers: Record<string, string> }[] = []

    const storage = new Map<string, string>()
    vi.stubGlobal('window', {
      localStorage: {
        getItem: (k: string) => storage.get(k) ?? null,
        setItem: (k: string, v: string) => { storage.set(k, v) },
        removeItem: (k: string) => { storage.delete(k) },
      },
    })
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({
        url,
        method: init?.method || 'GET',
        body: init?.body ? JSON.parse(String(init.body)) : null,
        headers: (init?.headers as Record<string, string>) || {},
      })
      return {
        ok: true,
        status: 200,
        text: async () => JSON.stringify(seed),
      }
    }))

    setStoredToken('tok_123')
    setStoredWorkflowUserId('u2')

    await apiClient.dispatchWorkflowAction({ kind: 'assignBatchTeam', batchId: 'b02', teamId: 't1' })
    await apiClient.dispatchWorkflowAction({ kind: 'assignJob', jobId: 'j0001', annotatorId: 'u7', qc1Id: 'u5' })
    await apiClient.dispatchWorkflowAction({ kind: 'submitJob', jobId: 'j0001', editedCuboids: 180 })
    await apiClient.dispatchWorkflowAction({ kind: 'qc1Return', jobId: 'j0001', reason: 'Lệch Yaw', errorCategory: 'Sai hướng' })
    await apiClient.dispatchWorkflowAction({ kind: 'createAudit', batchIds: ['b01'], percent: 30 })
    await apiClient.dispatchWorkflowAction({ kind: 'setTeamPm', teamId: 't1', pmId: 'u2' })
    await apiClient.dispatchWorkflowAction({ kind: 'moveMember', userId: 'u7', toTeamId: 't2' })
    await apiClient.dispatchWorkflowAction({ kind: 'deleteTeam', teamId: 't5' })

    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      'POST /api/workflow/batches/b02/assign-team/',
      'POST /api/workflow/jobs/j0001/assign/',
      'POST /api/workflow/jobs/j0001/submit/',
      'POST /api/workflow/jobs/j0001/qc1-return/',
      'POST /api/workflow/audits/',
      'POST /api/workflow/teams/t1/pm/',
      'POST /api/workflow/users/u7/move-team/',
      'DELETE /api/workflow/teams/t5/',
    ])
    expect(calls[0].headers.Authorization).toBe('Token tok_123')
    expect(calls[0].headers['X-Workflow-User']).toBe('u2')
    expect(calls[2].body).toEqual({ editedCuboids: 180 })
  })
})
