import dayjs from 'dayjs'
import { requireCan } from './policy'
import { AUDIT_LEVELS, fmtLockTime, seededShuffle } from './seed'
import type {
  Audit, Batch, BatchEvent, BatchEventType, DashboardState, DataType, Job, JobEvent, JobEventType,
  JobStage, Team, User, WorkStep,
} from './types'

/**
 * Logic thuần của store. Mọi hàm nhận state cũ và trả state mới (không mutate).
 * Hành động sai luật (thiếu lý do, sai bước, không tìm thấy job) => throw Error (tiếng Việt).
 */

function needsReturnPool(s: DashboardState, job: Job): boolean {
  const teamId = findBatch(s, job.batchId).teamId
  const members = s.teams.find(t => t.id === teamId)?.memberIds ?? []
  return job.teamId !== teamId || !job.annotatorId || !members.includes(job.annotatorId) || (!!job.qc1Id && !members.includes(job.qc1Id))
}

export type Action =
  | { kind: 'setCurrentUser'; userId: string }
  | { kind: 'assignJob'; jobId: string; annotatorId: string; qc1Id: string }
  | { kind: 'submitJob'; jobId: string; editedCuboids?: number }
  | { kind: 'startQc1'; jobId: string }
  | { kind: 'qc1Pass'; jobId: string }
  | { kind: 'qc1Return'; jobId: string; reason: string; errorCategory: string }
  | { kind: 'startQc2'; jobId: string }
  | { kind: 'qc2Pass'; jobId: string }
  | { kind: 'qc2ReturnToQc1'; jobId: string; reason: string; errorCategory: string }
  | { kind: 'qc2ReturnToAnno'; jobId: string; reason: string; errorCategory: string }
  | { kind: 'markDelivered'; jobIds: string[] }
  | { kind: 'reassignJob'; jobId: string; annotatorId?: string; qc1Id?: string }
  | { kind: 'updateDataType'; dataType: DataType }
  | { kind: 'createTeam'; name: string; allowedSteps: WorkStep[]; canQa: boolean }
  | { kind: 'updateTeam'; teamId: string; patch: Partial<Pick<Team, 'name' | 'allowedSteps' | 'canQa'>> }
  | { kind: 'deleteTeam'; teamId: string }
  | { kind: 'addTeamMember'; teamId: string; userId: string }
  | { kind: 'removeTeamMember'; teamId: string; userId: string }
  | { kind: 'updateUser'; userId: string; patch: Partial<Omit<User, 'id'>> }
  | { kind: 'reassignBatch'; batchId: string; step: WorkStep; picId: string }
  | { kind: 'releaseBatch'; batchId: string }
  | { kind: 'setAutoLock'; batchId: string; autoLockAt: string | null }
  | { kind: 'setBatchDue'; batchId: string; dueAt: string | null; stepBufferDays?: { qc1: number; qc2: number } }
  | { kind: 'setJobDue'; jobId: string; step: WorkStep; dueAt: string | null }
  | { kind: 'createAudit'; batchIds: string[]; percent?: number }
  | { kind: 'auditJobPass'; auditId: string; jobId: string }
  | { kind: 'auditJobReturn'; auditId: string; jobId: string; target: 'qc1' | 'anno'; reason: string; errorCategory: string }
  | { kind: 'closeAudit'; auditId: string }
  | { kind: 'toggleFavorite'; targetId: string }
  | { kind: 'setBatchPriority'; batchId: string; priority: 1 | 2 | 3 | 4 | 5 }
  | { kind: 'assignProject'; projectId: string; pmIds: string[] }
  | { kind: 'assignBatchTeam'; batchId: string; teamId: string }
  | { kind: 'setTeamPm'; teamId: string; pmId: string }
  | { kind: 'moveMember'; userId: string; toTeamId: string | null }

export function todayOf(state: DashboardState): string {
  return state.now.slice(0, 10)
}

function findJob(state: DashboardState, jobId: string): Job {
  const j = state.jobs.find((x) => x.id === jobId)
  if (!j) throw new Error(`Không tìm thấy job ${jobId}`)
  return j
}

function findBatch(state: DashboardState, batchId: string): Batch {
  const b = state.batches.find((x) => x.id === batchId)
  if (!b) throw new Error(`Không tìm thấy batch ${batchId}`)
  return b
}

function findTeam(state: DashboardState, teamId: string): Team {
  const t = state.teams.find((x) => x.id === teamId)
  if (!t) throw new Error(`Không tìm thấy team ${teamId}`)
  return t
}

function findAudit(state: DashboardState, auditId: string): Audit {
  const a = state.audits.find((x) => x.id === auditId)
  if (!a) throw new Error(`Không tìm thấy audit ${auditId}`)
  return a
}

