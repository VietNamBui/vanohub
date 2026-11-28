import dayjs from 'dayjs'
import { isBatchLocked, nextAuditLevelIndex, todayOf } from './logic'
import { AUDIT_LEVELS } from './seed'
import type {
  Audit, Batch, BatchEvent, DashboardState, DataType, Dataset, Job, JobEvent, JobStage, Project, Role, Team, User, WorkStep,
} from './types'

/** Mọi selector là hàm thuần nhận `state` (kết quả của `useStore()` dùng được trực tiếp). Tỷ lệ % là số 0–100. */

export const STAGES: JobStage[] = [
  'unassigned_pool', 'team_pool', 'anno_in_progress', 'qc1_pending', 'qc1_in_progress',
  'qc2_pending', 'qc2_in_progress', 'ready_to_deliver', 'delivered',
]

export const STAGE_LABEL: Record<JobStage, string> = {
  unassigned_pool: 'Chờ giao',
  team_pool: 'Chờ giao',
  anno_in_progress: 'Đang gán nhãn',
  qc1_pending: 'Chờ QC1',
  qc1_in_progress: 'QC1 đang kiểm tra',
  qc2_pending: 'Chờ QC2 · Audit',
  qc2_in_progress: 'QC2 · Audit đang kiểm tra',
  ready_to_deliver: 'Sẵn sàng giao',
  delivered: 'Đã giao',
}

export const ROLE_LABEL: Record<Role, string> = { admin: 'Admin', pm: 'PM', lead: 'Team lead', annotator: 'Annotator' }

export const HOME_ROUTE: Record<Role, string> = { admin: '/queue', pm: '/queue', lead: '/queue', annotator: '/queue' }

/**
 * Trang được phép theo vai (khớp menu từng vai). Admin/PM: mọi trang. Lead thêm /lead và /pm/users (mở thành viên từ trang
 * Thành viên). /audits mở cho mọi vai vì trang tự kiểm `canAudit`. /datasets, /batches chỉ là redirect về Hàng đợi.
 */
const ROLE_PATHS: Partial<Record<Role, string[]>> = {
  lead: ['/queue', '/lead', '/me', '/jobs', '/profile', '/audits', '/pm/users', '/datasets', '/batches'],
  annotator: ['/queue', '/me', '/jobs', '/profile', '/audits', '/datasets', '/batches'],
}
export function canAccessPath(role: Role, pathname: string): boolean {
  const allowed = ROLE_PATHS[role]
  if (!allowed || pathname === '/') return true
  return allowed.some((p) => pathname === p || pathname.startsWith(`${p}/`))
}

const pct = (n: number, d: number) => (d === 0 ? 0 : Math.round((n / d) * 1000) / 10)

// ---------- lookup
export const userById = (s: DashboardState, id: string | null | undefined): User | undefined => s.users.find((u) => u.id === id)
export const teamById = (s: DashboardState, id: string | null | undefined): Team | undefined => s.teams.find((t) => t.id === id)
export const projectById = (s: DashboardState, id: string | null | undefined): Project | undefined => s.projects.find((p) => p.id === id)
export const jobById = (s: DashboardState, id: string | undefined): Job | undefined => s.jobs.find((j) => j.id === id)
export const dataTypeOfProject = (s: DashboardState, projectId: string): DataType | undefined =>
  s.dataTypes.find((d) => d.id === projectById(s, projectId)?.dataTypeId)
/** Timeline của job, cũ → mới. */
export const eventsOfJob = (s: DashboardState, jobId: string): JobEvent[] =>
  s.events.filter((e) => e.jobId === jobId).sort((a, b) => a.at.localeCompare(b.at) || a.id.localeCompare(b.id))

