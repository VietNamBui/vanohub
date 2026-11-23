// Khớp với accounts.models.Role ở backend (giá trị lưu trong DB).
export type Role = 'director' | 'project_manager' | 'qc2' | 'team_leader' | 'qc1' | 'annotator'

export const ROLE_LABELS: Record<Role, string> = {
  director: 'Director',
  project_manager: 'Project Manager',
  qc2: 'QC2 Auditor',
  team_leader: 'Team Leader',
  qc1: 'QC1 Reviewer',
  annotator: 'Annotator',
}

/** Thứ tự hiển thị từ cao xuống thấp. */
export const ROLE_ORDER: Role[] = ['director', 'project_manager', 'qc2', 'team_leader', 'qc1', 'annotator']

/** Nhãn ngắn dùng trong bảng chật chỗ. */
export const ROLE_SHORT_LABELS: Record<Role, string> = {
  director: 'Director',
  project_manager: 'PM',
  qc2: 'QC2',
  team_leader: 'TL',
  qc1: 'QC1',
  annotator: 'Annotator',
}

/**
 * ĐỀ XUẤT (chưa chốt) — khớp GRANTABLE_ROLES ở backend (projects/views.py):
 * PM gán thêm được các vai trò này; PM và Director do Director quản lý.
 */
export const GRANTABLE_ROLES: Role[] = ['qc2', 'team_leader', 'qc1', 'annotator']
