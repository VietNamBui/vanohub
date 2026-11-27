import type { ProjectSummary } from '../features/projects/types'
import RoleBadges from '../shared/components/RoleBadges'
import type { Role } from '../shared/types/roles'

/**
 * Vai trò của tài khoản đang đăng nhập, hiện cạnh tên trên thanh trên cùng.
 * - Trong một dự án: vai trò ở dự án đó.
 * - Ngoài dự án (vd. trang chọn dự án): gộp vai trò ở mọi dự án mình tham gia.
 */
export default function HeaderRoles({ projects, projectId }: { projects: ProjectSummary[]; projectId: number | null }) {
  const scoped = projectId === null ? projects : projects.filter((p) => p.id === projectId)
  const roles: Role[] = [...new Set(scoped.flatMap((p) => p.my_roles))]
  if (roles.length === 0) return null
  return <RoleBadges roles={roles} short />
}