// ---------- tổ chức: PM → team → dự án (R1, R4)
/** Team của PM (mỗi team thuộc đúng một PM). */
export const teamsOfPm = (s: DashboardState, pmId: string): Team[] => s.teams.filter((t) => t.pmId === pmId)
/** R1: team của dự án = team có `pmId ∈ project.pmIds` (thêm PM vào dự án ⇒ team của PM dùng được ngay). */
export function projectTeamIds(s: DashboardState, projectId: string): string[] {
  const pmIds = projectById(s, projectId)?.pmIds ?? []
  return s.teams.filter((t) => t.pmId !== '' && pmIds.includes(t.pmId)).map((t) => t.id)
}
/**
 * R4: người chịu trách nhiệm QC2/Audit của job = PM của team đang giữ batch (`Batch.teamId`);
 * batch chưa có team thì dùng `job.teamId`. null = chưa có team/PM.
 */
export function qc2OwnerOf(s: DashboardState, job: Pick<Job, 'batchId' | 'teamId'>): string | null {
  const teamId = s.batches.find((b) => b.id === job.batchId)?.teamId ?? job.teamId
  return teamById(s, teamId)?.pmId || null
}

// ---------- phạm vi nhìn thấy theo vai trò
export function visibleProjects(s: DashboardState, user: User): Project[] {
  switch (user.role) {
    case 'admin': return s.projects
    case 'pm': return s.projects.filter((p) => p.pmIds.includes(user.id))
    default: return s.projects.filter((p) => projectTeamIds(s, p.id).some((t) => user.teamIds.includes(t)))
  }
}
export function visibleTeams(s: DashboardState, user: User): Team[] {
  switch (user.role) {
    case 'admin': return s.teams
    case 'pm': {
      const ids = new Set(visibleProjects(s, user).flatMap((p) => projectTeamIds(s, p.id)))
      return s.teams.filter((t) => ids.has(t.id))
    }
    default: return s.teams.filter((t) => user.teamIds.includes(t.id))
  }
}
/** Job user được xem: admin/pm theo dự án; lead theo team; annotator chỉ job của mình. */
export function visibleJobs(s: DashboardState, user: User): Job[] {
  switch (user.role) {
    case 'admin': return s.jobs
    case 'pm': { const ids = new Set(visibleProjects(s, user).map((p) => p.id)); return s.jobs.filter((j) => ids.has(j.projectId)) }
    case 'lead': return s.jobs.filter((j) => j.teamId !== null && user.teamIds.includes(j.teamId))
    default: return s.jobs.filter((j) => j.annotatorId === user.id)
  }
}
/** Thành viên team đủ điều kiện làm QC1 (lead + người isQc). */
export const qcCandidatesOfTeam = (s: DashboardState, teamId: string): User[] =>
  s.users.filter((u) => u.teamIds.includes(teamId) && (u.isQc || u.role === 'lead'))
/** Annotator thường của team (không tính lead; gồm cả người isQc). */
export const annotatorsOfTeam = (s: DashboardState, teamId: string): User[] =>
  s.users.filter((u) => u.teamIds.includes(teamId) && u.role === 'annotator')

// ---------- job theo bước
export function jobsByStage(s: DashboardState, projectId?: string): Record<JobStage, Job[]> {
  const out = Object.fromEntries(STAGES.map((st) => [st, [] as Job[]])) as Record<JobStage, Job[]>
  for (const j of s.jobs) if (!projectId || j.projectId === projectId) out[j.stage].push(j)
  return out
}

// ---------- thống kê
const isDone = (j: Job) => j.stage === 'ready_to_deliver' || j.stage === 'delivered'
const reworkEvents = (events: JobEvent[]) => events.filter((e) => e.reworkAgainst && e.reworkAgainst.length > 0)

export interface ProjectStats { totalJobs: number; assignedJobs: number; completionPct: number; editedCuboids: number; reworkRate: number }

