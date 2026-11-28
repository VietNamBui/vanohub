import type { JobStatus } from '../jobs/types'
import type { ErrorCategory, ErrorVerdict, JobIssue, Severity } from './types'

const ACTIVE_ANNOTATOR_STATUSES = new Set<JobStatus>(['pending_annotation', 'annotating', 'rework'])
const BLOCKING_SEVERITIES = new Set<Severity>(['major', 'critical'])

export interface RejectErrorPrefill {
  job_issue: number
  cvat_issue_id: number
  category: number | null
  severity: Severity
  verdict: ErrorVerdict
  is_missing_object: boolean
  frame_number: string
  cvat_object_id: string
  location: string
  description: string
}

/** Khớp loại lỗi danh mục ưu tiên theo mã lỗi cụ thể (`code`), rồi đến nhóm chính (`primary_category`). */
export function matchCategoryForIssue(
  issue: Pick<JobIssue, 'defect_code' | 'primary_category'>,
  categories: ErrorCategory[],
): ErrorCategory | null {
  const defectCode = issue.defect_code.trim().toUpperCase()
  const primary = issue.primary_category.trim().toUpperCase()

  if (defectCode) {
    const exactCode = categories.find((c) => c.code.trim().toUpperCase() === defectCode)
    if (exactCode) return exactCode
  }
  if (primary) {
    const byPrimary = categories.find((c) => c.primary_category.trim().toUpperCase() === primary)
    if (byPrimary) return byPrimary
    const byPrimaryCode = categories.find((c) => c.code.trim().toUpperCase() === primary)
    if (byPrimaryCode) return byPrimaryCode
  }
  return null
}

/** Dựng sẵn một dòng lỗi Reject từ JobIssue (khớp chuẩn ràng buộc `EXI-MISS` và `track_id`/`shape_id` ở backend). */
export function buildRejectPrefillFromIssue(
  issue: Pick<
    JobIssue,
    | 'id'
    | 'cvat_issue_id'
    | 'defect_code'
    | 'primary_category'
    | 'severity'
    | 'frame_number'
    | 'track_id'
    | 'shape_id'
    | 'message'
  >,
  categories: ErrorCategory[],
): RejectErrorPrefill {
  const matched = matchCategoryForIssue(issue, categories)
  const boundObjId = issue.track_id ?? issue.shape_id
  const isMissingObject = issue.defect_code.trim().toUpperCase() === 'EXI-MISS' && boundObjId == null
  const location =
    boundObjId != null
      ? `Frame ${issue.frame_number} · #${boundObjId}`
      : `Frame ${issue.frame_number} · Issue #${issue.cvat_issue_id}`

  return {
    job_issue: issue.id,
    cvat_issue_id: issue.cvat_issue_id,
    category: matched?.id ?? null,
    severity: issue.severity,
    verdict: 'fail',
    is_missing_object: isMissingObject,
    frame_number: String(issue.frame_number),
    cvat_object_id: !isMissingObject && boundObjId != null ? String(boundObjId) : '',
    location,
    description: issue.message,
  }
}

/** Lý do Annotator chưa thể bấm "Đã sửa" trên một JobIssue; null = cho phép. */
export function getAnnotatorAddressBlockReason(
  issue: Pick<JobIssue, 'authority_status' | 'is_clarification' | 'ruled_at' | 'status'>,
  jobStatus: JobStatus,
  isLocked = false,
  isEscalatedBlocked = false,
): string | null {
  if (isLocked) return 'Job đang bị khoá.'
  if (isEscalatedBlocked) return 'Job đang bị chặn do vượt số vòng rework tối đa.'
  if (!ACTIVE_ANNOTATOR_STATUSES.has(jobStatus)) {
    return 'Chỉ đánh dấu đã sửa khi job đang ở giai đoạn Annotator.'
  }
  if (issue.authority_status !== 'valid') return 'Issue không hợp lệ.'
  if (issue.is_clarification && !issue.ruled_at) {
    return 'Chờ PM phán quyết yêu cầu làm rõ trước khi đánh dấu đã sửa.'
  }
  if (issue.status !== 'open' && issue.status !== 'reopened') {
    return 'Chỉ đánh dấu đã sửa khi issue đang Mở hoặc Mở lại.'
  }
  return null
}

/** Lý do Annotator chưa thể gửi "Phản hồi" cho một JobIssue; null = cho phép. */
export function getAnnotatorDisputeBlockReason(
  issue: Pick<JobIssue, 'authority_status' | 'status' | 'is_disputed'>,
  jobStatus: JobStatus,
  isLocked = false,
): string | null {
  if (isLocked) return 'Job đang bị khoá.'
  if (jobStatus === 'approved' || jobStatus === 'delivered') {
    return 'Không thể phản hồi trên job đã duyệt hoặc đã bàn giao.'
  }
  if (issue.authority_status !== 'valid') return 'Issue không hợp lệ.'
  if (issue.is_disputed) return 'Issue đang có phản hồi chờ PM xử lý.'
  if (issue.status !== 'open' && issue.status !== 'reopened' && issue.status !== 'addressed') {
    return 'Không thể phản hồi issue ở trạng thái hiện tại.'
  }
  return null
}