/** Batch bị khoá khi autoLockAt < state.now. */
export function isBatchLocked(state: Pick<DashboardState, 'now'>, batch: Pick<Batch, 'autoLockAt'>): boolean {
  return batch.autoLockAt !== null && new Date(batch.autoLockAt).getTime() < new Date(state.now).getTime()
}

function requireUnlocked(state: DashboardState, job: Job): void {
  const b = state.batches.find((x) => x.id === job.batchId)
  if (b && isBatchLocked(state, b)) throw new Error('Batch đã bị khoá')
}

/** Mức audit kế tiếp của dự án: lần đầu 100; sau khi đạt → 30 → 10; trượt → quay về 100. */
export function nextAuditLevelIndex(state: Pick<DashboardState, 'audits'>, projectId: string): number {
  const closed = state.audits.filter((a) => a.projectId === projectId && a.status !== 'open')
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt) || a.id.localeCompare(b.id))
  const last = closed.at(-1)
  if (!last || last.status === 'failed') return 0
  return Math.min(last.currentLevelIndex + 1, AUDIT_LEVELS.length - 1)
}

function requireStage(job: Job, allowed: JobStage[], what: string): void {
  if (!allowed.includes(job.stage)) throw new Error(`Không thể ${what}: job ${job.id} đang ở bước "${job.stage}"`)
}

function requireReason(reason: string, errorCategory: string): string {
  const r = reason.trim()
  if (!r) throw new Error('Bắt buộc nhập lý do trả về')
  if (!errorCategory.trim()) throw new Error('Bắt buộc chọn loại lỗi')
  return r
}

/** Giả lập đồng hồ: mỗi hành động tiến 1 phút kể từ state.now. */
function tick(state: DashboardState): { at: string; now: string } {
  const now = new Date(new Date(state.now).getTime() + 60_000).toISOString()
  return { at: now, now }
}

/** Thêm BatchEvent (actor = currentUser) và tiến đồng hồ 1 phút. */
function withBatchEvents(
  state: DashboardState, evs: { batchId: string; type: BatchEventType; detail: string }[],
): DashboardState {
  const { at, now } = tick(state)
  const added: BatchEvent[] = evs.map((e, i) => ({
    id: `be${String(state.batchEvents.length + i + 1).padStart(4, '0')}`, at, actorId: state.currentUserId, ...e,
  }))
  return { ...state, now, batchEvents: [...state.batchEvents, ...added] }
}

const patchBatch = (state: DashboardState, batchId: string, patch: Partial<Batch>): DashboardState => ({
  ...state, batches: state.batches.map((b) => (b.id === batchId ? { ...b, ...patch } : b)),
})

const ACTIVE_STAGES: JobStage[] = [
  'team_pool', 'anno_in_progress', 'qc1_pending', 'qc1_in_progress', 'qc2_pending', 'qc2_in_progress', 'ready_to_deliver',
]

interface Patch {
  job: Partial<Job>
  type: JobEventType
  toStage: JobStage
  reason?: string
  errorCategory?: string
  reworkAgainst?: string[]
}

function applyToJobs(state: DashboardState, patches: { job: Job; patch: Patch }[]): DashboardState {
  const { at, now } = tick(state)
  const byId = new Map(patches.map((p) => [p.job.id, p]))
  const newEvents: JobEvent[] = patches.map(({ job, patch }, i) => ({
    id: `ev${String(state.events.length + i + 1).padStart(5, '0')}`,
    jobId: job.id,
    at,
    actorId: state.currentUserId,
    type: patch.type,
    fromStage: job.stage,
    toStage: patch.toStage,
    ...(patch.reason ? { reason: patch.reason } : {}),
    ...(patch.errorCategory ? { errorCategory: patch.errorCategory } : {}),
    ...(patch.reworkAgainst ? { reworkAgainst: patch.reworkAgainst } : {}),
  }))
  return {
    ...state,
    now,
    jobs: state.jobs.map((j) => {
      const p = byId.get(j.id)
      return p ? { ...j, ...p.patch.job, stage: p.patch.toStage } : j
    }),
    events: [...state.events, ...newEvents],
  }
}

function applyOne(state: DashboardState, job: Job, patch: Patch): DashboardState {
  return applyToJobs(state, [{ job, patch }])
}

/** Xem trước chia job: xáo seed -> tham lam job nhiều cuboid nhất trước vào team ít cuboid nhất, số job lệch ≤1. */
function requireAuditJob(state: DashboardState, audit: Audit, jobId: string): Job {
  if (audit.status !== 'open') throw new Error('Audit đã kết thúc')
  if (!audit.sampledJobIds.includes(jobId)) throw new Error(`Job ${jobId} không thuộc mẫu của audit ${audit.id}`)
  if (audit.results[jobId]) throw new Error(`Job ${jobId} đã được chấm`)
  return findJob(state, jobId)
}