/** completionPct = job qua QC2 (ready_to_deliver|delivered) / job đã giao cho annotator. reworkRate = số lần rework / số job đã nộp. */
export function projectStats(s: DashboardState, projectId: string): ProjectStats {
  const jobs = s.jobs.filter((j) => j.projectId === projectId)
  const ids = new Set(jobs.map((j) => j.id))
  const assigned = jobs.filter((j) => j.annotatorId !== null)
  const submitted = jobs.filter((j) => j.firstSubmittedAt !== null)
  const reworks = reworkEvents(s.events.filter((e) => ids.has(e.jobId))).length
  return {
    totalJobs: jobs.length, assignedJobs: assigned.length,
    completionPct: pct(assigned.filter(isDone).length, assigned.length),
    editedCuboids: jobs.reduce((n, j) => n + j.editedCuboids, 0),
    reworkRate: pct(reworks, submitted.length),
  }
}

export interface TeamStats extends ProjectStats { teamId: string; memberCount: number; reworkCount: number; byStage: Record<JobStage, number> }

export function teamStats(s: DashboardState, teamId: string, projectId?: string): TeamStats {
  const jobs = s.jobs.filter((j) => j.teamId === teamId && (!projectId || j.projectId === projectId))
  const ids = new Set(jobs.map((j) => j.id))
  const assigned = jobs.filter((j) => j.annotatorId !== null)
  const submitted = jobs.filter((j) => j.firstSubmittedAt !== null)
  const reworkCount = reworkEvents(s.events.filter((e) => ids.has(e.jobId))).length
  const byStage = Object.fromEntries(STAGES.map((st) => [st, 0])) as Record<JobStage, number>
  jobs.forEach((j) => { byStage[j.stage] += 1 })
  return {
    teamId, memberCount: teamById(s, teamId)?.memberIds.length ?? 0, byStage, reworkCount,
    totalJobs: jobs.length, assignedJobs: assigned.length,
    completionPct: pct(assigned.filter(isDone).length, assigned.length),
    editedCuboids: jobs.reduce((n, j) => n + j.editedCuboids, 0),
    reworkRate: pct(reworkCount, submitted.length),
  }
}

/** Chỉ tiêu KPI/ngày của user = loại dữ liệu của dự án đầu tiên mà team của user tham gia. */
export function kpiTargetOfUser(s: DashboardState, userId: string): number {
  const u = userById(s, userId)
  const project = u ? s.projects.find((p) => projectTeamIds(s, p.id).some((t) => u.teamIds.includes(t))) : undefined
  return s.dataTypes.find((d) => d.id === project?.dataTypeId)?.kpiPerDay ?? 0
}

export interface UserStats {
  userId: string; kpiToday: number; kpiTarget: number
  /** 7 ngày gần nhất, cũ → mới. */
  kpiWeek: { date: string; editedCuboids: number; target: number }[]
  assignedJobs: number; submittedJobs: number; completionPct: number; reworkCount: number; reworkRate: number
}

/** reworkRate = số lần rework nhắm vào user / số job user đã nộp. */
export function userStats(s: DashboardState, userId: string): UserStats {
  const target = kpiTargetOfUser(s, userId)
  const today = todayOf(s)
  const mine = s.kpiDaily.filter((k) => k.userId === userId)
  const kpiWeek = Array.from({ length: 7 }, (_, i) => {
    const date = dayjs(today).subtract(6 - i, 'day').format('YYYY-MM-DD')
    return { date, editedCuboids: mine.find((k) => k.date === date)?.editedCuboids ?? 0, target }
  })
  const jobs = s.jobs.filter((j) => j.annotatorId === userId)
  const submitted = jobs.filter((j) => j.firstSubmittedAt !== null)
  const reworkCount = s.events.filter((e) => e.reworkAgainst?.includes(userId)).length
  return {
    userId, kpiTarget: target, kpiToday: kpiWeek[6].editedCuboids, kpiWeek,
    assignedJobs: jobs.length, submittedJobs: submitted.length,
    completionPct: pct(jobs.filter(isDone).length, jobs.length),
    reworkCount, reworkRate: pct(reworkCount, submitted.length),
  }
}

