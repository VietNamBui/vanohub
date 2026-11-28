import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { message } from 'antd'
import { apiClient, getStoredToken } from '../api/client'
import { applyAction, type Action } from './logic'
import { clearState, loadState, saveState } from './persist'
import { createSeedState, createWorkflowTestSeedState } from './seed'
import type { DashboardState, DataType, DatasetPreset, Team, User, WorkStep } from './types'

/**
 * Các action áp dụng ĐỒNG BỘ (optimistic) và THROW Error (tiếng Việt) khi sai luật (thiếu lý do, sai bước...).
 * Khi đã kết nối Django REST API (`apiMode === 'api'`), mọi mutation đều gọi REST endpoint
 * tương ứng (transactional trên PostgreSQL/SQLite) và đồng bộ lại state chuẩn từ backend.
 */
export interface StoreActions {
  setCurrentUser(userId: string): void
  assignJob(jobId: string, annotatorId: string, qc1Id: string): void
  submitJob(jobId: string, editedCuboids?: number): void
  startQc1(jobId: string): void
  qc1Pass(jobId: string): void
  qc1Return(jobId: string, reason: string, errorCategory: string): void
  startQc2(jobId: string): void
  qc2Pass(jobId: string): void
  qc2ReturnToQc1(jobId: string, reason: string, errorCategory: string): void
  qc2ReturnToAnno(jobId: string, reason: string, errorCategory: string): void
  markDelivered(jobIds: string[]): void
  reassignJob(jobId: string, patch: { annotatorId?: string; qc1Id?: string }): void
  updateDataType(dataType: DataType): void
  createTeam(input: { name: string; allowedSteps: WorkStep[]; canQa: boolean }): void
  updateTeam(teamId: string, patch: Partial<Pick<Team, 'name' | 'allowedSteps' | 'canQa'>>): void
  deleteTeam(teamId: string): void
  addTeamMember(teamId: string, userId: string): void
  removeTeamMember(teamId: string, userId: string): void
  updateUser(userId: string, patch: Partial<Omit<User, 'id'>>): void
  reassignBatch(batchId: string, step: WorkStep, picId: string): void
  releaseBatch(batchId: string): void
  setAutoLock(batchId: string, autoLockAt: string | null): void
  setBatchDue(batchId: string, dueAt: string | null, stepBufferDays?: { qc1: number; qc2: number }): void
  setJobDue(jobId: string, step: WorkStep, dueAt: string | null): void
  createAudit(batchIds: string[], percent?: number): void
  auditJobPass(auditId: string, jobId: string): void
  auditJobReturn(auditId: string, jobId: string, target: 'qc1' | 'anno', reason: string, errorCategory: string): void
  closeAudit(auditId: string): void
  toggleFavorite(targetId: string): void
  setBatchPriority(batchId: string, priority: 1 | 2 | 3 | 4 | 5): void
  assignProject(projectId: string, pmIds: string[]): void
  /** R3: giao/chuyển nguyên batch cho một team. */
  assignBatchTeam(batchId: string, teamId: string): void
  /** R6: đổi PM của team. */
  setTeamPm(teamId: string, pmId: string): void
  /** R7: đổi team (`toTeamId=null` = nghỉ), bàn giao việc cho lead cũ. */
  moveMember(userId: string, toTeamId: string | null): void
  /** R10: xoá dữ liệu đã lưu, nạp lại seed của bộ dữ liệu hiện hành. */
  resetDemoData(): void
  /** Chuyển đổi bộ dữ liệu mẫu (mẫu đầy đủ vs kiểm thử luồng 2 DA × 3 DS × 5 Batch × 8 Job). */
  setDatasetPreset(preset: DatasetPreset): void
  /** Đồng bộ lại state từ Django REST API. */
  refreshState(): Promise<void>
  /** Đăng nhập qua Django `/api/auth/login/` và nạp state live. */
  loginWithApi(username: string, password: string): Promise<User>
}

export type StoreValue = DashboardState & StoreActions & {
  currentUser: User
  apiMode: 'api' | 'mock'
  loading: boolean
  syncError: string | null
}

