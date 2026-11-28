import type { UserBrief } from '../../shared/api/types'
import type { DueState, JobStatus } from '../jobs/types'

export type Severity = 'minor' | 'major' | 'critical'
export type ErrorVerdict = 'fail' | 'edge'
export type PrimaryCategory = '' | 'E1' | 'E2' | 'E3' | 'E4' | 'E5' | 'E6'

export interface ErrorCategory {
  id: number
  code: string
  primary_category: PrimaryCategory
  name: string
  description: string
  severity: Severity
  applies_to: 'qc1' | 'qc2' | 'both'
  is_active: boolean
}

export type ErrorCategoryInput = Partial<Omit<ErrorCategory, 'id'>>

export type JobIssueStatus = 'open' | 'addressed' | 'unclear' | 'reopened' | 'resolved' | 'not_an_issue'
export type JobIssueSource = 'manual' | 'clarification'
export type JobIssueAuthorStage = '' | 'annotator' | 'qc1' | 'qc2'
export type JobIssueAuthorityStatus = 'valid' | 'rejected_author'
export type JobIssueRuleDecision = 'ruling' | 'not_an_issue' | 'resolved'

export interface JobIssue {
  id: number
  job: number
  job_name: string
  cvat_issue_id: number
  first_comment_id: number | null
  defect_code: string
  primary_category: PrimaryCategory
  severity: Severity
  source: JobIssueSource
  is_clarification: boolean
  frame_number: number
  frame_start: number | null
  frame_end: number | null
  track_id: number | null
  shape_id: number | null
  position: number[]
  message: string
  author: UserBrief | null
  author_cvat_id: number | null
  author_stage: JobIssueAuthorStage
  authority_status: JobIssueAuthorityStatus
  status: JobIssueStatus
  cvat_resolved: boolean
  cvat_last_comment_id: number
  cvat_synced_at: string | null
  source_missing: boolean
  tampered: boolean
  tamper_reason: string
  cvat_reopen_drift: boolean
  is_disputed: boolean
  dispute_reason: string
  ruling_label: string
  ruling_attributes: Record<string, unknown>
  ruling_note: string
  ruled_by: UserBrief | null
  ruled_at: string | null
  created_at: string
  updated_at: string
}

export interface JobIssueListParams {
  job?: number
  status?: string
  severity?: string
  primary_category?: string
  authority_status?: JobIssueAuthorityStatus
  is_clarification?: boolean
  is_disputed?: boolean
  tampered?: boolean
  source_missing?: boolean
  page?: number
  page_size?: number
}

export interface JobIssueImportResult {
  job: number
  created: number
  updated: number
  total: number
  issues: JobIssue[]
}

export interface JobIssueDisputeResult {
  issue: JobIssue
  request_id: number
}

export interface JobIssueRulePayload {
  decision: JobIssueRuleDecision
  ruling_label?: string
  ruling_attributes?: Record<string, string | number | boolean | null>
  ruling_note?: string
  dispute_outcome?: 'rejected' | null
}

export interface SampleJob {
  id: number
  name: string
  status: JobStatus
  dataset_name: string
  batch_name: string
  annotator: UserBrief | null
  qc1_reviewer: UserBrief | null
  deadline: string | null
  is_overdue: boolean
  due_state: DueState
  hours_remaining: number | null
  rework_round: number
  max_rework_rounds: number
  object_count: number
  frame_count: number
  /** Frame đầu của job trong task (CVAT đánh số frame theo task). */
  cvat_start_frame: number
  cvat_job_id: number | null
  cvat_url: string | null
}

export interface ReviewError {
  id: number
  stage: 'qc1' | 'qc2'
  rework_round: number
  job_issue?: number | null
  cvat_issue_id?: number | null
  category: number
  category_name: string
  severity: Severity
  verdict?: ErrorVerdict
  frame_number?: number | null
  cvat_object_id?: number | null
  is_missing_object?: boolean
  location: string
  description: string
  is_voided?: boolean
  reported_by: UserBrief | null
  created_at: string
}

export interface AuditSample {
  id: number
  audit: number
  audit_status: 'in_progress' | 'completed'
  job: SampleJob
  job_name: string
  batch_name: string
  dataset_name: string
  cvat_url: string | null
  /** Frame (đánh số theo task) QC2 cần kiểm — sampling_rate % số frame của job. */
  frames: number[]
  rework_round: number
  checked_object_count: number | null
  auditor: UserBrief | null
  result: 'pending' | 'pass' | 'reject'
  created_at: string
  reviewed_by: UserBrief | null
  reviewed_at: string | null
  comment: string
  errors: ReviewError[]
}