export interface TeamRework { teamId: string; teamName: string; reworkCount: number; submittedJobs: number; reworkRate: number }

export function reworkByTeam(s: DashboardState, projectId: string): TeamRework[] {
  return projectTeamIds(s, projectId).map((teamId) => {
    const st = teamStats(s, teamId, projectId)
    const submitted = s.jobs.filter((j) => j.teamId === teamId && j.projectId === projectId && j.firstSubmittedAt !== null).length
    return { teamId, teamName: teamById(s, teamId)?.name ?? teamId, reworkCount: st.reworkCount, submittedJobs: submitted, reworkRate: st.reworkRate }
  })
}

export function topErrorCategories(s: DashboardState, projectId: string, limit = 5): { category: string; count: number }[] {
  const ids = new Set(s.jobs.filter((j) => j.projectId === projectId).map((j) => j.id))
  const counts = new Map<string, number>()
  for (const e of s.events) if (e.errorCategory && ids.has(e.jobId)) counts.set(e.errorCategory, (counts.get(e.errorCategory) ?? 0) + 1)
  return [...counts].map(([category, count]) => ({ category, count })).sort((a, b) => b.count - a.count).slice(0, limit)
}

export interface QcStats { userId: string; qc1Passed: number; qc2Returned: number; missRate: number }

/** qc1Passed = job user đã cho qua QC1; qc2Returned = trong đó số job QC2 trả lại (rework nhắm vào user). */
export function qcStats(s: DashboardState, userId: string): QcStats {
  const passed = new Set(s.events.filter((e) => e.type === 'qc1_pass' && e.actorId === userId).map((e) => e.jobId))
  const returned = new Set(
    s.events.filter((e) => (e.type === 'qc2_return_qc1' || e.type === 'qc2_return_anno') && e.reworkAgainst?.includes(userId) && passed.has(e.jobId)).map((e) => e.jobId),
  )
  return { userId, qc1Passed: passed.size, qc2Returned: returned.size, missRate: pct(returned.size, passed.size) }
}

export const driftedJobs = (s: DashboardState): Job[] => s.jobs.filter((j) => j.cvatDrift)

// =====================================================================
// Dataset / Batch / Audit
// =====================================================================
export const BATCH_STATUS_LABEL: Record<Batch['status'], string> = {
  pending: 'Chưa chia', in_progress: 'Đang làm', in_audit: 'Đang audit', ready: 'Sẵn sàng giao', delivered: 'Đã giao', released: 'Đã release',
}
export const STEP_LABEL: Record<WorkStep, string> = { annotate: 'Gán nhãn', qc1: 'QC1', qc2: 'QC2 · Audit' }

export const datasetById = (s: DashboardState, id: string | null | undefined): Dataset | undefined => s.datasets.find((d) => d.id === id)
export const batchById = (s: DashboardState, id: string | null | undefined): Batch | undefined => s.batches.find((b) => b.id === id)
export const auditById = (s: DashboardState, id: string | null | undefined): Audit | undefined => s.audits.find((a) => a.id === id)
export const jobsOfBatch = (s: DashboardState, batchId: string): Job[] => s.jobs.filter((j) => j.batchId === batchId)
export const batchesOfDataset = (s: DashboardState, datasetId: string): Batch[] => s.batches.filter((b) => b.datasetId === datasetId)
export const batchOfJob = (s: DashboardState, job: Pick<Job, 'batchId'>): Batch | undefined => batchById(s, job.batchId)

export const isBatchLockedById = (s: DashboardState, batchId: string): boolean => {
  const b = batchById(s, batchId)
  return !!b && isBatchLocked(s, b)
}
/** Job bị khoá khi batch của nó có autoLockAt < state.now. */
export const isJobLocked = (s: DashboardState, jobId: string): boolean => {
  const j = jobById(s, jobId)
  return !!j && isBatchLockedById(s, j.batchId)
}

