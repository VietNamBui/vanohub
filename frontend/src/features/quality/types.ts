import type { UserBrief } from '../../shared/api/types'
import type { JobStatus } from '../jobs/types'
import type { SamplingMethod, StratifyBy } from '../projects/types'

export type Severity = 'minor' | 'major' | 'critical'

export interface ErrorCategory {
  id: number
  name: string
  description: string
  severity: Severity
  applies_to: 'qc1' | 'qc2' | 'both'
  is_active: boolean
}

export interface SampleJob {
  id: number
  name: string
  status: JobStatus
  batch_name: string
  annotator: UserBrief | null
  qc1_reviewer: UserBrief | null
  rework_round: number
  object_count: number
  frame_count: number
  cvat_job_id: number | null
  cvat_url: string | null
}

export interface ReviewError {
  id: number
  stage: 'qc1' | 'qc2'
  rework_round: number
  category: number
  category_name: string
  severity: Severity
  location: string
  description: string
  reported_by: UserBrief | null
  created_at: string
}

export interface AuditSample {
  id: number
  audit: number
  audit_status: 'in_progress' | 'completed'
  job: SampleJob
  stratum: string
  auditor: UserBrief | null
  result: 'pending' | 'pass' | 'reject'
  reviewed_by: UserBrief | null
  reviewed_at: string | null
  comment: string
  errors: ReviewError[]
}

export interface Audit {
  id: number
  batch: number
  batch_name: string
  dataset_name: string
  status: 'in_progress' | 'completed'
  method: SamplingMethod
  sampling_rate: number
  stratify_by: StratifyBy | ''
  seed: number
  eligible_count: number
  note: string
  created_by: UserBrief | null
  created_at: string
  completed_at: string | null
  sample_count: number
  passed: number
  rejected: number
  pending: number
}

export interface AuditInput {
  batch: number
  method?: SamplingMethod
  sampling_rate?: number
  stratify_by?: StratifyBy
  seed?: number
  auditors?: number[]
  note?: string
}

export interface AuditPreview {
  batch: number
  method: SamplingMethod
  sampling_rate: number
  stratify_by: StratifyBy | ''
  seed: number
  eligible_count: number
  sample_count: number
  estimated_objects: number
  estimated_frames: number
  samples: { stratum: string; job: SampleJob }[]
}

export interface ErrorInput {
  category: number
  severity?: Severity
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
  kpi: { current: Qc2Window; previous: Qc2Window }
  trend: { date: string; audited: number; rejected: number; errors: number }[]
  error_percent_in_job: PendingMetric
  audit_speed: PendingMetric
  scope: 'project' | 'mine'
  stats: { assigned: number; pending: number; passed: number; rejected: number; audited_in_period: number }
  pass_rate: number | null
  qc1_missed_errors: number
  reworked_after_audit: number
  errors_by_category: { category: string; count: number }[]
  progress_by_batch: { batch: string; total: number; done: number }[]
}

export interface AuditStrategy {
  method: SamplingMethod
  sampling_rate: number
  stratify_by: StratifyBy | ''
  /** Chỉ PM sửa được; QC2 chỉ xem. */
  can_edit: boolean
  history: {
    at: string
    actor: UserBrief | null
    before: Partial<Record<'sampling_method' | 'sampling_rate' | 'stratify_by', string | number>>
    after: Partial<Record<'sampling_method' | 'sampling_rate' | 'stratify_by', string | number>>
  }[]
  preview_batches: { id: number; name: string; dataset_name: string; pending_qc2: number }[]
}
