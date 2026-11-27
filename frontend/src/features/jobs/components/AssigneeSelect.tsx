import { AlertTriangle } from '@untitledui/icons'
import { Tooltip, TooltipTrigger } from '@/components/base/tooltip/tooltip'
import type { UserBrief } from '../../../shared/api/types'
import RoleBadges from '../../../shared/components/RoleBadges'
import SearchableSelect from '../../../shared/components/ui/SearchableSelect'
import type { Member } from '../../projects/types'
import { buildAssigneeOptions } from '../jobHelpers'

interface Props {
  value: UserBrief | null
  /** Người có vai trò phù hợp trong dự án (backend vẫn tự kiểm tra lại). */
  options: Member[]
  /** id = null → bỏ giao. Không truyền → không cho bỏ trống. */
  onChange: (userId: number | null) => void
  allowClear?: boolean
  disabled?: boolean
  disabledReason?: string
  placeholder?: string
  /** Người không được chọn (vd. luật bốn mắt) — vẫn hiện nhưng mờ. */
  blockedIds?: number[]
}

export const CVAT_UNLINKED_HINT =
  'Chưa liên kết CVAT — job vẫn giao được trên VanoHub, sẽ tự đồng bộ sang CVAT khi người này liên kết.'

/** Ô chọn người phụ trách ngay trong bảng job (Annotator / QC1 / QC2). Hỗ trợ tìm kiếm & hiện đủ vai trò. */
export default function AssigneeSelect({
  value,
  options,
  onChange,
  allowClear = true,
  disabled,
  disabledReason,
  placeholder = 'Chưa giao',
  blockedIds = [],
}: Props) {
  if (disabled) {
    const label = (
      <span className={value ? 'text-sm text-primary' : 'text-sm text-tertiary'}>
        {value?.full_name ?? placeholder}
      </span>
    )
    if (!disabledReason) return label
    return (
      <Tooltip title={disabledReason}>
        <TooltipTrigger className="cursor-default text-left">{label}</TooltipTrigger>
      </Tooltip>
    )
  }

  const { items, selectedUnlinked } = buildAssigneeOptions(options, value, blockedIds)

  return (
    <div className="inline-flex items-center gap-1.5" onClick={(event) => event.stopPropagation()}>
      <SearchableSelect
        size="sm"
        className="w-40"
        popoverClassName="w-80"
        ariaLabel={placeholder}
        placeholder={placeholder}
        searchPlaceholder="Tìm tên hoặc username…"
        allowClear={allowClear}
        clearLabel="Bỏ giao"
        items={items}
        selectedKey={value?.id ?? null}
        onSelectionChange={(key) => onChange(key == null ? null : Number(key))}
        renderOption={(item) => (
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate font-medium text-primary">{item.label}</div>
              <div className="truncate text-xs text-tertiary">{item.username}</div>
              {!item.cvatLinked && <div className="text-xs text-warning-primary">Chưa liên kết CVAT</div>}
            </div>
            {item.roles.length > 0 && <RoleBadges roles={item.roles} short />}
          </div>
        )}
      />
      {selectedUnlinked && (
        <Tooltip title={CVAT_UNLINKED_HINT}>
          <TooltipTrigger aria-label="Chưa liên kết CVAT" className="cursor-default text-fg-warning-primary">
            <AlertTriangle className="size-4" aria-hidden="true" />
          </TooltipTrigger>
        </Tooltip>
      )}
    </div>
  )
}