/** Đợt QC2 của một task — tự tạo khi job đầu tiên vào Chờ QC2, tự chốt khi task bàn giao. */
export interface Audit {
  id: number
  batch: number
  batch_name: string
  dataset_name: string
  status: 'in_progress' | 'completed'
  sampling_rate: number
  created_at: string
  completed_at: string | null
  sample_count: number
  passed: number
  rejected: number
  pending: number
}

export interface ErrorInput {
  category: number
  job_issue?: number | null
  severity?: Severity
  verdict?: ErrorVerdict
  frame_number?: number | null
  cvat_object_id?: number | null
  is_missing_object?: boolean
  location?: string
  description?: string
}

export interface Qc2Window {
  audited: number
  passed: number
  rejected: number
  pass_rate: number | null
  errors: number
}

/** Chỉ số chưa có công thức / dữ liệu — giao diện hiện "Chưa chốt", không bịa số. */
export interface PendingMetric {
  value: number | null
  status: 'ok' | 'provisional' | 'pending_definition'
  formula: string
}

export interface Qc2Summary {
  kpi: {
    current: Qc2Window
    previous: Qc2Window
    comparison: Record<'audited' | 'passed' | 'rejected' | 'errors', MetricDelta>
  }
  kpi_target: number | null
  kpi_summary: KpiProgress
  trend: { date: string; audited: number; rejected: number; errors: number }[]
  error_percent_in_job: PendingMetric
  defect_error_rate: PendingMetric
  quality_cl: PendingMetric
  defect_rate_by_severity: PendingMetric
  audit_speed: PendingMetric
  scope: 'project' | 'mine'
  stats: {
    assigned: number
    pending: number
    passed: number
    rejected: number
    audited_in_period: number
    audited_today: number
    overdue: number
    due_soon: number
  }
  pass_rate: number | null
  qc1_missed_errors: number
  reworked_after_audit: number
  errors_by_category: { category: string; count: number }[]
  errors_by_severity: Partial<Record<Severity, number>>
  progress_by_batch: { batch_id: number; batch: string; dataset_name: string; total: number; done: number }[]
}

export interface AuditStrategy {
  /** % số frame của mỗi job QC2 kiểm. */
  sampling_rate: number
  /** Chỉ PM có quyền cấu hình mới sửa được. */
  can_edit: boolean
  history: {
    at: string
    actor: UserBrief | null
    before: { sampling_rate?: number }
    after: { sampling_rate?: number }
  }[]
  stats: { pending: number; passed: number; rejected: number }
}

export type Qc1Scope = 'mine' | 'pool' | 'all'
export type Qc1JobTab = 'queue' | 'reviewing' | 'done' | 'all'

export interface Qc1Window {
  reviewed: number
  passed: number
  rejected: number
  pass_rate: number | null
  errors: number
}

export interface MetricDelta {
  delta: number
  pct_change: number | null
}

export interface KpiProgress {
  actual: number
  target: number | null
  achievement_pct: number | null
  shortfall: number
  surplus: number
}

export interface Qc1EscapeError {
  id: number
  job_id: number
  job_name: string
  batch_name: string
  category: string
  severity: Severity
  verdict: ErrorVerdict
  frame_number: number | null
  cvat_object_id: number | null
  is_missing_object: boolean
  location: string
  description: string
  reported_by: UserBrief | null
  created_at: string
}

export interface Qc1Summary {
  scope: 'project' | 'mine'
  stats: {
    assigned: number
    pending: number
    pool_pending: number
    reviewing: number
    qc1_passed: number
    passed: number
    rejected: number
    reviewed_in_period: number
    reviewed_today: number
    overdue: number
    due_soon: number
  }
  pass_rate: number | null
  on_time_pct: number | null
  on_time_count: number
  on_time_total: number
  first_pass_yield: PendingMetric & { passed: number; total: number }
  kpi: {
    current: Qc1Window
    previous: Qc1Window
    comparison: Record<'reviewed' | 'passed' | 'rejected' | 'errors', MetricDelta>
  }
  kpi_summary: KpiProgress
  trend: { date: string; reviewed: number; rejected: number; errors: number }[]
  qc2_escape_errors: number
  escaped_jobs: number
  escaped_jobs_count: number
  qc1_escape_job_rate: number | null
  audited_jobs_count: number
  escape_errors: Qc1EscapeError[]
  errors_by_category: { category: string; count: number }[]
  errors_by_severity: Partial<Record<Severity, number>>
  kpi_target: number | null
}
