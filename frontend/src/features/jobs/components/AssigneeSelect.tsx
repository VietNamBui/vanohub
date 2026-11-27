import { WarningFilled } from '@ant-design/icons'
import { Select, Tooltip, Typography } from 'antd'
import type { UserBrief } from '../../../shared/api/types'
import RoleBadges from '../../../shared/components/RoleBadges'
import type { Member } from '../../projects/types'

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

export const CVAT_UNLINKED_HINT = 'Chưa liên kết CVAT — job vẫn giao được trên VanoHub, sẽ tự đồng bộ sang CVAT khi người này liên kết.'

/** Ô chọn người phụ trách ngay trong bảng job (Annotator / QC1 / QC2). Người chưa liên kết CVAT có cảnh báo. */
export default function AssigneeSelect({
  value, options, onChange, allowClear = true, disabled, disabledReason, placeholder = 'Chưa giao', blockedIds = [],
}: Props) {
  if (disabled) {
    return (
      <Tooltip title={disabledReason}>
        <Typography.Text type={value ? undefined : 'secondary'}>{value?.full_name ?? placeholder}</Typography.Text>
      </Tooltip>
    )
  }
  // Người đang được giao nhưng không còn trong danh sách (vd. đã mất vai trò) vẫn phải hiện đúng tên.
  const items = options.map((m) => ({
    value: m.user.id,
    label: m.user.full_name,
    username: m.user.username,
    roles: m.roles,
    cvatLinked: m.cvat_linked,
    disabled: blockedIds.includes(m.user.id),
  }))
  if (value && !items.some((i) => i.value === value.id)) {
    items.unshift({ value: value.id, label: value.full_name, username: value.username, roles: [], cvatLinked: true, disabled: true })
  }
  const selectedUnlinked = value != null && items.find((i) => i.value === value.id)?.cvatLinked === false

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 2 }}>
    <Select
      size="small"
      variant="borderless"
      style={{ width: 150, marginInline: -7 }}
      popupMatchSelectWidth={300}
      placeholder={placeholder}
      allowClear={allowClear}
      // Tìm theo cả tên hiển thị lẫn username.
      showSearch={{ filterOption: (input, option) => `${option?.label} ${option?.username}`.toLowerCase().includes(input.toLowerCase()) }}
      // Mỗi lựa chọn hiện tên + username + toàn bộ vai trò → thấy rõ vì sao người đó có trong danh sách.
      optionRender={(option) => (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <span style={{ minWidth: 0 }}>
            <div>{option.data.label}</div>
            <div style={{ fontSize: 12, opacity: 0.6 }}>{option.data.username}</div>
            {!option.data.cvatLinked && <div style={{ fontSize: 12, color: '#b54708' }}>Chưa liên kết CVAT</div>}
          </span>
          <RoleBadges roles={option.data.roles} short />
        </div>
      )}
      value={value?.id}
      options={items}
      onChange={(id?: number) => onChange(id ?? null)}
      onClick={(event) => event.stopPropagation()}
    />
    {selectedUnlinked && (
      <Tooltip title={CVAT_UNLINKED_HINT}>
        <WarningFilled aria-label="Chưa liên kết CVAT" style={{ color: '#dc6803' }} />
      </Tooltip>
    )}
    </span>
  )
}
