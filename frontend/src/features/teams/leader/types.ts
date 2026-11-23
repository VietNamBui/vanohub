import type { UserBrief } from '../../../shared/api/types'
import type { Role } from '../../../shared/types/roles'
import type { JobStatus } from '../../jobs/types'
import type { PendingMetric } from '../../quality/types'

export interface LeaderMember {
  user: UserBrief
  email: string
  roles: Role[]
  /** Vai trò được gán trực tiếp (không gồm vai trò kèm theo) — để biết QC1 có thu lại được không. */
  direct_roles: Role[]
  joined_at: string
  capacity: number
  holding: number
  qc1_holding: number
  due_soon: number
  escalated: number
  jobs_total: number
  jobs_done: number
  rework_rate: number | null
}

export interface LeaderTeam {
  id: number
  name: string
  members: LeaderMember[]
}

export interface LeaderDashboard {
  teams: { id: number; name: string }[]
  member_count: number
  jobs_total: number
  jobs_open: number
  done_in_period: PendingMetric
  kpi_by_total: PendingMetric
  kpi_quota: PendingMetric
  rework_rate: PendingMetric
  ranking: { user: UserBrief; jobs_total: number; jobs_done: number; objects_done: number; rework_rate: number | null }[]
  due_soon: { id: number; name: string; batch_name: string; status: JobStatus; annotator: UserBrief | null; deadline: string; is_overdue: boolean }[]
}

export type LeaderJobTab = 'all' | 'doing' | 'qc' | 'escalated'
