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
  'dataset.create': 'Tạo dataset',
  'dataset.lock': 'Khoá dataset',
  'dataset.unlock': 'Mở khoá dataset',
  'batch.create': 'Tạo batch',
  'batch.lock': 'Khoá batch',
  'batch.unlock': 'Mở khoá batch',
  'batch.deadline': 'Đổi deadline batch',
  'batch.deliver': 'Bàn giao batch',
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
}
