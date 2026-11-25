import type { Role } from '../../shared/types/roles'

export interface RoleAssignment {
  id: number
  role: Role
  project: number | null // null = phạm vi toàn tổ chức (Director)
  project_name: string | null
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
  timezone_name?: string
  notify_rework?: boolean
  notify_deadline?: boolean
  notify_request_updates?: boolean
  notify_qc_pass?: boolean
  is_director: boolean
  role_assignments: RoleAssignment[]
}

export interface ProfileUpdateInput {
  first_name?: string
  last_name?: string
  full_name?: string
  email?: string
  avatar_url?: string
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
