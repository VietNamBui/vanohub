import SearchableSelect, { type SearchableOption } from '../../../shared/components/ui/SearchableSelect'
import { useRequest } from '../../../shared/hooks/useRequest'
import type { Role } from '../../../shared/types/roles'
import { listMembers } from '../api'

export interface MemberSelectProps {
  projectId: number
  role?: Role
  value?: number | null
  onChange?: (userId: number | null) => void
  label?: string
  hint?: string
  placeholder?: string
  allowClear?: boolean
  size?: 'sm' | 'md'
  disabled?: boolean
  className?: string
  popoverClassName?: string
  ariaLabel?: string
}

/** Chọn người trong dự án, có thể lọc theo vai trò (vd. chỉ Annotator) và tìm kiếm theo tên/username. */
export default function MemberSelect({
  projectId,
  role,
  value,
  onChange,
  label,
  hint,
  placeholder = 'Chọn người',
  allowClear = true,
  size = 'md',
  disabled,
  className,
  popoverClassName,
  ariaLabel,
}: MemberSelectProps) {
  const { data: members, isLoading } = useRequest(`members:${projectId}:${role ?? ''}`, () =>
    listMembers(projectId, role),
  )

  const items: SearchableOption[] = (members ?? []).map((m) => ({
    id: m.user.id,
    label: `${m.user.full_name} (${m.user.username})`,
    searchText: `${m.user.full_name} ${m.user.username} ${m.team?.name ?? ''}`,
    supportingText: `${m.active_jobs} job${m.team ? ` · ${m.team.name}` : ''}`,
  }))

  const selectedKey = value != null && items.some((i) => i.id === value) ? value : null

  return (
    <SearchableSelect
      label={label}
      hint={hint}
      size={size}
      className={className}
      popoverClassName={popoverClassName}
      ariaLabel={ariaLabel ?? label ?? placeholder}
      placeholder={placeholder}
      searchPlaceholder="Tìm tên hoặc username…"
      allowClear={allowClear}
      clearLabel="Bỏ chọn / Chưa giao"
      isDisabled={disabled || isLoading}
      items={items}
      selectedKey={selectedKey}
      onSelectionChange={(key) => onChange?.(key == null ? null : Number(key))}
    />
  )
}
