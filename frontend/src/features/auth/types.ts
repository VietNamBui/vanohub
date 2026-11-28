import type { Capability } from '../../shared/types/capabilities'
import type { Role } from '../../shared/types/roles'

export interface RoleAssignment {
  id: number
  role: Role
  project: number
  project_name: string | null
}

export interface UserProjectScope {
  id: number
  name: string
  cvat_org_slug: string
  roles: Role[]
  direct_roles: Role[]
  capabilities: Capability[]
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
  is_pm: boolean
  cvat_linked?: boolean
  cvat_username?: string | null
  role_assignments: RoleAssignment[]
  projects: UserProjectScope[]
}

export interface ProfileUpdateInput {
  first_name?: string
  last_name?: string
  full_name?: string
  email?: string
  avatar_url?: string
  notify_rework?: boolean
  notify_deadline?: boolean
  notify_request_updates?: boolean
  notify_qc_pass?: boolean
}

export interface TokenPair {
  access: string
  refresh: string
}
