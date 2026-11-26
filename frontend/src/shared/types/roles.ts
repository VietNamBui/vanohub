// Khớp với accounts.models.Role ở backend (giá trị lưu trong DB).
// Chốt 2026-11-26: chỉ còn 4 vai trò — bỏ Director và Team Leader, PM quản lý tất cả.
export type Role = 'project_manager' | 'qc2' | 'qc1' | 'annotator'

export const ROLE_LABELS: Record<Role, string> = {
  project_manager: 'Project Manager',
  qc2: 'QC2 Auditor',
  qc1: 'QC1 Reviewer',
  annotator: 'Annotator',
}

/** Thứ tự hiển thị từ cao xuống thấp. */
export const ROLE_ORDER: Role[] = ['project_manager', 'qc2', 'qc1', 'annotator']

/** Nhãn ngắn dùng trong bảng chật chỗ. */
export const ROLE_SHORT_LABELS: Record<Role, string> = {
  project_manager: 'PM',
  qc2: 'QC2',
  qc1: 'QC1',
  annotator: 'Annotator',
}

/** Khớp GRANTABLE_ROLES ở backend (projects/views.py): PM gán / gỡ được các vai trò này; PM lấy từ CVAT organization. */
export const GRANTABLE_ROLES: Role[] = ['qc2', 'qc1', 'annotator']
