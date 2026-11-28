import type { UserBrief } from '../../shared/api/types'
import type { SearchableOption } from '../../shared/components/ui/searchableSelectUtils'
import type { Role } from '../../shared/types/roles'
import { formatDateTime } from '../../shared/utils/format'
import type { Member } from '../projects/types'
import { JOB_STATUS_LABELS } from './constants'
import type { Job, JobDetail, JobErrorBrief, JobFilters, JobStatus, QueueStage, Stage } from './types'

export const PG_INT32_MAX = 2_147_483_647

const VALID_STAGES = new Set<Stage>(['annotation', 'qc1', 'qc2', 'done'])
const VALID_QUEUE_STAGES = new Set<QueueStage['stage']>(['annotation', 'qc1', 'qc2'])

export interface AssigneeOption extends SearchableOption {
  username: string
  roles: Role[]
  cvatLinked: boolean
}

export interface AssignValues {
  annotator?: number | null
  qc1_reviewer?: number | null
  note?: string
}

/** Phân tích chuỗi số nguyên dương từ URL query; trả về undefined nếu không hợp lệ. */
export function parsePositiveInt(raw: string | null): number | undefined {
  if (!raw) return undefined
  const num = Number(raw)
  return Number.isInteger(num) && num > 0 ? num : undefined
}

/** Đọc bộ lọc trang Jobs từ URLSearchParams. */
export function parseJobUrlFilters(
  sp: URLSearchParams,
): Omit<JobFilters, 'page' | 'page_size' | 'ordering'> {
  const rawStage = sp.get('stage') ?? ''
  const stage: Stage | '' = VALID_STAGES.has(rawStage as Stage) ? (rawStage as Stage) : ''
  return {
    stage,
    status: sp.get('status') || undefined,
    dataset: parsePositiveInt(sp.get('dataset')),
    batch: parsePositiveInt(sp.get('batch')),
    assignee: parsePositiveInt(sp.get('assignee')),
    search: sp.get('search') || undefined,
    escalated: sp.get('escalated') === '1',
    overdue: sp.get('overdue') === '1',
    due_soon: sp.get('due_soon') === '1',
    unassigned: sp.get('unassigned') === '1',
    locked: sp.get('locked') === '1',
    issue: parsePositiveInt(sp.get('issue')),
  }
}

/** Tuần tự hoá bộ lọc trang Jobs ra URLSearchParams, bỏ qua giá trị rỗng hoặc false. */
export function serializeJobUrlFilters(
  filters: Omit<JobFilters, 'page' | 'page_size' | 'ordering'>,
): URLSearchParams {
  const params = new URLSearchParams()
  if (filters.stage) params.set('stage', filters.stage)
  if (filters.status) params.set('status', filters.status)
  if (filters.dataset) params.set('dataset', String(filters.dataset))
  if (filters.batch) params.set('batch', String(filters.batch))
  if (filters.assignee) params.set('assignee', String(filters.assignee))
  if (filters.search?.trim()) params.set('search', filters.search.trim())
  if (filters.escalated) params.set('escalated', '1')
  if (filters.overdue) params.set('overdue', '1')
  if (filters.due_soon) params.set('due_soon', '1')
  if (filters.unassigned) params.set('unassigned', '1')
  if (filters.locked) params.set('locked', '1')
  if (filters.issue) params.set('issue', String(filters.issue))
  return params
}

/** Chu kỳ sắp xếp 3 trạng thái: tăng dần → giảm dần → bỏ sắp xếp. */
export function nextJobSortOrdering(
  currentOrdering: string | undefined,
  descriptor: { column?: string | number; direction?: 'ascending' | 'descending' },
): string | undefined {
  if (descriptor.column == null) return undefined
  const col = String(descriptor.column)
  if (currentOrdering === `-${col}`) return undefined
  return descriptor.direction === 'descending' ? `-${col}` : col
}

