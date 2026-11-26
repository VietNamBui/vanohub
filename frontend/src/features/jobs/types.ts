import type { UserBrief } from '../../shared/api/types'
import type { ActivityLog } from '../projects/types'

export type JobStatus =
  | 'pending_annotation'
  | 'annotating'
  | 'pending_qc1'
  | 'qc1_reviewing'
  | 'qc1_passed'
  | 'rework'
  | 'pending_qc2'
  | 'approved'
  | 'delivered'

export type Stage = 'annotation' | 'qc1' | 'qc2' | 'done'
export type ReworkScope = 'partial' | 'full'
export type DueState = 'overdue' | 'soon' | 'normal' | 'none'

export interface Job {
  id: number
  name: string
  status: JobStatus
  status_label: string
  stage: Stage
  batch: number
  batch_name: string
  dataset: number
  dataset_name: string
  annotator: UserBrief | null
  qc1_reviewer: UserBrief | null
  /** Chỉ có khi job được lấy mẫu trong đợt audit QC2 đang mở. */
  qc2: Qc2Assignment | null
  deadline: string | null
  is_overdue: boolean
  due_state?: DueState
  hours_remaining?: number | null
  rework_round: number
  max_rework_rounds: number
  escalation_policy?: 'block' | 'warn_only'
  rework_scope?: ReworkScope
  rework_scope_label?: string
  is_escalated: boolean
  is_locked: boolean
  frame_count: number
  object_count: number
  target_object_count?: number
  progress_percent?: number
  open_error_count?: number
  started_at?: string | null
  submitted_at?: string | null
  cvat_job_id: number | null
  cvat_task_id: number | null
  cvat_stage: string
  cvat_state: string
  cvat_url: string | null
  updated_at: string
}

export interface JobErrorBrief {
  id: number
  stage: 'qc1' | 'qc2'
  rework_round: number
  category: string
  severity: string
  location: string
  description: string
  reported_by: UserBrief | null
  created_at: string
}

export interface JobDetail extends Job {
  timeline: ActivityLog[]
  errors: JobErrorBrief[]
}

export interface JobFilters {
  page?: number
  page_size?: number
  stage?: Stage | ''
  status?: string
  dataset?: number | string
  batch?: number | string
  assignee?: number
  annotator?: number
  qc1_reviewer?: number
  min_rework?: number
  max_rework?: number
  deadline_from?: string
  deadline_to?: string
  search?: string
  escalated?: boolean
  overdue?: boolean
  due_soon?: boolean
  unassigned?: boolean
  locked?: boolean
  ordering?: string
}

export interface QueueStage {
  stage: 'annotation' | 'qc1' | 'qc2'
  total: number
  unassigned: number
  rework: number
  escalated: number
  overdue: number
  locked: number
  by_status: Partial<Record<JobStatus, number>>
}

export interface Qc2Assignment {
  sample_id: number
  audit_id: number
  result: 'pending' | 'pass' | 'reject'
  auditor: UserBrief | null
}

export type AnnotatorJobTab = 'active' | 'todo' | 'rework' | 'submitted' | 'done' | 'all'

export interface AnnotatorMetric {
  value: number | null
  status: 'ok' | 'provisional' | 'pending_definition'
  formula: string
}

export type AnnotatorRequestType = 'error_dispute' | 'data_issue'
export type AnnotatorRequestStatus = 'pending_pm' | 'resolved' | 'rejected'

export interface AnnotatorRequest {
  id: number
  job: number
  job_name: string
  batch_name: string
  review_error: number | null
  error_category: string | null
  error_location: string
  request_type: AnnotatorRequestType
  request_type_label: string
  status: AnnotatorRequestStatus
  status_label: string
  title: string
  reason: string
  progress_note: string
  resolution_note: string
  created_by: UserBrief
  handler: UserBrief | null
  handler_role: string
  created_at: string
  updated_at: string
  resolved_at: string | null
}

export interface AnnotatorReworkFocus {
  job_id: number
  job_name: string
  batch_name: string
  deadline: string | null
  rework_round: number
  max_rework_rounds: number
  rework_scope: ReworkScope
  rework_scope_label: string
  error_count: number
  pending_object_frames: number
  errors: JobErrorBrief[]
}

export interface AnnotatorDailyResult {
  date: string
  label: string
  first_pass_objects: number
  rework_objects: number
  total_objects: number
  target_objects: number
  is_off_day: boolean
}

export interface AnnotatorDashboard {
  counts: {
    total: number
    pending_annotation: number
    annotating: number
    rework: number
    waiting_review: number
    done: number
    overdue: number
    due_soon?: number
    escalated: number
  }
  objects_done: number
  submitted_in_period: AnnotatorMetric
  rework_rate: AnnotatorMetric
  first_pass_yield: AnnotatorMetric
  kpi_target: number | null
  errors_by_category: { category: string; count: number }[]
  due_soon: {
    id: number
    name: string
    batch_name: string
    status: JobStatus
    deadline: string
    is_overdue: boolean
  }[]
  meta: {
    team_name: string | null
    project_name: string
    last_cvat_sync_at: string | null
    wip_limit: number
    active_jobs_count: number
    active_object_frames: number
  }
  kpi_summary: {
    actual_objects: number
    target_objects: number | null
    achievement_pct: number | null
    shortfall: number
    rework_jobs_count: number
    max_rework_round_active: number
    max_rework_rounds: number
    due_soon_count: number
    overdue_count: number
    fpy_pct: number | null
    fpy_passed: number
    fpy_total: number
    on_time_pct: number | null
    on_time_count: number
    submitted_total: number
  }
  next_jobs: Job[]
  rework_focus: AnnotatorReworkFocus | null
  daily_results: AnnotatorDailyResult[]
  recent_requests: {
    pending_count: number
    items: AnnotatorRequest[]
  }
}

export type AnnotatorAnalyticsRange = '7d' | '30d' | 'week'

export interface AnnotatorAnalytics {
  range: AnnotatorAnalyticsRange
  week_label: string
  iso_year: number
  avg_productivity: {
    objects_per_hour: number
    total_objects: number
    total_hours: number
  }
  forecast: {
    estimated_objects: number
    avg_daily_objects: number
    remaining_workdays: number
    daily_target: number
  }
  ranking: {
    rank: number
    total_annotators: number
    previous_rank: number
  }
  daily_productivity: {
    date: string
    label: string
    first_pass_objects: number
    rework_objects: number
    first_pass_per_hour: number
    rework_per_hour: number
    hours: number
    is_off_day: boolean
  }[]
  weekly_forecast_series: {
    date: string
    day_label: string
    actual_objects: number
    forecast_objects: number
    is_forecast: boolean
    is_off_day: boolean
  }[]
}

export interface AnnotatorQuickSearchResult {
  jobs: {
    id: number
    name: string
    batch_name: string
    status: JobStatus
    status_label: string
    rework_round: number
    progress_percent: number
  }[]
}
