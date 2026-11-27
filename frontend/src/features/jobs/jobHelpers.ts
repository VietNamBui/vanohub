import type { UserBrief } from '../../shared/api/types'
import type { SearchableOption } from '../../shared/components/ui/searchableSelectUtils'
import type { Role } from '../../shared/types/roles'
import { formatDateTime } from '../../shared/utils/format'
import type { Member } from '../projects/types'
import { JOB_STATUS_LABELS } from './constants'
import type { Job, JobDetail, JobErrorBrief, JobFilters, JobStatus, QueueStage, Stage } from './types'

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

/** Màu chấm tròn hiển thị theo loại sự kiện dòng thời gian. */
export function timelineDotColor(action: string): string {
  if (action === 'qc2.reject') return 'bg-fg-error-primary'
  if (action === 'qc2.pass') return 'bg-fg-success-primary'
  return 'bg-brand-solid'
}