/** Batch user được xem: admin tất cả; pm theo dự án; còn lại theo team có job trong batch. */
export function visibleBatches(s: DashboardState, user: User): Batch[] {
  if (user.role === 'admin') return s.batches
  if (user.role === 'pm') { const ids = new Set(visibleProjects(s, user).map((p) => p.id)); return s.batches.filter((b) => ids.has(b.projectId)) }
  const mine = new Set(s.jobs.filter((j) => j.teamId !== null && user.teamIds.includes(j.teamId)).map((j) => j.batchId))
  return s.batches.filter((b) => mine.has(b.id))
}
export const visibleDatasets = (s: DashboardState, user: User): Dataset[] => {
  if (user.role === 'admin') return s.datasets
  const ids = new Set(visibleProjects(s, user).map((p) => p.id))
  return s.datasets.filter((d) => ids.has(d.projectId))
}

export interface DatasetStats { batchTotal: number; batchPending: number; batchActive: number; batchDone: number; jobTotal: number }
/** done = ready|delivered; active = in_progress|in_audit; released không tính vào active/done. */
export function datasetStats(s: DashboardState, datasetId: string): DatasetStats {
  const bs = batchesOfDataset(s, datasetId)
  const n = (st: Batch['status'][]) => bs.filter((b) => st.includes(b.status)).length
  return {
    batchTotal: bs.length, batchPending: n(['pending']), batchActive: n(['in_progress', 'in_audit']), batchDone: n(['ready', 'delivered']),
    jobTotal: s.jobs.filter((j) => bs.some((b) => b.id === j.batchId)).length,
  }
}

export interface BatchStats {
  totalJobs: number; doneJobs: number; progressPct: number; byStage: Record<JobStage, number>
  picNames: { annotate: string[]; qc1: string | null; qc2: string | null }; locked: boolean
}
export function batchStats(s: DashboardState, batchId: string): BatchStats {
  const jobs = jobsOfBatch(s, batchId)
  const b = batchById(s, batchId)
  const byStage = Object.fromEntries(STAGES.map((st) => [st, 0])) as Record<JobStage, number>
  jobs.forEach((j) => { byStage[j.stage] += 1 })
  const doneJobs = jobs.filter(isDone).length
  return {
    totalJobs: jobs.length, doneJobs, progressPct: pct(doneJobs, jobs.length), byStage,
    picNames: {
      annotate: b?.teamId ? [teamById(s, b.teamId)?.name ?? b.teamId] : [],
      qc1: b?.stepPic.qc1 ? userById(s, b.stepPic.qc1)?.name ?? b.stepPic.qc1 : null,
      qc2: b?.stepPic.qc2 ? userById(s, b.stepPic.qc2)?.name ?? b.stepPic.qc2 : null,
    },
    locked: !!b && isBatchLocked(s, b),
  }
}
/** Lịch sử batch, mới → cũ. */
export const batchHistory = (s: DashboardState, batchId: string): BatchEvent[] =>
  s.batchEvents.filter((e) => e.batchId === batchId).sort((a, b) => b.at.localeCompare(a.at) || b.id.localeCompare(a.id))

/** Mức audit kế tiếp của dự án: { index, percent }. */
export function nextAuditLevel(s: DashboardState, projectId: string): { index: number; percent: number } {
  const index = nextAuditLevelIndex(s, projectId)
  return { index, percent: AUDIT_LEVELS[index] }
}
/** Batch có thể đưa vào audit mới: in_progress và có ≥1 job qc2_pending. */
export const auditableBatches = (s: DashboardState, user: User): Batch[] =>
  visibleBatches(s, user).filter((b) => b.status === 'in_progress' && s.jobs.some((j) => j.batchId === b.id && j.stage === 'qc2_pending'))

