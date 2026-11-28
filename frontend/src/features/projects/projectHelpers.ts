import type {
  ActivityLog,
  Delivery,
  DeliveryCandidate,
  EscalationPolicy,
  ProjectSettingsUpdateInput,
  ProjectSyncResult,
  UnifiedNotification,
} from './types'

const PG_INT32_MAX = 2_147_483_647
const PG_INT16_MAX = 32_767
const DECIMAL_RE = /^\d+(?:\.\d{1,2})?$/

export interface ChecklistSection {
  title: string
  body: string
}

/** Phân tích nội dung Markdown hướng dẫn theo tiêu đề # / ## thành từng mục kiểm tra. */
export function parseGuidelineSections(markdown: string): ChecklistSection[] {
  const lines = markdown.split('\n')
  const sections: ChecklistSection[] = []
  let currentTitle = ''
  let bodyLines: string[] = []

  const flush = () => {
    const body = bodyLines.join('\n').trim()
    if (currentTitle || body) {
      sections.push({ title: currentTitle || 'Nội dung hướng dẫn', body })
    }
    currentTitle = ''
    bodyLines = []
  }

  for (const raw of lines) {
    const line = raw.trim()
    if (!line) continue
    if (line.startsWith('## ')) {
      flush()
      currentTitle = line.replace(/^##\s+/, '').trim()
    } else if (line.startsWith('# ')) {
      flush()
      currentTitle = line.replace(/^#\s+/, '').trim()
    } else {
      bodyLines.push(line.replace(/^[-*]\s+/, '• '))
    }
  }
  flush()
  return sections
}

/** Kiểm tra dữ liệu nhập trước khi xuất bản phiên bản hướng dẫn mới. */
export function validateGuidelineDraft(
  title: string,
  content: string,
): {
  titleError: string | null
  contentError: string | null
  trimmedTitle: string
  trimmedContent: string
  valid: boolean
} {
  const trimmedTitle = title.trim()
  const trimmedContent = content.trim()
  const titleError = trimmedTitle ? null : 'Vui lòng nhập tiêu đề.'
  const contentError = trimmedContent ? null : 'Vui lòng nhập nội dung hướng dẫn.'
  return {
    titleError,
    contentError,
    trimmedTitle,
    trimmedContent,
    valid: Boolean(trimmedTitle && trimmedContent),
  }
}

/** Định dạng thông báo tóm tắt kết quả đồng bộ organization với CVAT. */
export function formatCvatSyncSummary(result: ProjectSyncResult): string {
  const parts = [
    `${result.projects} project, ${result.tasks} task`,
    result.projects_created ? `${result.projects_created} project mới` : null,
    result.tasks_created ? `${result.tasks_created} task mới` : null,
    result.jobs_created ? `${result.jobs_created} job mới` : null,
    result.jobs_updated ? `${result.jobs_updated} job cập nhật` : null,
  ].filter(Boolean)
  return `Đã đồng bộ CVAT: ${parts.join(', ')}.`
}

/** Chỉ đánh dấu đã đọc qua API cho thông báo lưu DB (`sys-*`, `ann-*`), bỏ qua cảnh báo hạn động `due-*`. */
export function canMarkNotificationRead(
  item: Pick<UnifiedNotification, 'id' | 'source' | 'is_read' | 'is_pinned_pending'>,
): boolean {
  if (item.is_read || item.is_pinned_pending) return false
  if (item.source === 'deadline' || item.id.startsWith('due-')) return false
  return true
}

/** Sắp xếp thông báo đồng nhất với backend: ghim chưa đọc lên đầu, sau đó mới nhất trước. */
export function sortUnifiedNotifications<
  T extends Pick<UnifiedNotification, 'is_read' | 'is_pinned_pending' | 'created_at'>,
>(items: T[]): T[] {
  return [...items].sort((a, b) => {
    const aPinnedUnread = !a.is_read && a.is_pinned_pending
    const bPinnedUnread = !b.is_read && b.is_pinned_pending
    if (aPinnedUnread !== bPinnedUnread) return aPinnedUnread ? -1 : 1
    return b.created_at.localeCompare(a.created_at)
  })
}

export interface ProjectSettingsDraft {
  max_rework_rounds: number
  escalation_policy: EscalationPolicy
  annotator_wip_limit: number
  sampling_rate: number
  quality_cl_threshold: string
  defect_rate_threshold: string
  kpi_annotation_target: string
  kpi_qc1_target: string
  kpi_qc2_target: string
}

export function validateProjectSettingsDraft(draft: ProjectSettingsDraft): {
  valid: boolean
  errors: Partial<Record<keyof ProjectSettingsDraft, string>>
  payload: ProjectSettingsUpdateInput | null
} {
  const errors: Partial<Record<keyof ProjectSettingsDraft, string>> = {}

  if (!Number.isInteger(draft.max_rework_rounds) || draft.max_rework_rounds < 1 || draft.max_rework_rounds > PG_INT16_MAX) {
    errors.max_rework_rounds = 'Số vòng rework tối đa phải là số nguyên từ 1 đến 32.767.'
  }
  if (!Number.isInteger(draft.annotator_wip_limit) || draft.annotator_wip_limit < 1 || draft.annotator_wip_limit > 50) {
    errors.annotator_wip_limit = 'Giới hạn job giữ cùng lúc phải nằm trong khoảng 1..50.'
  }
  if (!Number.isInteger(draft.sampling_rate) || draft.sampling_rate < 1 || draft.sampling_rate > 100) {
    errors.sampling_rate = 'Tỉ lệ frame QC2 kiểm phải nằm trong khoảng 1..100%.'
  }

  const parsePercentDecimal = (raw: string, key: 'quality_cl_threshold' | 'defect_rate_threshold'): string | null => {
    const trimmed = raw.trim()
    if (!trimmed) return null
    if (!DECIMAL_RE.test(trimmed)) {
      errors[key] = 'Nhập phần trăm hợp lệ từ 0 đến 100 (tối đa 2 chữ số thập phân).'
      return null
    }
    const num = Number(trimmed)
    if (!Number.isFinite(num) || num < 0 || num > 100) {
      errors[key] = 'Giá trị ngưỡng phải nằm trong khoảng 0..100%.'
      return null
    }
    return num.toFixed(2)
  }

  const parseOptionalPositiveInt = (
    raw: string,
    key: 'kpi_annotation_target' | 'kpi_qc1_target' | 'kpi_qc2_target',
  ): number | null => {
    const trimmed = raw.trim()
    if (!trimmed) return null
    if (!/^\d+$/.test(trimmed)) {
      errors[key] = 'Chỉ tiêu KPI phải là số nguyên dương.'
      return null
    }
    const num = Number(trimmed)
    if (!Number.isSafeInteger(num) || num < 1 || num > PG_INT32_MAX) {
      errors[key] = 'Chỉ tiêu KPI phải là số nguyên từ 1 trở lên.'
      return null
    }
    return num
  }

  const qualityCl = parsePercentDecimal(draft.quality_cl_threshold, 'quality_cl_threshold')
  const defectRate = parsePercentDecimal(draft.defect_rate_threshold, 'defect_rate_threshold')
  const kpiAnno = parseOptionalPositiveInt(draft.kpi_annotation_target, 'kpi_annotation_target')
  const kpiQc1 = parseOptionalPositiveInt(draft.kpi_qc1_target, 'kpi_qc1_target')
  const kpiQc2 = parseOptionalPositiveInt(draft.kpi_qc2_target, 'kpi_qc2_target')

  const valid = Object.keys(errors).length === 0
  return {
    valid,
    errors,
    payload: valid
      ? {
          max_rework_rounds: draft.max_rework_rounds,
          escalation_policy: draft.escalation_policy,
          annotator_wip_limit: draft.annotator_wip_limit,
          sampling_rate: draft.sampling_rate,
          quality_cl_threshold: qualityCl,
          defect_rate_threshold: defectRate,
          kpi_annotation_target: kpiAnno,
          kpi_qc1_target: kpiQc1,
          kpi_qc2_target: kpiQc2,
        }
      : null,
  }
}

export function validateDeliveryUpdateInput(input: {
  recipient: string
  output_path: string
  note: string
  client_feedback: string
}): {
  valid: boolean
  recipientError: string | null
  outputPathError: string | null
  payload: { recipient: string; output_path: string; note: string; client_feedback: string } | null
} {
  const recipient = input.recipient.trim()
  const outputPath = input.output_path.trim()
  const recipientError = recipient ? null : 'Người nhận bàn giao không được để trống.'
  const outputPathError = outputPath ? null : 'Đường dẫn đầu ra không được để trống.'
  const valid = Boolean(recipient && outputPath)
  return {
    valid,
    recipientError,
    outputPathError,
    payload: valid
      ? {
          recipient,
          output_path: outputPath,
          note: input.note.trim(),
          client_feedback: input.client_feedback.trim(),
        }
      : null,
  }
}

export function computeDeliveryDh07Summary(
  deliveries: Pick<Delivery, 'deadline' | 'is_on_time'>[],
  candidates: Pick<DeliveryCandidate, 'is_overdue'>[],
): {
  onTimeCount: number
  lateCount: number
  overdueUndeliveredCount: number
  dueCount: number
  rate: number | null
} {
  const dueDelivered = deliveries.filter((d) => d.deadline != null)
  const onTimeCount = dueDelivered.filter((d) => d.is_on_time === true).length
  const lateCount = dueDelivered.length - onTimeCount
  const overdueUndeliveredCount = candidates.filter((c) => c.is_overdue).length
  const dueCount = dueDelivered.length + overdueUndeliveredCount
  return {
    onTimeCount,
    lateCount,
    overdueUndeliveredCount,
    dueCount,
    rate: dueCount > 0 ? Math.round((onTimeCount * 1000) / dueCount) / 10 : null,
  }
}

export const ACTIVITY_ACTION_LABELS: Record<string, string> = {
  'project.create': 'Tạo organization',
  'project.update': 'Cập nhật organization',
  'project.settings': 'Đổi cấu hình organization',
  'member.create': 'Tạo tài khoản thành viên',
  'member.add_role': 'Gán thêm vai trò',
  'member.remove_role': 'Gỡ vai trò',
  'member.view_password': 'Xem mật khẩu tạm',
  'member.reset_password': 'Cấp lại mật khẩu tạm',
  'team.create': 'Tạo team',
  'team.update': 'Sửa team',
  'team.delete': 'Xoá team',
  'team.add_member': 'Thêm thành viên vào team',
  'team.remove_member': 'Gỡ thành viên khỏi team',
  'team.set_capacity': 'Đổi định mức team',
  'team.transfer': 'Điều chuyển team',
  'dataset.create': 'Tạo project',
  'dataset.lock': 'Khoá project',
  'dataset.unlock': 'Mở khoá project',
  'batch.create': 'Tạo task',
  'batch.assign_team': 'Phân team phụ trách task',
  'batch.deadline': 'Đổi deadline task',
  'batch.lock': 'Khoá task',
  'batch.unlock': 'Mở khoá task',
  'batch.confirm_qc2': 'Xác nhận chuyển QC2',
  'batch.deliver': 'Bàn giao task',
  'delivery.update': 'Cập nhật bàn giao',
  'job.import': 'Nhập job từ CVAT',
  'job.status': 'Đổi trạng thái job',
  'job.assign': 'Giao / giao lại job',
  'job.deadline': 'Đổi deadline job',
  'job.lock': 'Khoá job',
  'job.unlock': 'Mở khoá job',
  'job.resolve_escalation': 'Xử lý escalation',
  'job.move_batch': 'Chuyển task cho job',
  'qc1.start': 'Bắt đầu kiểm tra QC1',
  'qc1.pass': 'QC1 Pass',
  'qc1.reject': 'QC1 Reject',
  'qc2.pass': 'QC2 Pass',
  'qc2.reject': 'QC2 Reject',
  'qc2.assign_auditor': 'Phân auditor QC2',
  'audit.create': 'Tạo đợt audit QC2',
  'audit.complete': 'Chốt đợt audit QC2',
  'error_category.create': 'Thêm danh mục lỗi',
  'error_category.update': 'Sửa danh mục lỗi',
  'guideline.publish': 'Xuất bản guideline',
  'announcement.send': 'Gửi thông báo',
  'annotator.dispute': 'Phản hồi lỗi QC',
  'annotator.data_issue': 'Báo vấn đề dữ liệu',
  'annotator.request_resolve': 'Xử lý yêu cầu Annotator',
  'annotator_request.resolve': 'Xử lý yêu cầu Annotator',
  'cvat.link': 'Liên kết tài khoản CVAT',
  'cvat.unlink': 'Huỷ liên kết CVAT',
  'cvat.sync': 'Đồng bộ CVAT',
  'cvat.assignee_push': 'Đẩy người giữ job sang CVAT',
  'cvat.org_invite': 'Mời vào CVAT organization',
}

export const ACTIVITY_ACTION_PREFIX_OPTIONS = [
  { id: '', label: 'Tất cả hành động' },
  { id: 'job.', label: 'Job (giao, trạng thái, hạn, khoá)' },
  { id: 'qc1.', label: 'Kiểm tra QC1' },
  { id: 'qc2.', label: 'Audit QC2' },
  { id: 'audit.', label: 'Đợt audit QC2' },
  { id: 'batch.', label: 'Task (deadline, team, QC2, bàn giao)' },
  { id: 'dataset.', label: 'Project (khoá / mở khoá)' },
  { id: 'delivery.', label: 'Cập nhật bàn giao' },
  { id: 'team.', label: 'Team & điều chuyển' },
  { id: 'member.', label: 'Thành viên & vai trò' },
  { id: 'project.', label: 'Organization & cấu hình' },
  { id: 'annotator.', label: 'Yêu cầu từ Annotator' },
  { id: 'error_category.', label: 'Danh mục lỗi' },
  { id: 'guideline.', label: 'Guidelines' },
  { id: 'announcement.', label: 'Thông báo' },
  { id: 'cvat.', label: 'Đồng bộ & liên kết CVAT' },
]

export function formatActivityChangeSummary(log: Pick<ActivityLog, 'before' | 'after'>): string {
  const parts: string[] = []
  const formatObj = (obj: Record<string, unknown> | null) => {
    if (!obj) return ''
    return Object.entries(obj)
      .map(([k, v]) => `${k}: ${v == null ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
      .join(', ')
  }
  const beforeStr = formatObj(log.before)
  const afterStr = formatObj(log.after)
  if (beforeStr) parts.push(`Trước: ${beforeStr}`)
  if (afterStr) parts.push(`Sau: ${afterStr}`)
  return parts.join(' → ')
}