/** Lý do QC1/QC2 chưa thể đưa issue vào danh sách lỗi Reject; null = cho phép. */
export function getSelectForRejectBlockReason(
  issue: Pick<
    JobIssue,
    'id' | 'authority_status' | 'status' | 'author_stage' | 'frame_number' | 'is_clarification' | 'ruled_at'
  >,
  mode: 'qc1' | 'qc2',
  sampleFrames?: number[],
  selectedIssueIds?: number[],
): string | null {
  if (selectedIssueIds?.includes(issue.id)) return 'Issue đã có trong danh sách Reject.'
  if (issue.authority_status !== 'valid') return 'Issue có tác giả không hợp lệ.'
  if (issue.status === 'not_an_issue') return 'Issue đã được chốt không phải lỗi.'
  if (issue.is_clarification && !issue.ruled_at) {
    return 'Yêu cầu làm rõ chưa có phán quyết PM — không thể đưa vào danh sách Reject.'
  }
  if (mode === 'qc2') {
    if (issue.author_stage === 'qc1') return 'Không thể dùng issue QC1 cho lượt reject QC2.'
    if (sampleFrames != null && !sampleFrames.includes(issue.frame_number)) {
      return `Frame #${issue.frame_number} không nằm trong danh sách frame mẫu QC2.`
    }
  }
  if (mode === 'qc1' && issue.author_stage === 'qc2') {
    return 'Không thể dùng issue QC2 cho lượt reject QC1.'
  }
  return null
}

/** Kiểm tra issue có đang chặn Submit Gate (Annotator nộp bài) hay không. */
export function isSubmitBlockingIssue(
  issue: Pick<JobIssue, 'authority_status' | 'source_missing' | 'status' | 'severity' | 'ruled_at'>,
): boolean {
  if (issue.authority_status !== 'valid' || issue.source_missing) return false
  if (issue.status !== 'open' && issue.status !== 'reopened') return false
  return BLOCKING_SEVERITIES.has(issue.severity) || issue.ruled_at != null
}

/** Kiểm tra issue có đang chặn Acceptance Gate (QC1 Pass / QC2 Pass / Bàn giao) hay không. */
export function isAcceptanceBlockingIssue(
  issue: Pick<JobIssue, 'authority_status' | 'source_missing' | 'status' | 'severity' | 'ruled_at'>,
): boolean {
  if (issue.authority_status !== 'valid' || issue.source_missing) return false
  if (issue.status === 'unclear') return true
  if (issue.status === 'open' || issue.status === 'reopened' || issue.status === 'addressed') {
    return BLOCKING_SEVERITIES.has(issue.severity) || issue.ruled_at != null
  }
  return false
}

/** Định dạng chuỗi frame hoặc khoảng frame của issue. */
export function formatIssueFrameLabel(
  issue: Pick<JobIssue, 'frame_number' | 'frame_start' | 'frame_end'>,
): string {
  if (issue.frame_start != null && issue.frame_end != null) {
    if (issue.frame_start === issue.frame_end) return `Frame #${issue.frame_start}`
    return `Frame #${issue.frame_start}–${issue.frame_end} (tại #${issue.frame_number})`
  }
  return `Frame #${issue.frame_number}`
}

/** Định dạng nhãn đối tượng 3D/2D gắn với issue (Track # hoặc Shape #). */
export function formatIssueObjectLabel(issue: Pick<JobIssue, 'track_id' | 'shape_id'>): string | null {
  if (issue.track_id != null) return `Track #${issue.track_id}`
  if (issue.shape_id != null) return `Shape #${issue.shape_id}`
  return null
}

/** Chuyển `ruling_attributes` sang văn bản mỗi dòng `key=value` để chỉnh sửa trong modal PM. */
export function formatRulingAttributes(attrs: Record<string, unknown> | null | undefined): string {
  if (!attrs) return ''
  return Object.entries(attrs)
    .map(([k, v]) => `${k}=${v == null ? '' : String(v)}`)
    .join('\n')
}

/** Phân tích văn bản `key=value` mỗi dòng thành `ruling_attributes` nguyên thủy khớp validator backend. */
export function parseRulingAttributes(raw: string): {
  valid: boolean
  error: string | null
  value: Record<string, string | number | boolean | null>
} {
  const result: Record<string, string | number | boolean | null> = {}
  const lines = raw
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)

  if (lines.length > 32) {
    return { valid: false, error: 'Tối đa 32 thuộc tính phán quyết.', value: {} }
  }

  for (const line of lines) {
    const eqIdx = line.indexOf('=')
    if (eqIdx <= 0) {
      return { valid: false, error: `Mỗi dòng phải theo định dạng key=value (lỗi ở "${line}").`, value: {} }
    }
    const key = line.slice(0, eqIdx).trim()
    const rawVal = line.slice(eqIdx + 1).trim()
    if (!key || key.length > 64) {
      return { valid: false, error: `Tên thuộc tính không hợp lệ ("${key}").`, value: {} }
    }
    if (rawVal.length > 255) {
      return { valid: false, error: `Giá trị thuộc tính "${key}" tối đa 255 ký tự.`, value: {} }
    }
    if (rawVal === '') {
      result[key] = null
    } else if (rawVal === 'true') {
      result[key] = true
    } else if (rawVal === 'false') {
      result[key] = false
    } else if (/^-?\d+(?:\.\d+)?$/.test(rawVal) && Number.isFinite(Number(rawVal))) {
      result[key] = Number(rawVal)
    } else {
      result[key] = rawVal
    }
  }

  return { valid: true, error: null, value: result }
}
