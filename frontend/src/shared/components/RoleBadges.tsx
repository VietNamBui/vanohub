import { Badge } from '@/components/base/badges/badges'
import type { BadgeColors } from '@/components/base/badges/badge-types'
import { ROLE_LABELS, ROLE_ORDER, ROLE_SHORT_LABELS, type Role } from '../types/roles'

const ROLE_COLORS: Record<Role, BadgeColors> = {
  project_manager: 'blue',
  qc2: 'indigo',
  qc1: 'success',
  annotator: 'gray',
}

/** Hiển thị danh sách vai trò theo thứ tự cố định. `short` → nhãn ngắn (TL, QC1...). */
export default function RoleBadges({ roles, short = false }: { roles: Role[]; short?: boolean }) {
  if (roles.length === 0) return <span className="text-sm text-quaternary">Không có vai trò</span>
  return (
    <span className="inline-flex flex-wrap gap-1">
      {ROLE_ORDER.filter((role) => roles.includes(role)).map((role) => <RoleBadge key={role} role={role} short={short} />)}
    </span>
  )
}

/** Một badge vai trò (dùng riêng khi cần bọc thêm nút, vd. nút gỡ vai trò). */
export function RoleBadge({ role, short = false }: { role: Role; short?: boolean }) {
  return (
    <Badge type="color" size="sm" color={ROLE_COLORS[role]}>
      {short ? ROLE_SHORT_LABELS[role] : ROLE_LABELS[role]}
    </Badge>
  )
}
