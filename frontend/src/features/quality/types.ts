import type { UserBrief } from '../../shared/api/types'
import type { JobStatus } from '../jobs/types'

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
  dataset_name: string
  batch_name: string
  annotator: UserBrief | null
  qc1_reviewer: UserBrief | null
  rework_round: number
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
  /** Frame (đánh số theo task) QC2 cần kiểm — sampling_rate % số frame của job. */
  frames: number[]
  rework_round: number
  auditor: UserBrief | null
  result: 'pending' | 'pass' | 'reject'
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