/** Lý do không sửa được người phụ trách (khớp ensure_editable + ASSIGN_LOCKED_STATUSES ở backend), null = sửa được. */
export function getJobLockReason(
  canManage: boolean,
  job: Pick<Job, 'is_locked' | 'status'>,
): string | null {
  if (!canManage) return 'Bạn không có quyền giao job'
  if (job.is_locked) return 'Job đang bị khoá'
  if (job.status === 'delivered') return 'Job đã bàn giao'
  if (job.status === 'qc1_passed' || job.status === 'pending_qc2' || job.status === 'approved') {
    return 'Không đổi người phụ trách sau khi job đã qua QC1'
  }
  return null
}

/** Lý do không thể giao lại hàng loạt (backend xử lý theo transaction: chỉ cần 1 job bị chặn là huỷ cả nhóm). */
export function getBulkAssignBlockReason(
  canManage: boolean,
  jobs: Pick<Job, 'is_locked' | 'status'>[],
): string | null {
  if (!canManage) return 'Bạn không có quyền giao job'
  for (const job of jobs) {
    const reason = getJobLockReason(canManage, job)
    if (reason) return reason
  }
  return null
}

/** Lý do không thể đặt deadline hàng loạt (khớp ensure_editable ở backend). */
export function getBulkDeadlineBlockReason(
  canManage: boolean,
  jobs: Pick<Job, 'is_locked' | 'status'>[],
): string | null {
  if (!canManage) return 'Bạn không có quyền đặt deadline'
  for (const job of jobs) {
    if (job.is_locked) return 'Trong vùng chọn có job đang bị khoá'
    if (job.status === 'delivered') return 'Trong vùng chọn có job đã bàn giao'
  }
  return null
}

/** Lý do không thể chuyển task hàng loạt (chỉ hỗ trợ job không gắn CVAT, chưa khoá/bàn giao). */
export function getBulkMoveBatchBlockReason(
  canManage: boolean,
  jobs: Pick<Job, 'is_locked' | 'status' | 'cvat_job_id'>[],
): string | null {
  if (!canManage) return 'Bạn không có quyền chuyển task'
  for (const job of jobs) {
    if (job.cvat_job_id != null) return 'Không thể chuyển task cho job đang gắn CVAT'
    if (job.is_locked) return 'Trong vùng chọn có job đang bị khoá'
    if (job.status === 'delivered') return 'Trong vùng chọn có job đã bàn giao'
  }
  return null
}

/** Lý do không sửa được người kiểm QC2 của mẫu audit đang mở. */
export function getQc2AssignBlockReason(
  canManageAudits: boolean,
  job: Pick<Job, 'is_locked' | 'status' | 'is_escalated' | 'escalation_policy' | 'qc2'>,
  projectPolicy?: 'block' | 'warn_only',
): string | null {
  if (!job.qc2) return 'Job chưa được lấy mẫu trong đợt audit QC2 đang mở'
  if (!canManageAudits) return 'Bạn không có quyền phân auditor'
  if (job.qc2.result !== 'pending') {
    return `Mẫu đã có kết quả (${job.qc2.result === 'pass' ? 'Pass' : 'Reject'})`
  }
  if (job.is_locked) return 'Job đang bị khoá'
  if (job.status === 'delivered') return 'Job đã bàn giao'
  if (isJobEscalationBlocked(job, projectPolicy)) return 'Job đang ở trạng thái Escalated'
  if (job.status !== 'pending_qc2') return 'Job không ở trạng thái Chờ QC2'
  return null
}

/** Vòng lỗi rework đang cần annotator xử lý (dùng total_rework_rounds để không lệch sau resolve-escalation). */
export function activeErrorRound(job: { rework_round: number; total_rework_rounds?: number }): number | null {
  const maxRound = Math.max(job.total_rework_rounds ?? 0, job.rework_round)
  return maxRound > 0 ? maxRound - 1 : null
}