export function applyAction(state: DashboardState, a: Action): DashboardState {
  switch (a.kind) {
    case 'setCurrentUser':
      if (!state.users.some((u) => u.id === a.userId)) throw new Error(`Không tìm thấy người dùng ${a.userId}`)
      return { ...state, currentUserId: a.userId }

    case 'assignJob': {
      requireCan(state, a)
      const job = findJob(state, a.jobId)
      requireStage(job, ['team_pool'], 'giao job')
      return applyOne(state, job, {
        job: { annotatorId: a.annotatorId, qc1Id: a.qc1Id }, type: 'assign', toStage: 'anno_in_progress',
      })
    }

    case 'submitJob': {
      requireCan(state, { kind: 'workJob', jobId: a.jobId, op: 'submit' })
      const job = findJob(state, a.jobId)
      requireUnlocked(state, job)
      requireStage(job, ['anno_in_progress'], 'nộp job')
      const first = job.firstSubmittedAt === null
      const { at } = tick(state)
      const next = applyOne(state, job, {
        job: first
          ? { editedCuboids: a.editedCuboids ?? Math.round(job.prelabelCuboids * 0.4), firstSubmittedAt: at }
          : {},
        type: first ? 'submit' : 'resubmit',
        toStage: 'qc1_pending',
      })
      // KPI chỉ cộng ở lần nộp ĐẦU, vào ngày nộp, cho annotator của job.
      if (!first || !job.annotatorId) return next
      const credited = next.jobs.find((j) => j.id === job.id)!.editedCuboids
      const date = todayOf(next)
      const exists = next.kpiDaily.some((k) => k.userId === job.annotatorId && k.date === date)
      return {
        ...next,
        kpiDaily: exists
          ? next.kpiDaily.map((k) => (k.userId === job.annotatorId && k.date === date ? { ...k, editedCuboids: k.editedCuboids + credited } : k))
          : [...next.kpiDaily, { userId: job.annotatorId, date, editedCuboids: credited }],
      }
    }

    case 'startQc1': {
      requireCan(state, { kind: 'workJob', jobId: a.jobId, op: 'startQc1' })
      const job = findJob(state, a.jobId)
      requireUnlocked(state, job)
      requireStage(job, ['qc1_pending'], 'bắt đầu QC1')
      return applyOne(state, job, { job: {}, type: 'qc1_start', toStage: 'qc1_in_progress' })
    }
    case 'qc1Pass': {
      requireCan(state, { kind: 'workJob', jobId: a.jobId, op: 'qc1Pass' })
      const job = findJob(state, a.jobId)
      requireUnlocked(state, job)
      requireStage(job, ['qc1_pending', 'qc1_in_progress'], 'duyệt QC1')
      return applyOne(state, job, { job: {}, type: 'qc1_pass', toStage: 'qc2_pending' })
    }
    case 'qc1Return': {
      requireCan(state, { kind: 'workJob', jobId: a.jobId, op: 'qc1Return' })
      const job = findJob(state, a.jobId)
      requireUnlocked(state, job)
      requireStage(job, ['qc1_pending', 'qc1_in_progress'], 'trả về từ QC1')
      const reason = requireReason(a.reason, a.errorCategory)
      return applyOne(state, job, {
        job: { reworkCount: job.reworkCount + 1, ...(needsReturnPool(state, job) ? { teamId: findBatch(state, job.batchId).teamId, annotatorId: null, qc1Id: null } : {}) }, type: 'qc1_return', toStage: needsReturnPool(state, job) ? 'team_pool' : 'anno_in_progress',
        reason, errorCategory: a.errorCategory, reworkAgainst: job.annotatorId ? [job.annotatorId] : [],
      })
    }

    case 'startQc2': {
      requireCan(state, { kind: 'qc2', jobId: a.jobId })
      const job = findJob(state, a.jobId)
      requireUnlocked(state, job)
      requireStage(job, ['qc2_pending'], 'bắt đầu QC2')
      return applyOne(state, job, { job: { qc2Id: state.currentUserId }, type: 'qc2_start', toStage: 'qc2_in_progress' })
    }
    case 'qc2Pass': {
      requireCan(state, { kind: 'qc2', jobId: a.jobId })
      const job = findJob(state, a.jobId)
      requireUnlocked(state, job)
      requireStage(job, ['qc2_pending', 'qc2_in_progress'], 'Audit')
      return applyOne(state, job, { job: { qc2Id: state.currentUserId }, type: 'qc2_pass', toStage: 'ready_to_deliver' })
    }
    case 'qc2ReturnToQc1': {
      requireCan(state, { kind: 'qc2', jobId: a.jobId })
      const job = findJob(state, a.jobId)
      requireUnlocked(state, job)
      requireStage(job, ['qc2_pending', 'qc2_in_progress'], 'trả về QC1')
      const reason = requireReason(a.reason, a.errorCategory)
      return applyOne(state, job, {
        job: { reworkCount: job.reworkCount + 1, qc2Id: state.currentUserId, ...(needsReturnPool(state, job) ? { teamId: findBatch(state, job.batchId).teamId, annotatorId: null, qc1Id: null } : {}) }, type: 'qc2_return_qc1', toStage: needsReturnPool(state, job) ? 'team_pool' : 'qc1_in_progress',
        reason, errorCategory: a.errorCategory, reworkAgainst: job.qc1Id ? [job.qc1Id] : [],
      })
    }
    case 'qc2ReturnToAnno': {
      requireCan(state, { kind: 'qc2', jobId: a.jobId })
      const job = findJob(state, a.jobId)
      requireUnlocked(state, job)
      requireStage(job, ['qc2_pending', 'qc2_in_progress'], 'trả thẳng annotator')
      const reason = requireReason(a.reason, a.errorCategory)
      return applyOne(state, job, {
        job: { reworkCount: job.reworkCount + 1, qc2Id: state.currentUserId, ...(needsReturnPool(state, job) ? { teamId: findBatch(state, job.batchId).teamId, annotatorId: null, qc1Id: null } : {}) }, type: 'qc2_return_anno', toStage: needsReturnPool(state, job) ? 'team_pool' : 'anno_in_progress',
        reason, errorCategory: a.errorCategory,
        reworkAgainst: [job.annotatorId, job.qc1Id].filter((x): x is string => !!x),
      })
    }

    case 'markDelivered': {
      requireCan(state, { kind: 'deliver', jobIds: a.jobIds })
      const jobs = a.jobIds.map((id) => findJob(state, id))
      jobs.forEach((j) => requireStage(j, ['ready_to_deliver'], 'đánh dấu đã giao'))
      const next = applyToJobs(state, jobs.map((job) => ({ job, patch: { job: {}, type: 'deliver' as const, toStage: 'delivered' as const } })))
      // Batch có toàn bộ job đã giao => 'delivered'.
      const done = new Set(jobs.map((j) => j.batchId))
      return {
        ...next,
        batches: next.batches.map((b) => done.has(b.id) && (b.status === 'ready' || b.status === 'in_progress')
          && next.jobs.filter((j) => j.batchId === b.id).every((j) => j.stage === 'delivered') ? { ...b, status: 'delivered' as const } : b),
      }
    }

    case 'reassignJob': {
      requireCan(state, a)
      const job = findJob(state, a.jobId)
      if (a.annotatorId === undefined && a.qc1Id === undefined) throw new Error('Cần chọn annotator hoặc QC1 mới')
      return applyOne(state, job, {
        job: {
          ...(a.annotatorId !== undefined ? { annotatorId: a.annotatorId } : {}),
          ...(a.qc1Id !== undefined ? { qc1Id: a.qc1Id } : {}),
        },
        type: 'reassign', toStage: job.stage,
      })
    }

    case 'updateDataType':
      requireCan(state, { kind: 'dataType' })
      if (!state.dataTypes.some((d) => d.id === a.dataType.id)) throw new Error(`Không tìm thấy loại dữ liệu ${a.dataType.id}`)
      return { ...state, dataTypes: state.dataTypes.map((d) => (d.id === a.dataType.id ? a.dataType : d)) }

    // ---------- Teams & users
    case 'createTeam': {
      requireCan(state, { kind: 'teamAdmin', op: 'create' })
      const name = a.name.trim()
      if (!name) throw new Error('Cần nhập tên team')
      if (a.allowedSteps.length === 0) throw new Error('Cần chọn ít nhất một bước được phép')
      if (state.teams.some((t) => t.name.toLowerCase() === name.toLowerCase())) throw new Error('Tên team đã tồn tại')
      const n = Math.max(0, ...state.teams.map((t) => Number(t.id.slice(1)) || 0)) + 1
      // Team mới thuộc PM tạo ra nó; admin tạo ⇒ chưa có PM (gán sau bằng setTeamPm).
      const me = state.users.find((u) => u.id === state.currentUserId)
      const pmId = me?.role === 'pm' ? me.id : ''
      return { ...state, teams: [...state.teams, { id: `t${n}`, name, leadId: '', memberIds: [], allowedSteps: a.allowedSteps, canQa: a.canQa, pmId }] }
    }
    case 'updateTeam': {
      requireCan(state, { kind: 'teamAdmin', op: 'update', teamId: a.teamId })
      findTeam(state, a.teamId)
      const name = a.patch.name?.trim()
      if (a.patch.name !== undefined && !name) throw new Error('Cần nhập tên team')
      if (a.patch.allowedSteps && a.patch.allowedSteps.length === 0) throw new Error('Cần chọn ít nhất một bước được phép')
      return {
        ...state,
        teams: state.teams.map((t) => (t.id === a.teamId ? { ...t, ...(a.patch.allowedSteps ? { allowedSteps: a.patch.allowedSteps } : {}), ...(a.patch.canQa !== undefined ? { canQa: a.patch.canQa } : {}), ...(name ? { name } : {}) } : t)),
      }
    }
    case 'deleteTeam': {
      requireCan(state, { kind: 'teamAdmin', op: 'delete', teamId: a.teamId })
      const team = findTeam(state, a.teamId)
      const active = state.jobs.filter((j) => j.teamId === team.id && ACTIVE_STAGES.includes(j.stage)).length
      if (active > 0) throw new Error(`Không thể xoá team "${team.name}": còn ${active} job đang xử lý`)
      return {
        ...state,
        teams: state.teams.filter((t) => t.id !== team.id),
        users: state.users.map((u) => (u.teamIds.includes(team.id) ? { ...u, teamIds: u.teamIds.filter((x) => x !== team.id) } : u)),
      }
    }
    case 'addTeamMember': {
      requireCan(state, { kind: 'addMember', teamId: a.teamId, userId: a.userId })
      const team = findTeam(state, a.teamId)
      if (!state.users.some((u) => u.id === a.userId)) throw new Error(`Không tìm thấy người dùng ${a.userId}`)
      if (team.memberIds.includes(a.userId)) throw new Error('Người dùng đã là thành viên team này')
      return {
        ...state,
        teams: state.teams.map((t) => (t.id === team.id ? { ...t, memberIds: [...t.memberIds, a.userId] } : t)),
        users: state.users.map((u) => (u.id === a.userId ? { ...u, teamIds: [...u.teamIds, team.id] } : u)),
      }
    }
    case 'removeTeamMember': {
      requireCan(state, { kind: 'moveMember', userId: a.userId, toTeamId: null })
      const team = findTeam(state, a.teamId)
      if (!state.users.find(u => u.id === a.userId)?.teamIds.includes(a.teamId) || !team.memberIds.includes(a.userId)) throw new Error('Người dùng không thuộc team này')
      return applyAction(state, { kind: 'moveMember', userId: a.userId, toTeamId: null })
    }
    case 'updateUser': {
      requireCan(state, a)
      if (!state.users.some((u) => u.id === a.userId)) throw new Error(`Không tìm thấy người dùng ${a.userId}`)
      if (a.patch.name !== undefined && !a.patch.name.trim()) throw new Error('Cần nhập tên')
      return { ...state, users: state.users.map((u) => (u.id === a.userId ? { ...u, ...a.patch, id: u.id } : u)) }
    }

    // ---------- Batches
    case 'reassignBatch': {
      if (a.step === 'qc2') throw new Error('QC2 do PM của team giữ batch')
      requireCan(state, { kind: 'batchQc1', batchId: a.batchId, picId: a.picId })
      if (a.step === 'annotate') throw new Error('Đổi team của batch: dùng Chuyển team (assignBatchTeam)')
      const batch = findBatch(state, a.batchId)
      if (batch.status === 'released' || batch.status === 'pending') throw new Error('Batch chưa chia hoặc đã release, không thể đổi người phụ trách')
      if (!state.users.some((u) => u.id === a.picId)) throw new Error(`Không tìm thấy người dùng ${a.picId}`)
      const patch: Partial<Batch> = { stepPic: { ...batch.stepPic, [a.step]: a.picId } }
      // Đẩy xuống job chưa qua bước đó.
      const pre: Record<WorkStep, JobStage[]> = {
        annotate: ['team_pool'], qc1: ['team_pool', 'anno_in_progress', 'qc1_pending', 'qc1_in_progress'], qc2: ['qc2_pending', 'qc2_in_progress'],
      }
      const next = patchBatch(state, batch.id, patch)
      const jobs = next.jobs.map((j) => {
        if (j.batchId !== batch.id || !pre[a.step].includes(j.stage)) return j
        return j.annotatorId === a.picId ? j : { ...j, qc1Id: a.picId }
      })
      const label = state.users.find((u) => u.id === a.picId)?.name
      return withBatchEvents({ ...next, jobs }, [{ batchId: batch.id, type: 'reassign', detail: `Đổi ${a.step} → ${label ?? a.picId}` }])
    }
    case 'releaseBatch': {
      requireCan(state, { kind: 'manageBatch', batchId: a.batchId, op: 'release' })
      const batch = findBatch(state, a.batchId)
      if (batch.status === 'released') throw new Error('Batch đã được release')
      if (batch.status === 'in_audit') throw new Error('Batch đang audit, không thể release')
      if (batch.status === 'delivered') throw new Error('Batch đã giao, không thể release')
      const gone = new Set(state.jobs.filter((j) => j.batchId === batch.id).map((j) => j.id))
      const next = patchBatch({
        ...state,
        jobs: state.jobs.filter((j) => !gone.has(j.id)),
        events: state.events.filter((e) => !gone.has(e.jobId)),
      }, batch.id, { status: 'released', autoLockAt: null })
      return withBatchEvents(next, [{ batchId: batch.id, type: 'release', detail: `Release batch: xoá ${gone.size} job và annotation, trả dữ liệu về kho` }])
    }
    case 'setAutoLock': {
      requireCan(state, { kind: 'manageBatch', batchId: a.batchId, op: 'autoLock' })
      const batch = findBatch(state, a.batchId)
      if (batch.status === 'released') throw new Error('Batch đã release')
      if (a.autoLockAt !== null && Number.isNaN(new Date(a.autoLockAt).getTime())) throw new Error('Thời điểm khoá tự động không hợp lệ')
      const type: BatchEventType = batch.autoLockAt === null && a.autoLockAt !== null ? 'autolock_set' : 'autolock_reset'
      const detail = a.autoLockAt === null ? 'Gỡ khoá tự động' : `${type === 'autolock_set' ? 'Đặt' : 'Sửa'} khoá tự động lúc ${fmtLockTime(a.autoLockAt)}`
      return withBatchEvents(patchBatch(state, batch.id, { autoLockAt: a.autoLockAt }), [{ batchId: batch.id, type, detail }])
    }

    case 'setBatchDue': {
      requireCan(state, { kind: 'manageBatch', batchId: a.batchId, op: 'due' })
      const batch = findBatch(state, a.batchId)
      if (batch.status === 'released' || batch.status === 'delivered') throw new Error('Batch đã giao hoặc đã release, không thể đổi hạn')
      if (a.dueAt !== null && Number.isNaN(new Date(a.dueAt).getTime())) throw new Error('Hạn giao không hợp lệ')
      const buf = a.stepBufferDays ?? batch.stepBufferDays
      if (![buf.qc1, buf.qc2].every((n) => Number.isFinite(n) && n >= 0)) throw new Error('Số ngày đệm mỗi bước phải là số không âm')
      // Không đổi gì (vd UI gửi trùng) ⇒ không ghi sự kiện (I5: mỗi THAY ĐỔI đúng một sự kiện).
      const sameInstant = (x: string | null, y: string | null) => (x === null || y === null ? x === y : new Date(x).getTime() === new Date(y).getTime())
      if (sameInstant(batch.dueAt, a.dueAt) && buf.qc1 === batch.stepBufferDays.qc1 && buf.qc2 === batch.stepBufferDays.qc2) return state
      const patched = patchBatch(state, batch.id, { dueAt: a.dueAt, stepBufferDays: { qc1: buf.qc1, qc2: buf.qc2 } })
      return a.dueAt === null
        ? withBatchEvents(patched, [{ batchId: batch.id, type: 'due_clear', detail: 'Bỏ hạn giao' }])
        : withBatchEvents(patched, [{ batchId: batch.id, type: 'due_set', detail: `Đặt hạn giao ${dayjs(a.dueAt).format('DD/MM/YYYY HH:mm')}` }])
    }
    case 'setJobDue': {
      requireCan(state, { kind: 'jobDue', jobId: a.jobId })
      const job = findJob(state, a.jobId)
      if (job.stage === 'delivered') throw new Error('Job đã giao, không thể đổi hạn')
      if (!['annotate', 'qc1', 'qc2'].includes(a.step)) throw new Error('Bước không hợp lệ')
      if (a.dueAt !== null && Number.isNaN(new Date(a.dueAt).getTime())) throw new Error('Hạn không hợp lệ')
      const prev = job.due?.[a.step] ?? null
      if (prev === null ? a.dueAt === null : a.dueAt !== null && new Date(prev).getTime() === new Date(a.dueAt).getTime()) return state
      const due = { ...(job.due ?? {}) }
      if (a.dueAt === null) delete due[a.step]; else due[a.step] = a.dueAt
      const reason = a.dueAt === null ? `Bỏ hạn riêng ${a.step}` : `Hạn ${a.step}: ${dayjs(a.dueAt).format('DD/MM/YYYY HH:mm')}`
      return applyOne(state, job, { job: { due }, type: 'due_override', toStage: job.stage, reason })
    }

    // ---------- Audits (QC2 lấy mẫu)
    case 'createAudit': {
      requireCan(state, { kind: 'audit', batchIds: a.batchIds })
      if (a.batchIds.length === 0) throw new Error('Cần chọn ít nhất một batch')
      const batches = a.batchIds.map((id) => findBatch(state, id))
      if (new Set(batches.map((b) => b.projectId)).size > 1) throw new Error('Các batch của một audit phải cùng dự án')
      for (const b of batches) if (b.status !== 'in_progress') throw new Error(`Batch ${b.name} không ở trạng thái chờ audit`)
      const eligible = state.jobs.filter((j) => a.batchIds.includes(j.batchId) && j.stage === 'qc2_pending').map((j) => j.id)
      if (eligible.length === 0) throw new Error('Không có job nào đã qua QC1 để lấy mẫu')
      const projectId = batches[0].projectId
      const levelIndex = nextAuditLevelIndex(state, projectId)
      const percent = a.percent ?? AUDIT_LEVELS[levelIndex]
      if (!Number.isInteger(percent) || percent < 1 || percent > 100) throw new Error('Tỷ lệ audit phải là số nguyên từ 1 đến 100%')
      const size = Math.ceil((percent / 100) * eligible.length)
      const sampled = seededShuffle(eligible, 31 + state.audits.length).slice(0, size)
      const audit: Audit = {
        id: `au${state.audits.length + 1}`, createdAt: tick(state).at, createdBy: state.currentUserId, projectId,
        batchIds: a.batchIds, levels: AUDIT_LEVELS, currentLevelIndex: levelIndex, percent, sampledJobIds: sampled,
        results: {}, status: 'open', closedAt: null,
      }
      let next: DashboardState = {
        ...state, audits: [...state.audits, audit],
        batches: state.batches.map((b) => (a.batchIds.includes(b.id) ? { ...b, status: 'in_audit' as const } : b)),
      }
      next = withBatchEvents(next, a.batchIds.map((batchId) => ({
        batchId, type: 'audit_create' as const, detail: `Tạo audit ${audit.id} (mức ${percent}%, ${sampled.length}/${eligible.length} job mẫu)`,
      })))
      return next
    }
    case 'auditJobPass': {
      const audit = findAudit(state, a.auditId)
      requireCan(state, { kind: 'audit', batchIds: audit.batchIds })
      const job = requireAuditJob(state, audit, a.jobId)
      requireUnlocked(state, job)
      const next = { ...state, audits: state.audits.map((x) => (x.id === audit.id ? { ...x, results: { ...x.results, [job.id]: 'passed' as const } } : x)) }
      return withBatchEvents(next, [{ batchId: job.batchId, type: 'audit_job_pass', detail: `Audit ${audit.id}: job ${job.id} đạt` }])
    }
    case 'auditJobReturn': {
      const audit = findAudit(state, a.auditId)
      requireCan(state, { kind: 'audit', batchIds: audit.batchIds })
      const job = requireAuditJob(state, audit, a.jobId)
      const returned = applyAction(state, {
        kind: a.target === 'qc1' ? 'qc2ReturnToQc1' : 'qc2ReturnToAnno', jobId: job.id, reason: a.reason, errorCategory: a.errorCategory,
      })
      const next = { ...returned, audits: returned.audits.map((x) => (x.id === audit.id ? { ...x, results: { ...x.results, [job.id]: 'returned' as const } } : x)) }
      return withBatchEvents(next, [{
        batchId: job.batchId, type: 'audit_job_return',
        detail: `Audit ${audit.id}: job ${job.id} trả ${a.target === 'qc1' ? 'QC1' : 'annotator'} — ${a.reason.trim()}`,
      }])
    }
    case 'closeAudit': {
      const audit = findAudit(state, a.auditId)
      requireCan(state, { kind: 'audit', batchIds: audit.batchIds })
      if (audit.status !== 'open') throw new Error('Audit đã kết thúc')
      const left = audit.sampledJobIds.filter((id) => !audit.results[id]).length
      if (left > 0) throw new Error(`Còn ${left} job mẫu chưa chấm`)
      const failed = Object.values(audit.results).includes('returned')
      let next = state
      if (!failed) {
        const jobs = state.jobs.filter((j) => audit.batchIds.includes(j.batchId) && (j.stage === 'qc2_pending' || j.stage === 'qc2_in_progress'))
        if (jobs.length > 0) {
          next = applyToJobs(state, jobs.map((job) => ({
            job, patch: { job: { qc2Id: state.currentUserId }, type: 'qc2_pass' as const, toStage: 'ready_to_deliver' as const },
          })))
        }
      }
      next = {
        ...next,
        audits: next.audits.map((x) => (x.id === audit.id ? { ...x, status: failed ? 'failed' : 'passed', closedAt: next.now } : x)),
        // Đạt: batch 'ready' khi mọi job đã sẵn sàng/đã giao, ngược lại quay về in_progress. Trượt: quay về in_progress chờ audit lại.
        batches: next.batches.map((b) => {
          if (!audit.batchIds.includes(b.id)) return b
          const allDone = next.jobs.filter((j) => j.batchId === b.id).every((j) => j.stage === 'ready_to_deliver' || j.stage === 'delivered')
          return { ...b, status: !failed && allDone ? 'ready' as const : 'in_progress' as const }
        }),
      }
      return withBatchEvents(next, audit.batchIds.map((batchId) => ({
        batchId, type: failed ? 'audit_fail' as const : 'audit_pass' as const,
        detail: failed ? `Audit ${audit.id} trượt: có job bị trả về` : `Audit ${audit.id} đạt mức ${audit.percent}%`,
      })))
    }

    case 'setBatchPriority': {
      requireCan(state, { kind: 'manageBatch', batchId: a.batchId, op: 'priority' })
      const batch = findBatch(state, a.batchId)
      if (batch.status === 'released') throw new Error('Batch đã release, không thể đổi ưu tiên')
      if (![1, 2, 3, 4, 5].includes(a.priority)) throw new Error('Mức ưu tiên phải từ 1 đến 5')
      if (batch.priority === a.priority) return state
      return withBatchEvents(patchBatch(state, batch.id, { priority: a.priority }), [{ batchId: batch.id, type: 'priority_set', detail: `Đổi ưu tiên ★${batch.priority} → ★${a.priority}` }])
    }

    case 'assignProject': {
      requireCan(state, a)
      const project = state.projects.find((p) => p.id === a.projectId)
      if (!project) throw new Error(`Không tìm thấy dự án ${a.projectId}`)
      const pmIds = [...new Set(a.pmIds)]
      if (pmIds.join() === project.pmIds.join()) return state
      const { at, now } = tick(state)
      return { ...state, now, projects: state.projects.map((p) => (p.id === project.id ? { ...p, pmIds, assignedAt: at } : p)) }
    }

    case 'assignBatchTeam': {
      requireCan(state, a)
      const batch = findBatch(state, a.batchId)
      const stages: JobStage[] = ['unassigned_pool', 'team_pool', 'anno_in_progress', 'qc1_pending', 'qc1_in_progress']
      const jobs = state.jobs.filter((j) => j.batchId === batch.id && stages.includes(j.stage))
      let next = applyToJobs(state, jobs.map((job) => ({
        job, patch: { job: { teamId: a.teamId, annotatorId: null, qc1Id: null }, type: 'distribute' as const, toStage: 'team_pool' as const },
      })))
      next = patchBatch(next, batch.id, { teamId: a.teamId, status: 'in_progress' })
      next = { ...next, datasets: next.datasets.map((d) => d.id === batch.datasetId ? { ...d, lastDistributedAt: next.now } : d) }
      return withBatchEvents(next, [{ batchId: batch.id, type: batch.teamId ? 'transfer' : 'distribute', detail: `Giao ${jobs.length} job cho ${findTeam(state, a.teamId).name}` }])
    }
    case 'setTeamPm': {
      requireCan(state, a)
      return { ...state, teams: state.teams.map((t) => t.id === a.teamId ? { ...t, pmId: a.pmId } : t) }
    }
    case 'moveMember': {
      requireCan(state, a)
      const member = state.users.find((u) => u.id === a.userId)!
      const from = findTeam(state, member.teamIds[0])
      const patches = state.jobs.flatMap(job => {
        if (job.teamId !== from.id) return []
        const anno = job.annotatorId === member.id && job.stage === 'anno_in_progress'
        const qc = job.qc1Id === member.id && ['anno_in_progress', 'qc1_pending', 'qc1_in_progress'].includes(job.stage)
        if (!anno && !qc) return []
        return [{ job, patch: { job: { ...(anno ? { annotatorId: null } : {}), ...(qc ? { qc1Id: from.leadId === job.annotatorId ? null : from.leadId } : {}) }, type: 'handover' as const, toStage: anno ? 'team_pool' as const : job.stage } }]
      })
      const next = applyToJobs(state, patches)
      return {
        ...next,
        users: next.users.map(u => u.id === member.id ? { ...u, teamIds: a.toTeamId ? [a.toTeamId] : [] } : u),
        teams: next.teams.map(t => t.id === from.id ? { ...t, memberIds: t.memberIds.filter(id => id !== member.id) } : t.id === a.toTeamId ? { ...t, memberIds: [...t.memberIds, member.id] } : t),
      }
    }

    case 'toggleFavorite': {
      const cur = state.favorites[state.currentUserId] ?? []
      const nextFav = cur.includes(a.targetId) ? cur.filter((x) => x !== a.targetId) : [...cur, a.targetId]
      return { ...state, favorites: { ...state.favorites, [state.currentUserId]: nextFav } }
    }
  }
}
