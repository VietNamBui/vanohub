import type { BadgeColors } from '@/components/base/badges/badge-types'
import type { JobIssueAuthorStage, JobIssueStatus, PrimaryCategory, Severity } from './types'

export const SEVERITY_LABELS: Record<Severity, string> = { minor: 'Nhẹ', major: 'Nặng', critical: 'Nghiêm trọng' }
export const SEVERITY_COLORS: Record<Severity, string> = { minor: 'default', major: 'orange', critical: 'red' }
export const SEVERITY_BADGE_COLORS: Record<Severity, BadgeColors> = {
  minor: 'gray',
  major: 'orange',
  critical: 'error',
}
export const RESULT_LABELS = { pending: 'Chờ audit', pass: 'Pass', reject: 'Reject' } as const
export const RESULT_COLORS = { pending: 'default', pass: 'success', reject: 'error' } as const
export const METHOD_LABELS = { random: 'Random', stratified: 'Stratified' } as const
export const STRATIFY_LABELS = { annotator: 'Annotator', qc1_reviewer: 'Người QC1', dataset: 'Dataset', '': '' } as const

export const PRIMARY_CATEGORY_LABELS: Record<PrimaryCategory, string> = {
  '': 'Chưa phân nhóm',
  E1: 'E1 · Thiếu đối tượng',
  E2: 'E2 · Sai nhãn lớp',
  E3: 'E3 · Lệch khung / biên',
  E4: 'E4 · Gán nhầm / thừa',
  E5: 'E5 · Sai thuộc tính',
  E6: 'E6 · Lỗi liên kết track',
}

export const JOB_ISSUE_STATUS_LABELS: Record<JobIssueStatus, string> = {
  open: 'Mở',
  addressed: 'Đã sửa (chờ xác nhận)',
  unclear: 'Chưa rõ / Tranh chấp',
  reopened: 'Mở lại',
  resolved: 'Đã xử lý',
  not_an_issue: 'Không phải lỗi',
}

export const JOB_ISSUE_STATUS_BADGE_COLORS: Record<JobIssueStatus, BadgeColors> = {
  open: 'error',
  addressed: 'blue',
  unclear: 'warning',
  reopened: 'orange',
  resolved: 'success',
  not_an_issue: 'gray',
}

export const JOB_ISSUE_AUTHOR_STAGE_LABELS: Record<JobIssueAuthorStage, string> = {
  '': 'Không xác định',
  annotator: 'Annotator',
  qc1: 'QC1',
  qc2: 'QC2',
}

export const TAMPER_REASON_LABELS: Record<string, string> = {
  first_comment_deleted: 'Comment đầu đã bị xoá',
  preqc_ref_injected: 'Chèn tham chiếu pre-QC không hợp lệ',
  envelope_downgraded: 'Hạ mức độ / đổi mã lỗi trên CVAT',
  position_3d_wiped: 'Xoá toạ độ / đối tượng 3D',
  invalid_position: 'Toạ độ CVAT không hợp lệ',
}