/** Tách lỗi của job thành lỗi đang cần sửa ở vòng hiện tại và lịch sử các vòng trước / đã huỷ. */
export function splitActiveErrors(
  job: { rework_round: number; total_rework_rounds?: number },
  errors: JobErrorBrief[],
): { active: JobErrorBrief[]; history: JobErrorBrief[] } {
  const round = activeErrorRound(job)
  const active = errors.filter((e) => !e.is_voided && (round === null || e.rework_round === round))
  const history = errors.filter((e) => e.is_voided || (round !== null && e.rework_round !== round))
  return { active, history }
}

/** Kiểm tra bản ghi lỗi có metadata cấu trúc (frame, object, thiếu đối tượng, verdict, void, issue CVAT) hay không. */
export function hasStructuredErrorMeta(
  err: Pick<JobErrorBrief, 'frame_number' | 'cvat_object_id' | 'is_missing_object' | 'verdict' | 'is_voided' | 'cvat_issue_id'>,
): boolean {
  return (
    err.frame_number != null ||
    err.cvat_object_id != null ||
    err.cvat_issue_id != null ||
    Boolean(err.is_missing_object) ||
    err.verdict === 'edge' ||
    err.verdict === 'fail' ||
    Boolean(err.is_voided)
  )
}

/** Tóm tắt vị trí lỗi gồm frame / object ID / mô tả vị trí cho tiêu đề hoặc danh sách chọn. */
export function formatErrorLocationSummary(
  err: Pick<JobErrorBrief, 'frame_number' | 'cvat_object_id' | 'is_missing_object' | 'location'>,
): string {
  const parts: string[] = []
  if (err.frame_number != null) parts.push(`Frame #${err.frame_number}`)
  if (err.is_missing_object) parts.push('Thiếu đối tượng')
  else if (err.cvat_object_id != null) parts.push(`Object #${err.cvat_object_id}`)
  if (err.location) parts.push(err.location)
  return parts.join(' · ')
}

/** Phân tích số nguyên không bắt buộc trong ngưỡng int32 PostgreSQL. */
export function parseOptionalInt(raw: string, min: number): { valid: boolean; value: number | null } {
  const trimmed = raw.trim()
  if (!trimmed) return { valid: true, value: null }
  if (!/^\d+$/.test(trimmed)) return { valid: false, value: null }
  const num = Number(trimmed)
  if (!Number.isSafeInteger(num) || num < min || num > PG_INT32_MAX) return { valid: false, value: null }
  return { valid: true, value: num }
}

/** Đọc bộ lọc task và stage từ URLSearchParams của trang Data Queue. */
export function parseQueueUrlParams(
  sp: URLSearchParams,
): { batch?: number; stage: '' | QueueStage['stage'] } {
  const batch = parsePositiveInt(sp.get('batch'))
  const rawStage = sp.get('stage') ?? ''
  const stage: '' | QueueStage['stage'] = VALID_QUEUE_STAGES.has(rawStage as QueueStage['stage'])
    ? (rawStage as QueueStage['stage'])
    : ''
  return { batch, stage }
}

/** Tạo URL tương đối dẫn từ Data Queue sang danh sách Jobs với ngữ cảnh lọc hiện tại. */
export function buildQueueJobsUrl(
  batch: number | undefined,
  extra: Record<string, string | number | undefined>,
): string {
  const params = new URLSearchParams()
  if (batch) params.set('batch', String(batch))
  for (const [k, v] of Object.entries(extra)) {
    if (v !== undefined && v !== '') params.set(k, String(v))
  }
  const qs = params.toString()
  return qs ? `../jobs?${qs}` : '../jobs'
}

