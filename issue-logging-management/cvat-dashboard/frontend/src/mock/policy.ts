import { pastWorkersOfJob, projectTeamIds, qc2OwnerOf } from './selectors'
import type { Batch, BatchStatus, DashboardState, Job, Project, Team, User } from './types'

/**
 * Bộ luật vai trò DUY NHẤT (plan 09, 00-ARCHITECTURE §R3–R8). `can` là hàm thuần, không đổi state:
 * tầng dữ liệu (`logic.ts`) gọi `requireCan` để CHẶN, giao diện gọi `can` để ẩn/làm mờ nút kèm `reason`.
 * Mọi điều kiện (quyền + điều kiện dữ liệu như "team đích không thuộc dự án") nằm ở đây.
 */

export type Verdict = { ok: true } | { ok: false; reason: string }

export type PolicyAction =
  | { kind: 'updateUser'; userId: string; patch: Partial<Omit<User, 'id'>> }
  | { kind: 'teamAdmin'; op: 'create' | 'update' | 'delete'; teamId?: string }
  | { kind: 'addMember'; teamId: string; userId: string }
  | { kind: 'workJob'; jobId: string; op: 'submit' | 'startQc1' | 'qc1Pass' | 'qc1Return' }
  | { kind: 'batchQc1'; batchId: string; picId: string }
  | { kind: 'manageBatch'; batchId: string; op: 'release' | 'autoLock' | 'due' | 'priority' }
  | { kind: 'jobDue'; jobId: string }
  | { kind: 'deliver'; jobIds: string[] }
  | { kind: 'dataType' }
  | { kind: 'assignBatchTeam'; batchId: string; teamId: string }
  | { kind: 'assignProject'; projectId: string; pmIds: string[] }
  | { kind: 'setTeamPm'; teamId: string; pmId: string }
  | { kind: 'moveMember'; userId: string; toTeamId: string | null }
  | { kind: 'assignJob'; jobId: string; annotatorId: string; qc1Id: string }
  | { kind: 'reassignJob'; jobId: string; annotatorId?: string; qc1Id?: string }
  | { kind: 'qc2'; jobId: string }
  | { kind: 'audit'; batchIds: string[] }

const OK: Verdict = { ok: true }
const deny = (reason: string): Verdict => ({ ok: false, reason })

const teamOf = (s: DashboardState, id: string | null | undefined): Team | undefined => s.teams.find((t) => t.id === id)
const userOf = (s: DashboardState, id: string | null | undefined): User | undefined => s.users.find((u) => u.id === id)
const nameOf = (s: DashboardState, userId: string): string => userOf(s, userId)?.name ?? userId

/** Batch được đổi team khi chưa xong (R3). */
const TRANSFERABLE: BatchStatus[] = ['pending', 'in_progress']
/** Batch coi như đã xong phần việc của PM (R5). */
const FINISHED: BatchStatus[] = ['ready', 'delivered', 'released']
/** Batch đang chạy — team cần PM phụ trách dự án (R6). */
const RUNNING: BatchStatus[] = ['in_progress', 'in_audit']

// ---------- R3: giao/chuyển batch cho team
function canAssignBatchTeam(s: DashboardState, user: User, batchId: string, teamId: string): Verdict {
  const batch = s.batches.find((b) => b.id === batchId)
  if (!batch) return deny(`Không tìm thấy batch ${batchId}`)
  if (batch.teamId === teamId) return deny('Batch đã ở team này')
  const team = teamOf(s, teamId)
  if (!team) return deny(`Không tìm thấy team ${teamId}`)
  const project = s.projects.find((p) => p.id === batch.projectId)
  if (!project) return deny(`Không tìm thấy dự án ${batch.projectId}`)
  if (!TRANSFERABLE.includes(batch.status)) return deny('Batch đang audit/đã xong, không đổi team được')
  if (!projectTeamIds(s, project.id).includes(team.id)) return deny(`Team ${team.name} không thuộc PM nào của dự án ${project.name}`)
  if (!team.allowedSteps.includes('annotate')) return deny(`Team ${team.name} không làm bước gán nhãn`)
  if (user.role === 'admin') return OK
  if (user.role !== 'pm') return deny('Chỉ sếp tổng hoặc PM của dự án được giao batch')
  if (!project.pmIds.includes(user.id)) return deny(`Bạn không phụ trách dự án ${project.name}`)
  const current = teamOf(s, batch.teamId)
  if (team.pmId !== user.id || (current && current.pmId !== user.id)) return deny('Chỉ sếp tổng được chuyển batch sang team của PM khác')
  return OK
}

