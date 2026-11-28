import type { Action } from '../mock/logic'
import type { DashboardState, DistributionPreviewRow } from '../mock/types'

const TOKEN_KEY = 'cvat_dashboard_token'
const WORKFLOW_USER_KEY = 'cvat_workflow_user_id'

export const getStoredToken = (): string | null =>
  typeof window === 'undefined' ? null : window.localStorage.getItem(TOKEN_KEY)

export const setStoredToken = (token: string): void => {
  if (typeof window !== 'undefined') window.localStorage.setItem(TOKEN_KEY, token)
}

export const removeStoredToken = (): void => {
  if (typeof window !== 'undefined') {
    window.localStorage.removeItem(TOKEN_KEY)
    window.localStorage.removeItem(WORKFLOW_USER_KEY)
  }
}

export const getStoredWorkflowUserId = (): string | null =>
  typeof window === 'undefined' ? null : window.localStorage.getItem(WORKFLOW_USER_KEY)

export const setStoredWorkflowUserId = (userId: string): void => {
  if (typeof window !== 'undefined') window.localStorage.setItem(WORKFLOW_USER_KEY, userId)
}

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getStoredToken()
  const wfUser = getStoredWorkflowUserId()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((options.headers as Record<string, string>) || {}),
  }
  if (token) headers.Authorization = `Token ${token}`
  if (wfUser) headers['X-Workflow-User'] = wfUser

  const resp = await fetch(path, { ...options, headers })
  const text = await resp.text()
  let data: unknown = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = { detail: text }
    }
  }
  if (!resp.ok) {
    const detail =
      data && typeof data === 'object' && 'detail' in data && typeof (data as { detail: unknown }).detail === 'string'
        ? (data as { detail: string }).detail
        : `Lỗi máy chủ (${resp.status})`
    throw new ApiError(detail, resp.status)
  }
  return data as T
}

export interface AuthUser {
  id: number
  username: string
  email: string
  is_staff: boolean
  is_superuser: boolean
}

export interface QcEventRecord {
  id: number
  idempotency_key: string | null
  scope: string
  event_type: string
  timestamp_utc: string
  job_id: number
  task_id: number | null
  project_id: number | null
  workflow_job_code: string | null
  stage: string
  actor_role: string
  user_id: number | null
  username: string
  issue_id: number | null
  defect_code: string
  severity: string
  status: string
  frame_number: number | null
  frames_span: number[]
  track_id: number | null
  shape_id: number | null
  label_class: string
  dwell_ms: number | null
  params: Record<string, unknown>
  metric_delta: Record<string, unknown>
  extra: Record<string, unknown>
  applied_to_workflow: boolean
}