/** Xây dựng danh sách lựa chọn người phụ trách, áp dụng luật bốn mắt và cảnh báo chưa liên kết CVAT. */
export function buildAssigneeOptions(
  options: Member[],
  value: UserBrief | null,
  blockedIds: number[] = [],
): { items: AssigneeOption[]; selectedUnlinked: boolean } {
  const blockedSet = new Set(blockedIds)
  const items: AssigneeOption[] = options.map((m) => ({
    id: m.user.id,
    label: m.user.full_name,
    searchText: `${m.user.full_name} ${m.user.username}`,
    username: m.user.username,
    roles: m.roles,
    cvatLinked: m.cvat_linked,
    isDisabled: blockedSet.has(m.user.id),
  }))

  // Người đang được giao nhưng không còn trong danh sách (vd. đã mất vai trò) vẫn phải hiện đúng tên.
  if (value && !items.some((i) => i.id === value.id)) {
    items.unshift({
      id: value.id,
      label: value.full_name,
      searchText: `${value.full_name} ${value.username}`,
      username: value.username,
      roles: [],
      cvatLinked: true,
      isDisabled: true,
    })
  }

  const selectedUnlinked = value != null && items.find((i) => i.id === value.id)?.cvatLinked === false
  return { items, selectedUnlinked }
}

/** Tạo payload gửi API giao job chỉ gồm các field đã thay đổi; trả về null nếu chưa sửa gì. */
export function buildAssignPayload(input: {
  touchedAnnotator: boolean
  touchedQc1: boolean
  annotator: number | null
  qc1Reviewer: number | null
  note: string
}): AssignValues | null {
  if (!input.touchedAnnotator && !input.touchedQc1) return null
  const payload: AssignValues = { note: input.note }
  if (input.touchedAnnotator) payload.annotator = input.annotator
  if (input.touchedQc1) payload.qc1_reviewer = input.qc1Reviewer
  return payload
}

/** Mô tả tóm tắt sự kiện trong dòng thời gian của chi tiết job. */
export function describeTimelineEvent(event: JobDetail['timeline'][number]): string {
  const after = event.after ?? {}
  if (event.action === 'job.status' || event.action.startsWith('qc1.') || event.action.startsWith('qc2.')) {
    const status = after.status as JobStatus | undefined
    return status ? `→ ${JOB_STATUS_LABELS[status] ?? status}` : ''
  }
  if (event.action === 'job.deadline') {
    const d = after.deadline as string | null
    return `→ ${d ? formatDateTime(d) : 'không có deadline'}`
  }
  return ''
}

/** Kiểm tra job bị chặn thao tác vì Escalated (chỉ chặn khi chính sách là BLOCK, không chặn ở WARN_ONLY). */
export function isJobEscalationBlocked(
  job: Pick<Job, 'is_escalated' | 'escalation_policy'>,
  projectPolicy?: 'block' | 'warn_only',
): boolean {
  const policy = job.escalation_policy ?? projectPolicy ?? 'block'
  return Boolean(job.is_escalated && policy !== 'warn_only')
}

/** Kiểm tra job đang ở trạng thái Escalated nhưng chạy chế độ cảnh báo (WARN_ONLY — vẫn thao tác tiếp được). */
export function isJobEscalationWarnOnly(
  job: Pick<Job, 'is_escalated' | 'escalation_policy'>,
  projectPolicy?: 'block' | 'warn_only',
): boolean {
  const policy = job.escalation_policy ?? projectPolicy ?? 'block'
  return Boolean(job.is_escalated && policy === 'warn_only')
}

/** Định dạng phần thiếu / vượt chỉ tiêu KPI (KPI03 & KPI04). */
export function formatKpiDeltaText(
  shortfall: number,
  surplus: number | undefined,
  unit = '',
  formatter: (n: number) => string = String,
): string {
  const suffix = unit ? ` ${unit}` : ''
  if ((surplus ?? 0) > 0) return `vượt ${formatter(surplus ?? 0)}${suffix}`
  if (shortfall > 0) return `thiếu ${formatter(shortfall)}${suffix}`
  return 'đạt chỉ tiêu'
}

/** Màu chấm tròn hiển thị theo loại sự kiện dòng thời gian. */
export function timelineDotColor(action: string): string {
  if (action === 'qc2.reject') return 'bg-fg-error-primary'
  if (action === 'qc2.pass') return 'bg-fg-success-primary'
  return 'bg-brand-solid'
}