// ---------- R5: đổi PM của dự án
function canAssignProject(s: DashboardState, user: User, projectId: string, pmIdsIn: string[]): Verdict {
  if (user.role !== 'admin') return deny('Chỉ sếp tổng được giao dự án')
  const project = s.projects.find((p) => p.id === projectId)
  if (!project) return deny(`Không tìm thấy dự án ${projectId}`)
  const pmIds = [...new Set(pmIdsIn)]
  if (pmIds.length === 0) return deny('Dự án cần ít nhất một PM phụ trách')
  for (const id of pmIds) if (userOf(s, id)?.role !== 'pm') return deny(`${id} không phải PM`)
  for (const removed of project.pmIds.filter((id) => !pmIds.includes(id))) {
    const open = unfinishedBatchesOfPm(s, project, removed)
    if (open.length > 0) {
      return deny(`PM ${nameOf(s, removed)} còn ${open.length} batch chưa xong ở dự án ${project.name}: ${open.map((b) => b.name).join(', ')}`)
    }
  }
  return OK
}

function unfinishedBatchesOfPm(s: DashboardState, project: Project, pmId: string): Batch[] {
  return s.batches.filter((b) => b.projectId === project.id && teamOf(s, b.teamId)?.pmId === pmId && !FINISHED.includes(b.status))
}

// ---------- R6: đổi PM của team
function canSetTeamPm(s: DashboardState, user: User, teamId: string, pmId: string): Verdict {
  if (user.role !== 'admin') return deny('Chỉ sếp tổng được đổi PM của team')
  const team = teamOf(s, teamId)
  if (!team) return deny(`Không tìm thấy team ${teamId}`)
  const pm = userOf(s, pmId)
  if (pm?.role !== 'pm') return deny(`${pmId} không phải PM`)
  const projectIds = new Set(s.batches.filter((b) => b.teamId === team.id && RUNNING.includes(b.status)).map((b) => b.projectId))
  const missing = s.projects.filter((p) => projectIds.has(p.id) && !p.pmIds.includes(pm.id))
  if (missing.length > 0) return deny(`PM ${pm.name} chưa phụ trách dự án: ${missing.map((p) => p.name).join(', ')}`)
  return OK
}

// ---------- R7: đổi team / nghỉ của một người
function canMoveMember(s: DashboardState, user: User, userId: string, toTeamId: string | null): Verdict {
  const member = userOf(s, userId)
  if (!member) return deny(`Không tìm thấy người dùng ${userId}`)
  if (member.role !== 'lead' && member.role !== 'annotator') return deny('Chỉ chuyển được lead hoặc annotator')
  const from = teamOf(s, member.teamIds[0])
  if (!from) return deny(`${member.name} chưa thuộc team nào`)
  const to = toTeamId === null ? null : teamOf(s, toTeamId)
  if (to === undefined) return deny(`Không tìm thấy team ${toTeamId}`)
  if (to && to.id === from.id) return deny(`${member.name} đã ở ${from.name}`)
  if (from.leadId === member.id) return deny(`${member.name} là lead duy nhất của ${from.name}, phải đổi lead trước`)
  if (user.role === 'admin') return OK
  if (user.role === 'pm' && from.pmId === user.id && (to === null || to.pmId === user.id)) return OK
  return deny('Chỉ sếp tổng hoặc PM của cả team nguồn và team đích được chuyển người')
}