export const isFavorite = (s: DashboardState, userId: string, targetId: string): boolean => (s.favorites[userId] ?? []).includes(targetId)

// ---------- Hàng đợi (Data Queue)
export interface QueueStep { step: WorkStep; pending: number; processing: number; rework: number }
export interface QueueRow { batch: Batch; project: Project; dataset: Dataset | undefined; steps: QueueStep[]; locked: boolean; favorite: boolean }

/** User có quyền QC (thấy hàng QC1/QC2): isQc, lead, pm, admin hoặc thuộc team canQa. */
export function canQc(s: DashboardState, user: User): boolean {
  return user.isQc || user.role === 'lead' || user.role === 'pm' || user.role === 'admin' || user.teamIds.some((t) => teamById(s, t)?.canQa)
}
/** Hàng QC2 · Audit: pm, admin hoặc thành viên team canQa. */
export const canAudit = (s: DashboardState, user: User): boolean =>
  user.role === 'pm' || user.role === 'admin' || user.teamIds.some((t) => teamById(s, t)?.canQa)

/**
 * Mỗi batch đang chạy (in_progress|in_audit|ready) user nhìn thấy → các bước kèm số chờ/đang xử lý.
 * annotate: chờ = job ở kho team (phạm vi team của user); đang = anno_in_progress (annotator: của mình); rework = job bị trả (ưu tiên).
 * Hàng qc1/qc2 chỉ có khi user có quyền (canQc / canAudit).
 */
export function queueRowsForUser(s: DashboardState, userId: string): QueueRow[] {
  const user = userById(s, userId)
  if (!user) return []
  const all = user.role === 'admin' || user.role === 'pm'
  const inScope = (j: Job) => all || (j.teamId !== null && user.teamIds.includes(j.teamId))
  const rows: QueueRow[] = []
  for (const batch of visibleBatches(s, user)) {
    if (batch.status !== 'in_progress' && batch.status !== 'in_audit' && batch.status !== 'ready') continue
    const jobs = jobsOfBatch(s, batch.id)
    const scoped = jobs.filter(inScope)
    const count = (js: Job[], st: JobStage) => js.filter((j) => j.stage === st).length
    const mineOnly = user.role === 'annotator'
    const annoJobs = scoped.filter((j) => !mineOnly || j.annotatorId === user.id)
    const steps: QueueStep[] = [{
      step: 'annotate', pending: count(scoped, 'team_pool'), processing: count(annoJobs, 'anno_in_progress'),
      rework: annoJobs.filter((j) => j.stage === 'anno_in_progress' && j.reworkCount > 0).length,
    }]
    if (canQc(s, user)) {
      steps.push({ step: 'qc1', pending: count(scoped, 'qc1_pending'), processing: count(scoped, 'qc1_in_progress'), rework: 0 })
      if (canAudit(s, user)) steps.push({ step: 'qc2', pending: count(jobs, 'qc2_pending'), processing: count(jobs, 'qc2_in_progress'), rework: 0 })
    }
    rows.push({
      batch, project: projectById(s, batch.projectId)!, dataset: datasetById(s, batch.datasetId), steps,
      locked: isBatchLocked(s, batch), favorite: isFavorite(s, userId, batch.id) || isFavorite(s, userId, batch.projectId),
    })
  }
  return rows
}

// ---------- Thống kê dữ liệu (Data Statistic)
export type StatStage = 'annotate' | 'qc1' | 'qc2'
export interface StatFilters { projectId?: string; batchId?: string; from: string; to: string }

const HOUR = 3600_000
const SESSION_GAP = 3 * HOUR
const SESSION_START = 0.5 * HOUR

const WORK_TYPES: Record<StatStage, JobEvent['type'][]> = {
  annotate: ['submit', 'resubmit'],
  qc1: ['qc1_pass', 'qc1_return'],
  qc2: ['qc2_pass', 'qc2_return_qc1', 'qc2_return_anno'],
}
const RETURN_TYPES: JobEvent['type'][] = ['qc1_return', 'qc2_return_qc1', 'qc2_return_anno']

