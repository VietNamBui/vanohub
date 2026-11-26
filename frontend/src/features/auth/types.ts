import type { Role } from '../../shared/types/roles'

export interface RoleAssignment {
  id: number
  role: Role
  project: number
  project_name: string | null
}

/** Dữ liệu trả về từ GET /api/auth/me/ */
export interface CurrentUser {
  id: number
  username: string
  first_name: string
  last_name: string
  email: string
  role_assignments: RoleAssignment[]
}

export interface TokenPair {
  access: string
  refresh: string
}
