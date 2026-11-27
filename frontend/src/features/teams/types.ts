import type { UserBrief } from '../../shared/api/types'
import type { Role } from '../../shared/types/roles'

export interface TeamMember {
  id: number
  user: UserBrief
  /** Vai trò hiệu lực trong dự án (backend trả kèm). */
  roles: Role[]
  direct_roles: Role[]
  capacity: number
  joined_at: string
}

export interface Team {
  id: number
  name: string
  members: TeamMember[]
  created_at: string
}

export interface Workload {
  user: UserBrief
  team: { id: number; name: string }
  roles: Role[]
  capacity: number
  holding: number
  qc1_holding: number
  due_soon: number
  escalated: number
}
