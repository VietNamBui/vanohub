import type { UserBrief } from '../../shared/api/types'
import type { Capability } from '../../shared/types/capabilities'
import type { Role } from '../../shared/types/roles'

export type EscalationPolicy = 'block' | 'warn_only'

export interface ProjectSummary {
  id: number
  name: string
  description: string
  /** CVAT organization ứng với "Organization" này (null nếu tạo nội bộ / demo). */
  cvat_org_id: number | null
  cvat_org_slug: string
  cvat_synced_at: string | null
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
  escalation_policy: EscalationPolicy
  max_rework_rounds: number
  annotator_wip_limit: number
}

export interface ProjectWriteInput {
  name: string
  description?: string
  max_rework_rounds?: number
  escalation_policy?: EscalationPolicy
  annotator_wip_limit?: number
  pm_ids?: number[]
}

export type SamplingMethod = 'random' | 'stratified'
export type StratifyBy = 'annotator' | 'qc1_reviewer' | 'dataset'

export interface ProjectSettings {
  cvat_org_id: number | null
  cvat_org_slug: string
  cvat_synced_at: string | null
  max_rework_rounds: number
  escalation_policy: EscalationPolicy
  annotator_wip_limit: number
  sampling_method: SamplingMethod
  /** % số frame của mỗi job QC2 kiểm (mọi job qua QC1 đều được kiểm). */
  sampling_rate: number
  stratify_by: StratifyBy
  quality_cl_threshold: string | null
  defect_rate_threshold: string | null
  kpi_annotation_target: number | null
  kpi_qc1_target: number | null
  kpi_qc2_target: number | null
}

export type ProjectSettingsUpdateInput = Partial<
  Omit<ProjectSettings, 'cvat_org_id' | 'cvat_org_slug' | 'cvat_synced_at'>
>

export interface CvatStatus {
  connected: boolean
  url: string
  version?: string
  detail?: string
}

export interface Member {
  user: UserBrief
  roles: Role[]
  /** Vai trò gán trực tiếp (không gồm vai trò đi kèm như QC2 của PM) — chỉ những vai trò này gỡ được. */
  direct_roles: Role[]
  team: { id: number; name: string } | null
  active_jobs: number
  /** Đã liên kết tài khoản CVAT chưa — chưa thì job vẫn giao được, CVAT được đồng bộ sau. */
  cvat_linked: boolean
  cvat_username: string | null
  /** Còn mật khẩu tạm do hệ thống cấp (người dùng chưa tự đổi). */
  has_initial_password: boolean
}

export interface CreateMemberInput {
  full_name: string
  username?: string
  email?: string
  roles: Role[]
  team?: number | null
}

/** Kết quả tạo tài khoản / cấp lại mật khẩu: mật khẩu tạm dạng rõ. */
export interface MemberCredential {
  username: string
  password: string | null
  /** initial: còn mật khẩu tạm · changed: người dùng đã tự đổi · unreadable: không giải mã được → cấp lại */
  status: 'initial' | 'changed' | 'unreadable'
}

export interface CreatedMember {
  user: UserBrief
  username: string
  password: string
  roles: Role[]
  team: { id: number; name: string } | null
}

export type DataStatus = 'active' | 'locked' | 'delivered'

/**
 * ÁNH XẠ (chốt 2026-11-25) — tên kiểu giữ như backend, giao diện hiển thị tên CVAT:
 *   ProjectDetail/ProjectSummary = "Organization" · Dataset = "Project" (CVAT project) · Batch = "Task" (CVAT task)
 */
export interface Dataset {
  id: number
  name: string
  description: string
  status: DataStatus
  cvat_project_id: number | null
  last_synced_at: string | null
  created_at: string
  task_count: number
  job_count: number
  done_count: number
}

export type SyncStatus = '' | 'ok' | 'error'