// ---------- R8: giao job trong team
function canAssignJob(s: DashboardState, user: User, job: Job, annotatorId: string | null, qc1Id: string | null): Verdict {
  const team = teamOf(s, job.teamId)
  if (!team) return deny(`Job ${job.id} chưa thuộc team nào`)
  if (annotatorId !== null && !team.memberIds.includes(annotatorId)) return deny('Annotator phải thuộc team của job')
  if (qc1Id !== null) {
    if (!team.memberIds.includes(qc1Id)) return deny('QC1 phải thuộc team của job')
    if (!userOf(s, qc1Id)?.isQc && team.leadId !== qc1Id) return deny('QC1 phải là QC hoặc lead của team')
  }
  if (annotatorId !== null && annotatorId === qc1Id) return deny('QC1 không được là người gán nhãn')
  if (user.role === 'admin' || team.leadId === user.id || team.pmId === user.id) return OK
  return deny('Chỉ lead, PM của team hoặc sếp tổng được giao job')
}

// ---------- R4: QC2 / Audit
/** Người dùng được làm QC2/Audit cho batch/job mà PM chịu trách nhiệm là `ownerId`. */
function canQc2For(s: DashboardState, user: User, ownerId: string | null): Verdict {
  if (user.role === 'admin') return OK
  if (ownerId !== null && user.id === ownerId) return OK
  // Thành viên team canQa: chỉ với batch của team thuộc cùng PM với team mình.
  if (ownerId !== null && user.teamIds.some((t) => { const tm = teamOf(s, t); return !!tm?.canQa && tm.pmId === ownerId })) return OK
  return deny('Chỉ PM của team đang giữ batch (hoặc sếp tổng) được QC2/Audit')
}

