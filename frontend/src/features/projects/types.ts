import type { UserBrief } from '../../shared/api/types'
import type { Capability } from '../../shared/types/capabilities'
import type { Role } from '../../shared/types/roles'

export type EscalationPolicy = 'block' | 'warn_only'

export interface ProjectSummary {
  id: number
  name: string
  description: string
  cvat_project_id: number | null
  created_at: string
  my_roles: Role[] // vai trò có hiệu lực (đã gồm PM → QC2)
  project_managers: UserBrief[]
  job_count: number
  done_count: number
  overdue_count: number
  escalated_count: number
  progress_percent: number
}

export interface ProjectDetail extends ProjectSummary {
  updated_at: string
  member_counts: Partial<Record<Role, number>>
  member_total: number
  my_capabilities: Capability[]
  max_rework_rounds: number
  escalation_policy: EscalationPolicy
  annotator_wip_limit: number
}

export interface ProjectWriteInput {
  name: string
  description?: string
  cvat_project_id?: number | null
  max_rework_rounds?: number
  escalation_policy?: EscalationPolicy
  annotator_wip_limit?: number
  pm_ids?: number[]
}

export type SamplingMethod = 'random' | 'stratified'
export type StratifyBy = 'annotator' | 'qc1_reviewer' | 'dataset'

export interface ProjectSettings {
  cvat_project_id: number | null
  max_rework_rounds: number
  escalation_policy: EscalationPolicy
  annotator_wip_limit?: number
  sampling_method: SamplingMethod
  sampling_rate: number
  stratify_by: StratifyBy
  quality_cl_threshold: string | null
  defect_rate_threshold: string | null
  kpi_annotation_target: number | null
  kpi_qc1_target: number | null
  kpi_qc2_target: number | null
}

export interface Member {
  user: UserBrief
  roles: Role[]
  team: { id: number; name: string } | null
  active_jobs: number
}

export type DataStatus = 'active' | 'locked' | 'delivered'

export interface Dataset {
  id: number
  name: string
  description: string
  status: DataStatus
  created_at: string
  batch_count: number
  job_count: number
  done_count: number
}

export type SyncStatus = '' | 'ok' | 'error'

export interface Batch {
  id: number
  dataset: number
  dataset_name: string
  name: string
  status: DataStatus
  deadline: string | null
  team: number | null
  team_name: string | null
  cvat_task_id: number | null
  last_synced_at: string | null
  last_sync_status: SyncStatus
  last_sync_error: string
  qc2_confirmed_by: UserBrief | null
  qc2_confirmed_at: string | null
  created_at: string
  job_count: number
  done_count: number
  qc1_passed_count: number
  pending_qc2_count: number
  escalated_count: number
  ready_for_qc2_confirm: boolean
}

export interface CvatTaskItem {
  id: number
  name: string
  project_id: number | null
  status: string
  size: number
  subset: string
}

export interface Delivery {
  id: number
  batch: number
  batch_name: string
  dataset_name: string
  recipient: string
  output_path: string
  note: string
  client_feedback: string
  delivered_by: UserBrief | null
  delivered_at: string
  job_count: number
}

export interface DeliveryCandidate {
  batch: number
  batch_name: string
  dataset_name: string
  job_count: number
  approved_count: number
  open_audits: number
  ready: boolean
}

export interface ActivityLog {
  id: number
  actor: UserBrief | null
  action: string
  target_type: string
  target_id: number | null
  target_label: string
  job: number | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  note: string
  created_at: string
}

export interface Announcement {
  id: number
  sender: UserBrief | null
  target_roles: Role[]
  target_team: number | null
  target_team_name: string | null
  content: string
  created_at: string
}

export interface Guideline {
  id: number
  version: number
  title: string
  content: string
  created_by: UserBrief | null
  created_at: string
}

export interface PermissionMatrix {
  capabilities: Record<Capability, Role[]>
  implied_roles: Partial<Record<Role, Role[]>>
}

export interface Metric {
  value: number | null
  status: 'ok' | 'provisional' | 'pending_definition'
  formula: string
}

export interface ProjectOverview {
  counts: { datasets: number; batches: number; jobs: number; escalated: number; overdue: number }
  by_status: Record<string, number>
  by_stage: Record<'annotation' | 'qc1' | 'qc2' | 'done', number>
  metrics: Record<
    | 'total_objects'
    | 'total_frames'
    | 'progress'
    | 'delivery_readiness'
    | 'rework_rate'
    | 'first_pass_yield'
    | 'qc2_pass_rate'
    | 'quality_cl'
    | 'defect_error_rate'
    | 'estimated_completion'
    | 'submitted_in_period'
    | 'active_members',
    Metric
  >
  thresholds: { quality_cl: string | null; defect_error_rate: string | null }
  alerts: { level: 'error' | 'warning' | 'info'; type: string; job: number; message: string }[]
}

export interface TeamRanking {
  formula: string
  rows: {
    rank: number
    team: { id: number; name: string }
    members: number
    jobs: number
    done: number
    objects_done: number
    rework_rate: number | null
    escalated: number
    qc2_errors: number
  }[]
}

export interface MemberPerformance {
  user: UserBrief
  jobs: number
  done: number
  objects_done: number
  rework_rate: number | null
}

export type NotificationCategory =
  | 'assigned'
  | 'rework'
  | 'review_needed'
  | 'escalated'
  | 'deadline'
  | 'dispute'
  | 'qc_pass'
  | 'announcement'

export interface UnifiedNotification {
  id: string
  notification_id: number | null
  source: 'system' | 'deadline' | 'announcement'
  category: NotificationCategory
  title: string
  body: string
  job_id: number | null
  action_url: string
  is_read: boolean
  is_pinned_pending: boolean
  created_at: string
}

export interface NotificationFeed {
  all_count: number
  unread_count: number
  items: UnifiedNotification[]
}