const StoreContext = createContext<StoreValue | null>(null)

function shouldUseRemoteApi(hasInitial: boolean): boolean {
  if (hasInitial) return false
  if (typeof window === 'undefined') return false
  if (import.meta.env.VITE_USE_MOCK === 'true') return false
  return true
}

/** `initial` (test) ⇒ không đọc/ghi localStorage; không có ⇒ nạp state đã lưu (R10). */
export function StoreProvider({ children, initial }: { children: ReactNode; initial?: DashboardState }) {
  const persist = !initial
  const remoteEligible = shouldUseRemoteApi(Boolean(initial))
  const [state, setState] = useState<DashboardState>(() => initial ?? loadState())
  const [apiMode, setApiMode] = useState<'api' | 'mock'>('mock')
  const [loading, setLoading] = useState<boolean>(false)
  const [syncError, setSyncError] = useState<string | null>(null)
  const ref = useRef(state)
  const apiModeRef = useRef(apiMode)
  apiModeRef.current = apiMode

  const commit = useCallback((next: DashboardState) => {
    ref.current = next
    setState(next)
    if (persist) saveState(next)
  }, [persist])

  const applyServerState = useCallback((serverState: DashboardState) => {
    if (!serverState || !Array.isArray(serverState.users) || serverState.users.length === 0) return
    const normalized: DashboardState = {
      ...serverState,
      schemaVersion: 2,
      datasetPreset: serverState.datasetPreset ?? ref.current.datasetPreset ?? 'default',
    }
    ref.current = normalized
    setState(normalized)
    if (persist) saveState(normalized)
    setApiMode('api')
    setSyncError(null)
  }, [persist])

  const refreshState = useCallback(async () => {
    if (!remoteEligible || !getStoredToken()) return
    setLoading(true)
    try {
      const serverState = await apiClient.getWorkflowState()
      applyServerState(serverState)
    } catch (err) {
      setSyncError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }, [remoteEligible, applyServerState])

  useEffect(() => {
    if (remoteEligible && getStoredToken()) {
      void refreshState()
    }
  }, [remoteEligible, refreshState])

  const loginWithApi = useCallback(async (username: string, password: string): Promise<User> => {
    await apiClient.login(username, password)
    const serverState = await apiClient.getWorkflowState()
    applyServerState(serverState)
    const logged =
      serverState.users.find((u) => u.id === serverState.currentUserId) ??
      serverState.users.find((u) => u.cvatUsername.toLowerCase() === username.trim().toLowerCase()) ??
      serverState.users[0]
    if (!logged) throw new Error('Không tìm thấy hồ sơ người dùng trên máy chủ')
    return logged
  }, [applyServerState])

  const run = useCallback((a: Action) => {
    const prev = ref.current
    const next = applyAction(prev, a) // throw trước khi set
    commit(next)

    if (apiModeRef.current === 'api' && getStoredToken()) {
      apiClient
        .dispatchWorkflowAction(a)
        .then((serverState) => {
          applyServerState(serverState)
        })
        .catch((err: Error) => {
          commit(prev)
          setSyncError(err.message)
          message.error(err.message || 'Đồng bộ máy chủ thất bại')
        })
    }
  }, [commit, applyServerState])

  const setDatasetPreset = useCallback((preset: DatasetPreset) => {
    if (persist) clearState()
    const nextState = preset === 'workflow_test' ? createWorkflowTestSeedState() : createSeedState()
    ref.current = nextState
    setState(nextState)
    if (persist) saveState(nextState)
  }, [persist])

  const resetDemoData = useCallback(() => {
    if (persist) clearState() // không ghi lại seed: lần tải sau dùng seed theo mã hiện hành
    const preset = ref.current.datasetPreset ?? 'default'
    const seed = preset === 'workflow_test' ? createWorkflowTestSeedState() : createSeedState()
    ref.current = seed
    setState(seed)
    if (persist) saveState(seed)
  }, [persist])

  const value = useMemo<StoreValue>(() => ({
    ...state,
    apiMode,
    loading,
    syncError,
    refreshState,
    loginWithApi,
    currentUser: state.users.find((u) => u.id === state.currentUserId) ?? state.users[0],
    setCurrentUser: (userId) => run({ kind: 'setCurrentUser', userId }),
    assignJob: (jobId, annotatorId, qc1Id) => run({ kind: 'assignJob', jobId, annotatorId, qc1Id }),
    submitJob: (jobId, editedCuboids) => run({ kind: 'submitJob', jobId, editedCuboids }),
    startQc1: (jobId) => run({ kind: 'startQc1', jobId }),
    qc1Pass: (jobId) => run({ kind: 'qc1Pass', jobId }),
    qc1Return: (jobId, reason, errorCategory) => run({ kind: 'qc1Return', jobId, reason, errorCategory }),
    startQc2: (jobId) => run({ kind: 'startQc2', jobId }),
    qc2Pass: (jobId) => run({ kind: 'qc2Pass', jobId }),
    qc2ReturnToQc1: (jobId, reason, errorCategory) => run({ kind: 'qc2ReturnToQc1', jobId, reason, errorCategory }),
    qc2ReturnToAnno: (jobId, reason, errorCategory) => run({ kind: 'qc2ReturnToAnno', jobId, reason, errorCategory }),
    markDelivered: (jobIds) => run({ kind: 'markDelivered', jobIds }),
    reassignJob: (jobId, patch) => run({ kind: 'reassignJob', jobId, ...patch }),
    updateDataType: (dataType) => run({ kind: 'updateDataType', dataType }),
    createTeam: (input) => run({ kind: 'createTeam', ...input }),
    updateTeam: (teamId, patch) => run({ kind: 'updateTeam', teamId, patch }),
    deleteTeam: (teamId) => run({ kind: 'deleteTeam', teamId }),
    addTeamMember: (teamId, userId) => run({ kind: 'addTeamMember', teamId, userId }),
    removeTeamMember: (teamId, userId) => run({ kind: 'removeTeamMember', teamId, userId }),
    updateUser: (userId, patch) => run({ kind: 'updateUser', userId, patch }),
    reassignBatch: (batchId, step, picId) => run({ kind: 'reassignBatch', batchId, step, picId }),
    releaseBatch: (batchId) => run({ kind: 'releaseBatch', batchId }),
    setAutoLock: (batchId, autoLockAt) => run({ kind: 'setAutoLock', batchId, autoLockAt }),
    setBatchDue: (batchId, dueAt, stepBufferDays) => run({ kind: 'setBatchDue', batchId, dueAt, stepBufferDays }),
    setJobDue: (jobId, step, dueAt) => run({ kind: 'setJobDue', jobId, step, dueAt }),
    createAudit: (batchIds, percent) => run({ kind: 'createAudit', batchIds, percent }),
    auditJobPass: (auditId, jobId) => run({ kind: 'auditJobPass', auditId, jobId }),
    auditJobReturn: (auditId, jobId, target, reason, errorCategory) => run({ kind: 'auditJobReturn', auditId, jobId, target, reason, errorCategory }),
    closeAudit: (auditId) => run({ kind: 'closeAudit', auditId }),
    toggleFavorite: (targetId) => run({ kind: 'toggleFavorite', targetId }),
    setBatchPriority: (batchId, priority) => run({ kind: 'setBatchPriority', batchId, priority }),
    assignProject: (projectId, pmIds) => run({ kind: 'assignProject', projectId, pmIds }),
    assignBatchTeam: (batchId, teamId) => run({ kind: 'assignBatchTeam', batchId, teamId }),
    setTeamPm: (teamId, pmId) => run({ kind: 'setTeamPm', teamId, pmId }),
    moveMember: (userId, toTeamId) => run({ kind: 'moveMember', userId, toTeamId }),
    resetDemoData,
    setDatasetPreset,
    datasetPreset: state.datasetPreset ?? 'default',
  }), [state, apiMode, loading, syncError, refreshState, loginWithApi, run, resetDemoData, setDatasetPreset])

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>
}

export function useStore(): StoreValue {
  const v = useContext(StoreContext)
  if (!v) throw new Error('useStore phải nằm trong <StoreProvider>')
  return v
}