/** Đổi 'YYYY-MM-DD' hoặc ISO thành mốc ms; `to` dạng ngày được tính hết ngày. */
const bound = (v: string, end: boolean): number =>
  v.length === 10 ? new Date(v + (end ? 'T23:59:59.999Z' : 'T00:00:00.000Z')).getTime() : new Date(v).getTime()

function scopedEvents(s: DashboardState, f: StatFilters): { events: JobEvent[]; jobs: Map<string, Job> } {
  const jobs = new Map(
    s.jobs.filter((j) => (!f.projectId || j.projectId === f.projectId) && (!f.batchId || j.batchId === f.batchId)).map((j) => [j.id, j] as const),
  )
  const lo = bound(f.from, false)
  const hi = bound(f.to, true)
  const events = s.events.filter((e) => {
    const t = new Date(e.at).getTime()
    return jobs.has(e.jobId) && t >= lo && t <= hi
  })
  return { events, jobs }
}

/** Giờ làm việc suy từ khoảng cách giữa các event của một người: khoảng ≤3h tính đủ; mỗi phiên (đầu hoặc sau khoảng >3h) cộng 0,5h. */
export function workingHours(timesMs: number[]): number {
  const t = [...timesMs].sort((a, b) => a - b)
  let total = 0
  t.forEach((x, i) => {
    if (i === 0 || x - t[i - 1] > SESSION_GAP) total += SESSION_START
    else total += x - t[i - 1]
  })
  return total / HOUR
}

export interface StageStatRow {
  user: User; jobs: number; cuboids: number; cuboidPerHour: number
  /** 0–100: tỷ lệ job qua bước kế tiếp không bị trả. */
  fpy: number
  reworkJobs: number
  /** Giờ. */
  repairTime: number; avgRepairTime: number
}

const round1 = (n: number) => Math.round(n * 10) / 10

/**
 * Năng suất theo bước. Job của một người = job họ hoàn tất bước đó (event nộp / duyệt-trả) trong khoảng.
 * fpy (annotate|qc1) = 1 − job bị trả về chống lại họ / job; (qc2) = job duyệt / (duyệt + trả).
 * Thời gian sửa = từ lúc bị trả tới lần nộp lại (annotate) hoặc duyệt lại QC1 (qc1) trên cùng job.
 */
