import type { UserBrief } from '../../shared/api/types'
import type { ActivityLog } from '../projects/types'

export type JobStatus =
  | 'pending_annotation'
  | 'annotating'
  | 'pending_qc1'
  | 'qc1_reviewing'
  | 'rework'
  | 'pending_qc2'
  | 'approved'
  | 'delivered'

export type Stage = 'annotation' | 'qc1' | 'qc2' | 'done'

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
  rework_round: number
  max_rework_rounds: number
  is_escalated: boolean
  is_locked: boolean
  frame_count: number
  object_count: number
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
  dataset?: number
  batch?: number
  assignee?: number
  search?: string
  escalated?: boolean
  overdue?: boolean
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