export function can(s: DashboardState, user: User, act: PolicyAction): Verdict {
  const admin = user.role === 'admin'
  const forbidden = () => deny('Bạn không có quyền thực hiện thao tác này')
  const fourEyes = (job: Job) => !pastWorkersOfJob(s, job.id).has(user.id)
  switch (act.kind) {
    case 'updateUser':
      if (!admin) return forbidden()
      if ('role' in act.patch || 'teamIds' in act.patch) return deny('Đổi team dùng Chuyển team/Cho nghỉ')
      return OK
    case 'teamAdmin': {
      if (!admin) return forbidden()
      if (act.op === 'delete') {
        const team = teamOf(s, act.teamId)
        if (!team || team.memberIds.length || s.batches.some(b => b.teamId === team.id && RUNNING.includes(b.status))) return deny('Team còn thành viên hoặc batch đang chạy')
      }
      return OK
    }
    case 'addMember': {
      if (!admin) return forbidden()
      const member = userOf(s, act.userId)
      if (!teamOf(s, act.teamId) || !member) return deny('Không tìm thấy team hoặc người dùng')
      return member.teamIds.length ? deny('Đổi team dùng Chuyển team/Cho nghỉ') : OK
    }
    case 'workJob': {
      const job = s.jobs.find(j => j.id === act.jobId)
      if (!job) return deny('Không tìm thấy job')
      const team = teamOf(s, job.teamId)
      if (!team?.memberIds.includes(user.id)) return forbidden()
      if (act.op === 'submit') return job.stage === 'anno_in_progress' && job.annotatorId === user.id ? OK : forbidden()
      if (act.op === 'startQc1' ? job.stage !== 'qc1_pending' : !['qc1_pending', 'qc1_in_progress'].includes(job.stage)) return forbidden()
      if (team.leadId !== user.id && !userOf(s, user.id)?.isQc) return forbidden()
      return user.id !== job.annotatorId && (job.qc1Id === user.id || teamOf(s, job.teamId)?.leadId === user.id) ? OK : forbidden()
    }
    case 'batchQc1': {
      const batch = s.batches.find(b => b.id === act.batchId)
      const team = teamOf(s, batch?.teamId)
      if (!team || !team.memberIds.includes(act.picId) || !(userOf(s, act.picId)?.isQc || team.leadId === act.picId)) return deny('QC1 phải là QC hoặc lead thuộc team batch')
      return admin || team.pmId === user.id || team.leadId === user.id ? OK : forbidden()
    }
    case 'manageBatch': {
      const batch = s.batches.find(b => b.id === act.batchId)
      if (!batch) return deny('Không tìm thấy batch')
      const project = s.projects.find(p => p.id === batch.projectId)
      if (admin) return OK
      if (user.role !== 'pm' || !project?.pmIds.includes(user.id)) return forbidden()
      return act.op !== 'release' || batch.status === 'pending' || teamOf(s, batch.teamId)?.pmId === user.id ? OK : forbidden()
    }
    case 'jobDue': {
      const job = s.jobs.find(j => j.id === act.jobId)
      if (!job) return deny('Không tìm thấy job')
      const project = s.projects.find(p => p.id === job.projectId)
      return admin || (user.role === 'pm' && project?.pmIds.includes(user.id)) || teamOf(s, job.teamId)?.leadId === user.id ? OK : forbidden()
    }
    case 'deliver':
      for (const id of act.jobIds) {
        const job = s.jobs.find(j => j.id === id)
        if (!job || !fourEyes(job) || !(admin || qc2OwnerOf(s, job) === user.id)) return forbidden()
      }
      return OK
    case 'dataType': return admin || user.role === 'pm' ? OK : forbidden()

    case 'assignBatchTeam': return canAssignBatchTeam(s, user, act.batchId, act.teamId)
    case 'assignProject': return canAssignProject(s, user, act.projectId, act.pmIds)
    case 'setTeamPm': return canSetTeamPm(s, user, act.teamId, act.pmId)
    case 'moveMember': return canMoveMember(s, user, act.userId, act.toTeamId)
    case 'assignJob': {
      const job = s.jobs.find((j) => j.id === act.jobId)
      if (!job) return deny(`Không tìm thấy job ${act.jobId}`)
      return canAssignJob(s, user, job, act.annotatorId, act.qc1Id)
    }
    case 'reassignJob': {
      const job = s.jobs.find((j) => j.id === act.jobId)
      if (!job) return deny(`Không tìm thấy job ${act.jobId}`)
      if (act.annotatorId === undefined && act.qc1Id === undefined) return deny('Cần chọn annotator hoặc QC1 mới')
      if (job.stage === 'team_pool') return deny('Job chưa giao: dùng Giao job (assignJob)')
      if ((act.annotatorId !== undefined && job.stage !== 'anno_in_progress') || !['anno_in_progress', 'qc1_pending', 'qc1_in_progress'].includes(job.stage)) return deny('Job đã qua bước này, không đổi người được')
      // Kiểm thành viên cho người MỚI; QC1 ≠ annotator xét trên cặp sau khi đổi.
      const annotatorId = act.annotatorId ?? job.annotatorId
      const qc1Id = act.qc1Id ?? job.qc1Id
      const base = canAssignJob(s, user, job, act.annotatorId ?? null, act.qc1Id ?? null)
      if (!base.ok) return base
      if (annotatorId !== null && annotatorId === qc1Id) return deny('QC1 không được là người gán nhãn')
      return OK
    }
    case 'qc2': {
      const job = s.jobs.find((j) => j.id === act.jobId)
      if (!job) return deny(`Không tìm thấy job ${act.jobId}`)
      if (!fourEyes(job)) return deny('Không được tự duyệt job đã gán nhãn hoặc QC1')
      return canQc2For(s, user, qc2OwnerOf(s, job))
    }
    case 'audit': {
      if (act.batchIds.length === 0) return deny('Cần chọn ít nhất một batch')
      for (const id of act.batchIds) {
        const batch = s.batches.find((b) => b.id === id)
        if (!batch) return deny(`Không tìm thấy batch ${id}`)
        if (s.jobs.some(j => j.batchId === id && !fourEyes(j))) return deny('Không được tự audit job đã gán nhãn hoặc QC1')
        const v = canQc2For(s, user, teamOf(s, batch.teamId)?.pmId || null)
        if (!v.ok) return v
      }
      return OK
    }
  }
}

/** `can` với người dùng hiện tại; sai luật ⇒ throw Error(reason) (tiếng Việt, hiện được cho người dùng). */
export function requireCan(s: DashboardState, act: PolicyAction): void {
  const user = userOf(s, s.currentUserId)
  if (!user) throw new Error(`Không tìm thấy người dùng ${s.currentUserId}`)
  const v = can(s, user, act)
  if (!v.ok) throw new Error(v.reason)
}
