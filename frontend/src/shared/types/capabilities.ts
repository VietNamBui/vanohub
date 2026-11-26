// Khớp với accounts/permissions.py (class Cap) ở backend.
export type Capability =
  | 'view_project'
  | 'view_dashboard'
  | 'view_jobs'
  | 'manage_data'
  | 'manage_jobs'
  | 'manage_team'
  | 'manage_settings'
  | 'manage_audits'
  | 'perform_audit'
  | 'manage_quality_catalog'
  | 'view_guidelines'
  | 'manage_delivery'
  | 'send_announcement'
  | 'view_activity'
  | 'annotate_jobs'
  | 'perform_qc1'

export const CAPABILITY_LABELS: Record<Capability, string> = {
  view_project: 'Xem dự án',
  view_dashboard: 'Xem dashboard dự án',
  view_jobs: 'Xem toàn bộ Job',
  manage_data: 'Quản lý Dataset / Batch, nhập từ CVAT',
  manage_jobs: 'Giao lại job, deadline, khoá, xử lý escalation',
  manage_team: 'Quản lý team, roster, điều chuyển',
  manage_settings: 'Cấu hình rework, sampling, KPI',
  manage_audits: 'Tạo / chốt audit QC2, phân auditor',
  perform_audit: 'Thực hiện QC2 (Pass / Reject, ghi lỗi)',
  manage_quality_catalog: 'Quản lý danh mục lỗi, guideline',
  view_guidelines: 'Xem hướng dẫn gán nhãn',
  manage_delivery: 'Bàn giao',
  send_announcement: 'Gửi thông báo',
  view_activity: 'Xem nhật ký hoạt động',
  annotate_jobs: 'Thực hiện gán nhãn và nộp bài (Annotator)',
  perform_qc1: 'Thực hiện kiểm tra Level 1 QC (Pass / Reject, ghi lỗi)',
}
