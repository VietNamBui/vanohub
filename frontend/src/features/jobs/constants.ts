import type { JobStatus, Stage } from './types'

export const JOB_STATUS_LABELS: Record<JobStatus, string> = {
  pending_annotation: 'Chờ annotate',
  annotating: 'Đang annotate',
  pending_qc1: 'Chờ QC1',
  qc1_reviewing: 'Đang QC1',
  rework: 'Rework',
  pending_qc2: 'Chờ QC2',
  approved: 'Đã duyệt',
  delivered: 'Đã bàn giao',
}

// Màu chỉ để hỗ trợ — nhãn chữ luôn đi kèm nên không phụ thuộc vào việc phân biệt màu.
export const JOB_STATUS_COLORS: Record<JobStatus, string> = {
  pending_annotation: 'default',
  annotating: 'processing',
  pending_qc1: 'gold',
  qc1_reviewing: 'gold',
  rework: 'volcano',
  pending_qc2: 'purple',
  approved: 'success',
  delivered: 'cyan',
}

export const STAGE_LABELS: Record<Stage, string> = {
  annotation: 'Annotation',
  qc1: 'QC1',
  qc2: 'QC2',
  done: 'Hoàn tất',
}

export const ACTION_LABELS: Record<string, string> = {
  'job.import': 'Nhập từ CVAT',
  'job.status': 'Đổi trạng thái',
  'job.assign': 'Giao việc',
  'job.deadline': 'Đổi deadline',
  'job.lock': 'Khoá job',
  'job.unlock': 'Mở khoá job',
  'job.resolve_escalation': 'Xử lý escalation',
  'qc1.start': 'Bắt đầu QC1',
  'qc1.pass': 'QC1 Pass',
  'qc1.reject': 'QC1 Reject',
  'qc2.pass': 'QC2 Pass',
  'qc2.reject': 'QC2 Reject',
  'qc2.assign_auditor': 'Phân auditor QC2',
  'dataset.create': 'Tạo project',
  'dataset.lock': 'Khoá project',
  'dataset.unlock': 'Mở khoá project',
  'batch.create': 'Tạo task',
  'batch.lock': 'Khoá task',
  'batch.unlock': 'Mở khoá task',
  'batch.deadline': 'Đổi deadline task',
  'batch.deliver': 'Bàn giao task',
  'audit.create': 'Tạo audit',
  'audit.complete': 'Chốt audit',
  'team.create': 'Tạo team',
  'team.update': 'Sửa team',
  'team.add_member': 'Thêm thành viên',
  'team.remove_member': 'Bỏ thành viên',
  'team.transfer': 'Điều chuyển',
  'project.settings': 'Đổi cấu hình',
  'error_category.create': 'Thêm loại lỗi',
  'error_category.update': 'Sửa loại lỗi',
  'guideline.publish': 'Xuất bản guideline',
  'announcement.send': 'Gửi thông báo',
  'annotator.dispute': 'Phản hồi lỗi QC1',
  'annotator.data_issue': 'Báo dữ liệu bị chặn',
}

/** Định dạng thời gian còn lại / quá hạn ("Còn 8 giờ", "Quá hạn 3 giờ"). */
export function formatDeadlineCountdown(hoursRemaining?: number | null): { text: string; tone: 'error' | 'warning' | 'gray' } | null {
  if (hoursRemaining == null) return null
  if (hoursRemaining < 0) {
    const h = Math.max(1, Math.round(Math.abs(hoursRemaining)))
    return { text: `Quá hạn ${h} giờ`, tone: 'error' }
  }
  const h = Math.max(1, Math.round(hoursRemaining))
  if (hoursRemaining <= 24) {
    return { text: `Còn ${h} giờ`, tone: 'warning' }
  }
  return { text: `Còn ${h} giờ`, tone: 'gray' }
}