/** "Task" trên giao diện = một CVAT task. PM đặt deadline (job nhận theo) và team phụ trách. */
export interface Batch {
  id: number
  name: string
  dataset: number
  dataset_name: string
  cvat_task_id: number | null
  status: DataStatus
  deadline: string | null
  team: number | null
  team_name: string | null
  source_missing: boolean
  last_synced_at: string | null
  last_sync_status: SyncStatus
  last_sync_error: string
  qc2_confirmed_at: string | null
  qc2_confirmed_by: UserBrief | null
  created_at: string
  job_count: number
  done_count: number
  qc1_passed_count: number
  blocking_qc2_count: number
  pending_qc2_count: number
  escalated_count: number
  pending_qc2_samples: number
  locked_jobs: number
  ready_for_qc2_confirm: boolean
}

export interface CvatLabel {
  id: number
  name: string
  color: string | null
  type: string | null
}

export interface ProjectSyncResult {
  projects: number
  projects_created: number
  tasks: number
  tasks_created: number
  jobs_created: number
  jobs_updated: number
  assignees_pushed: number
  waiting_link: number
  assignee_error?: string
}

export interface ProjectsSyncResult {
  created: string[]
  updated: string[]
  pm_added: { organization: string; user: string }[]
  members_added: { organization: string; user: string }[]
  waiting: { cvat_org_id: number; name: string; reason: string }[]
}

export interface Delivery {
  id: number
  batch: number
  batch_name: string
  dataset_name: string
  deadline: string | null
  is_on_time: boolean | null
  recipient: string
  output_path: string
  note: string
  client_feedback: string
  delivered_by: UserBrief | null
  delivered_at: string
  job_count: number
}

export type DueState = 'overdue' | 'soon' | 'normal' | 'none'

export interface DeliveryCandidate {
  batch: number
  batch_name: string
  dataset_name: string
  status: DataStatus
  dataset_status: DataStatus
  deadline: string | null
  is_overdue: boolean
  due_state: DueState
  job_count: number
  approved_count: number
  locked_jobs: number
  pending_qc2_samples: number
  in_progress_audits: number
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

export interface DeliveryReadinessMetric extends Metric {
  ready_batches?: number
  delivered_batches?: number
  total_batches?: number
}

export interface DeliveryOnTimeMetric extends Metric {
  on_time_deliveries?: number
  due_deliveries?: number
  late_deliveries?: number
  overdue_undelivered?: number
}

export interface RatioMetric extends Metric {
  passed?: number
  resolved?: number
  total?: number
}

export interface ProjectOverview {
  counts: {
    datasets: number
    batches: number
    ready_batches: number
    delivered_batches: number
    overdue_batches: number
    jobs: number
    remaining_jobs: number
    escalated: number
    overdue: number
  }
  by_status: Record<string, number>
  by_stage: Record<'annotation' | 'qc1' | 'qc2' | 'done', number>
  stage_progress: {
    annotation_passed: number
    qc1_passed: number
    qc2_approved: number
  }
  pending_decisions: {
    batches_ready_for_qc2_confirm: number
    batches_ready_for_qc2: number
    pending_qc2_samples: number
    pending_requests: number
    escalated_jobs: number
    escalated: number
    total: number
  }
  errors_by_category: { category: string; count: number }[]
  errors_by_severity: { minor: number; major: number; critical: number }
  metrics: {
    total_objects: Metric
    total_frames: Metric
    progress: Metric
    remaining_jobs: Metric
    delivery_readiness: DeliveryReadinessMetric
    delivered_rate: Metric
    delivery_on_time_rate: DeliveryOnTimeMetric
    rework_rate: Metric
    first_pass_yield: RatioMetric
    qc2_pass_rate: Metric
    quality_cl: Metric
    defect_error_rate: Metric
    defect_rate_by_severity: Metric
    dispute_overturn_rate: RatioMetric
    estimated_completion: Metric
    submitted_in_period: Metric
    active_members: Metric
  }
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
    objects_produced: number
    first_pass_objects: number
    rework_objects: number
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
  first_pass_objects: number
  rework_objects: number
  total_objects: number
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

export type ProjectNotificationCategory = NotificationCategory

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
