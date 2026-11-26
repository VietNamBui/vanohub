import type { Role } from '../../shared/types/roles'

export interface RoleAssignment {
  id: number
  role: Role
  project: number
  project_name: string
}

/** Dữ liệu trả về từ GET/PATCH /api/auth/me/ */
export interface CurrentUser {
  id: number
  username: string
  first_name: string
  last_name: string
  full_name?: string
  email: string
  avatar_url?: string
  cvat_username?: string
  timezone_name?: string
  notify_rework?: boolean
  notify_deadline?: boolean
  notify_request_updates?: boolean
  notify_qc_pass?: boolean
  role_assignments: RoleAssignment[]
}

export interface ProfileUpdateInput {
  first_name?: string
  last_name?: string
  full_name?: string
  email?: string
  avatar_url?: string
  cvat_username?: string
  timezone_name?: string
  notify_rework?: boolean
  notify_deadline?: boolean
  notify_request_updates?: boolean
  notify_qc_pass?: boolean
}

export interface TokenPair {
  access: string
  refresh: string
}