export const apiClient = {
  login: async (username: string, password: string): Promise<{ token: string; user: AuthUser }> => {
    const res = await request<{ token: string; user: AuthUser }>('/api/auth/login/', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    setStoredToken(res.token)
    return res
  },

  logout: async (): Promise<void> => {
    try {
      await request('/api/auth/logout/', { method: 'POST' })
    } finally {
      removeStoredToken()
    }
  },

  getWorkflowState: (): Promise<DashboardState> => request<DashboardState>('/api/workflow/state/'),

  switchWorkflowUser: async (userId: string): Promise<DashboardState> => {
    setStoredWorkflowUserId(userId)
    return request<DashboardState>('/api/workflow/switch-user/', {
      method: 'POST',
      body: JSON.stringify({ userId }),
    })
  },

  previewDistribution: async (batchId: string, teamIds: string[]): Promise<DistributionPreviewRow[]> => {
    const res = await request<{ rows: DistributionPreviewRow[] }>(
      `/api/workflow/batches/${encodeURIComponent(batchId)}/preview-distribution/`,
      { method: 'POST', body: JSON.stringify({ teamIds }) },
    )
    return res.rows
  },

  dispatchWorkflowAction: (action: Action): Promise<DashboardState> => {
    const post = (url: string, body?: unknown) =>
      request<DashboardState>(url, { method: 'POST', body: body !== undefined ? JSON.stringify(body) : '{}' })

    switch (action.kind) {
      case 'setCurrentUser':
        return apiClient.switchWorkflowUser(action.userId)
      case 'assignJob':
        return post(`/api/workflow/jobs/${encodeURIComponent(action.jobId)}/assign/`, {
          annotatorId: action.annotatorId,
          qc1Id: action.qc1Id,
        })
      case 'reassignJob':
        return post(`/api/workflow/jobs/${encodeURIComponent(action.jobId)}/reassign/`, {
          annotatorId: action.annotatorId,
          qc1Id: action.qc1Id,
        })
      case 'submitJob':
        return post(`/api/workflow/jobs/${encodeURIComponent(action.jobId)}/submit/`, {
          editedCuboids: action.editedCuboids,
        })
      case 'startQc1':
        return post(`/api/workflow/jobs/${encodeURIComponent(action.jobId)}/qc1-start/`)
      case 'qc1Pass':
        return post(`/api/workflow/jobs/${encodeURIComponent(action.jobId)}/qc1-pass/`)
      case 'qc1Return':
        return post(`/api/workflow/jobs/${encodeURIComponent(action.jobId)}/qc1-return/`, {
          reason: action.reason,
          errorCategory: action.errorCategory,
        })
      case 'startQc2':
        return post(`/api/workflow/jobs/${encodeURIComponent(action.jobId)}/qc2-start/`)
      case 'qc2Pass':
        return post(`/api/workflow/jobs/${encodeURIComponent(action.jobId)}/qc2-pass/`)
      case 'qc2ReturnToQc1':
        return post(`/api/workflow/jobs/${encodeURIComponent(action.jobId)}/qc2-return-qc1/`, {
          reason: action.reason,
          errorCategory: action.errorCategory,
        })
      case 'qc2ReturnToAnno':
        return post(`/api/workflow/jobs/${encodeURIComponent(action.jobId)}/qc2-return-anno/`, {
          reason: action.reason,
          errorCategory: action.errorCategory,
        })
      case 'markDelivered':
        return post('/api/workflow/jobs/deliver/', { jobIds: action.jobIds })
      case 'setJobDue':
        return post(`/api/workflow/jobs/${encodeURIComponent(action.jobId)}/due/`, {
          step: action.step,
          dueAt: action.dueAt,
        })
      case 'reassignBatch':
        return post(`/api/workflow/batches/${encodeURIComponent(action.batchId)}/reassign/`, {
          step: action.step,
          picId: action.picId,
        })
      case 'releaseBatch':
        return post(`/api/workflow/batches/${encodeURIComponent(action.batchId)}/release/`)
      case 'setAutoLock':
        return post(`/api/workflow/batches/${encodeURIComponent(action.batchId)}/autolock/`, {
          autoLockAt: action.autoLockAt,
        })
      case 'setBatchDue':
        return post(`/api/workflow/batches/${encodeURIComponent(action.batchId)}/due/`, {
          dueAt: action.dueAt,
          stepBufferDays: action.stepBufferDays,
        })
      case 'setBatchPriority':
        return post(`/api/workflow/batches/${encodeURIComponent(action.batchId)}/priority/`, {
          priority: action.priority,
        })
      case 'assignBatchTeam':
        return post(`/api/workflow/batches/${encodeURIComponent(action.batchId)}/assign-team/`, {
          teamId: action.teamId,
        })
      case 'setTeamPm':
        return post(`/api/workflow/teams/${encodeURIComponent(action.teamId)}/pm/`, {
          pmId: action.pmId,
        })
      case 'moveMember':
        return post(`/api/workflow/users/${encodeURIComponent(action.userId)}/move-team/`, {
          toTeamId: action.toTeamId,
        })
      case 'createAudit':
        return post('/api/workflow/audits/', { batchIds: action.batchIds, percent: action.percent })
      case 'auditJobPass':
        return post(`/api/workflow/audits/${encodeURIComponent(action.auditId)}/pass-job/`, {
          jobId: action.jobId,
        })
      case 'auditJobReturn':
        return post(`/api/workflow/audits/${encodeURIComponent(action.auditId)}/return-job/`, {
          jobId: action.jobId,
          target: action.target,
          reason: action.reason,
          errorCategory: action.errorCategory,
        })
      case 'closeAudit':
        return post(`/api/workflow/audits/${encodeURIComponent(action.auditId)}/close/`)
      case 'updateDataType':
        return request<DashboardState>(`/api/workflow/data-types/${encodeURIComponent(action.dataType.id)}/`, {
          method: 'PUT',
          body: JSON.stringify(action.dataType),
        })
      case 'createTeam':
        return post('/api/workflow/teams/', {
          name: action.name,
          allowedSteps: action.allowedSteps,
          canQa: action.canQa,
        })
      case 'updateTeam':
        return request<DashboardState>(`/api/workflow/teams/${encodeURIComponent(action.teamId)}/`, {
          method: 'PATCH',
          body: JSON.stringify(action.patch),
        })
      case 'deleteTeam':
        return request<DashboardState>(`/api/workflow/teams/${encodeURIComponent(action.teamId)}/`, {
          method: 'DELETE',
        })
      case 'addTeamMember':
        return post(`/api/workflow/teams/${encodeURIComponent(action.teamId)}/members/`, {
          userId: action.userId,
        })
      case 'removeTeamMember':
        return request<DashboardState>(
          `/api/workflow/teams/${encodeURIComponent(action.teamId)}/members/${encodeURIComponent(action.userId)}/`,
          { method: 'DELETE' },
        )
      case 'updateUser':
        return request<DashboardState>(`/api/workflow/users/${encodeURIComponent(action.userId)}/`, {
          method: 'PATCH',
          body: JSON.stringify(action.patch),
        })
      case 'assignProject':
        return post(`/api/workflow/projects/${encodeURIComponent(action.projectId)}/assign/`, {
          pmIds: action.pmIds,
        })
      case 'toggleFavorite':
        return post('/api/workflow/favorites/toggle/', { targetId: action.targetId })
    }
  },

  // Transactional `qc:*` custom events API
  getQcEvents: (params: Record<string, string | number> = {}): Promise<{ count: number; results: QcEventRecord[] }> => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => qs.set(k, String(v)))
    const suffix = qs.toString() ? `?${qs.toString()}` : ''
    return request<{ count: number; results: QcEventRecord[] }>(`/api/qc-events/${suffix}`)
  },

  postQcEvent: (payload: Record<string, unknown>): Promise<{ created: boolean; event: QcEventRecord }> =>
    request<{ created: boolean; event: QcEventRecord }>('/api/qc-events/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getQcActivity: (days = 7, taskId?: number, jobId?: number): Promise<Record<string, unknown>> => {
    const qs = new URLSearchParams({ days: String(days) })
    if (taskId) qs.set('task_id', String(taskId))
    if (jobId) qs.set('job_id', String(jobId))
    return request<Record<string, unknown>>(`/api/qc-events/activity/?${qs.toString()}`)
  },
}