export function statsByStage(s: DashboardState, f: StatFilters & { stage: StatStage }): StageStatRow[] {
  const { events, jobs } = scopedEvents(s, f)
  const allByJob = new Map<string, JobEvent[]>()
  for (const e of s.events) if (jobs.has(e.jobId)) (allByJob.get(e.jobId) ?? allByJob.set(e.jobId, []).get(e.jobId)!).push(e)
  allByJob.forEach((l) => l.sort((a, b) => a.at.localeCompare(b.at) || a.id.localeCompare(b.id)))

  const work = events.filter((e) => WORK_TYPES[f.stage].includes(e.type))
  const byUser = new Map<string, JobEvent[]>()
  for (const e of work) (byUser.get(e.actorId) ?? byUser.set(e.actorId, []).get(e.actorId)!).push(e)

  const rows: StageStatRow[] = []
  for (const [userId, evs] of byUser) {
    const user = userById(s, userId)
    if (!user) continue
    const jobIds = [...new Set(evs.map((e) => e.jobId))]
    const cuboids = jobIds.reduce((n, id) => n + (jobs.get(id)?.editedCuboids ?? 0), 0)
    // Mọi event của người này trong khoảng (mọi loại) để ước giờ làm.
    const times = events.filter((e) => e.actorId === userId).map((e) => new Date(e.at).getTime())
    const hours = workingHours(times)

    let reworkJobs = 0
    let repairs = 0
    let repairMs = 0
    let fpy: number
    if (f.stage === 'qc2') {
      const passed = new Set(evs.filter((e) => e.type === 'qc2_pass').map((e) => e.jobId))
      const returned = new Set(evs.filter((e) => e.type !== 'qc2_pass').map((e) => e.jobId))
      reworkJobs = returned.size
      fpy = pct(passed.size, passed.size + returned.size)
    } else {
      for (const id of jobIds) {
        const list = allByJob.get(id) ?? []
        const against = list.filter((e) => RETURN_TYPES.includes(e.type) && e.reworkAgainst?.includes(userId))
        if (against.length > 0) reworkJobs += 1
        for (const r of against) {
          const fix = list.find((e) => e.at >= r.at && e.id > r.id && (f.stage === 'annotate' ? e.type === 'resubmit' : e.type === 'qc1_pass'))
          if (fix) { repairs += 1; repairMs += new Date(fix.at).getTime() - new Date(r.at).getTime() }
        }
      }
      fpy = pct(jobIds.length - reworkJobs, jobIds.length)
    }
    rows.push({
      user, jobs: jobIds.length, cuboids, cuboidPerHour: hours > 0 ? Math.round(cuboids / hours) : 0, fpy, reworkJobs,
      repairTime: round1(repairMs / HOUR), avgRepairTime: repairs > 0 ? round1(repairMs / HOUR / repairs) : 0,
    })
  }
  return rows.sort((a, b) => b.cuboids - a.cuboids || a.user.name.localeCompare(b.user.name))
}

export interface KeyMetrics {
  activeWorkers: number
  annotate: { jobs: number; cuboids: number }
  qc1: { jobs: number; cuboids: number }
  ready: { jobs: number; cuboids: number }
  /** %: lần trả về / lần nộp trong khoảng. */
  reworkRate: number
  /** %: lần trả về / lần kiểm (duyệt + trả) trong khoảng. */
  errorRate: number
}

export function keyMetrics(s: DashboardState, f: StatFilters): KeyMetrics {
  const { events, jobs } = scopedEvents(s, f)
  const cub = (ids: Set<string>) => ({ jobs: ids.size, cuboids: [...ids].reduce((n, id) => n + (jobs.get(id)?.editedCuboids ?? 0), 0) })
  const ids = (types: JobEvent['type'][]) => new Set(events.filter((e) => types.includes(e.type)).map((e) => e.jobId))
  const workTypes = [...WORK_TYPES.annotate, ...WORK_TYPES.qc1, ...WORK_TYPES.qc2]
  const returns = events.filter((e) => RETURN_TYPES.includes(e.type)).length
  const submits = events.filter((e) => WORK_TYPES.annotate.includes(e.type)).length
  const checks = events.filter((e) => WORK_TYPES.qc1.includes(e.type) || WORK_TYPES.qc2.includes(e.type)).length
  return {
    activeWorkers: new Set(events.filter((e) => workTypes.includes(e.type)).map((e) => e.actorId)).size,
    annotate: cub(ids(WORK_TYPES.annotate)),
    qc1: cub(ids(['qc1_pass'])),
    ready: cub(ids(['qc2_pass'])),
    reworkRate: pct(returns, submits),
    errorRate: pct(returns, checks),
  }
}
export * from './deadline'

/** R11: current assignees and people who actually submitted (first or later rounds) or reviewed QC1. */
export function pastWorkersOfJob(s: DashboardState, jobId: string): Set<string> {
  const job = s.jobs.find(j => j.id === jobId)
  return new Set([
    job?.annotatorId, job?.qc1Id,
    ...s.events.filter(e => e.jobId === jobId && ['submit', 'resubmit', 'qc1_pass', 'qc1_return'].includes(e.type)).map(e => e.actorId),
  ].filter((id): id is string => !!id))
}
