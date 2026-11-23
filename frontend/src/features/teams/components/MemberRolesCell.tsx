import { Plus } from '@untitledui/icons'
import { useState } from 'react'
import { Button as AriaButton, Dialog as AriaDialog, DialogTrigger, Popover } from 'react-aria-components'
import RoleBadges from '../../../shared/components/RoleBadges'
import { useAction } from '../../../shared/hooks/useAction'
import { GRANTABLE_ROLES, ROLE_LABELS, type Role } from '../../../shared/types/roles'
import { addMemberRole } from '../../projects/api'
import { cx } from '@/utils/cx'

interface Props {
  projectId: number
  userId: number
  userName: string
  roles: Role[]
  /** Gọi với danh sách vai trò mới (backend trả về) sau khi gán thành công. */
  onChange: (roles: Role[]) => void
}

/**
 * Ô "Vai trò": các badge + nút "+" mở popup nhỏ.
 * Bấm một vai trò trong popup → gán cho người này; vai trò đó hiện vào hàng và biến khỏi popup.
 */
export default function MemberRolesCell({ projectId, userId, userName, roles, onChange }: Props) {
  const { run } = useAction()
  const [adding, setAdding] = useState<Role | null>(null)
  const available = GRANTABLE_ROLES.filter((role) => !roles.includes(role))

  async function add(role: Role) {
    setAdding(role)
    const result = await run(() => addMemberRole(projectId, userId, role), `Đã gán ${ROLE_LABELS[role]}`)
    setAdding(null)
    if (result) onChange(result.roles)
  }

  return (
    <div className="flex flex-wrap items-center gap-1">
      <RoleBadges roles={roles} short />
      {available.length > 0 && (
        <DialogTrigger>
          <AriaButton
            aria-label={`Thêm vai trò cho ${userName}`}
            className={({ isHovered, isFocusVisible }) => cx(
              'flex size-6 cursor-pointer items-center justify-center rounded-md text-fg-quaternary ring-1 ring-secondary ring-inset outline-focus-ring transition duration-100',
              isHovered && 'bg-primary_hover text-fg-quaternary_hover',
              isFocusVisible && 'outline-2 outline-offset-2',
            )}
          >
            <Plus className="size-4" />
          </AriaButton>
          <Popover
            placement="bottom start"
            offset={6}
            className={({ isEntering, isExiting }) => cx(
              'w-52 rounded-lg bg-primary p-1.5 shadow-lg ring-1 ring-secondary_alt',
              isEntering && 'duration-150 ease-out animate-in fade-in',
              isExiting && 'duration-100 ease-in animate-out fade-out',
            )}
          >
            <AriaDialog aria-label="Thêm vai trò" className="outline-hidden">
              <p className="px-2 pt-1 pb-1.5 text-xs font-semibold text-tertiary">Thêm vai trò</p>
              {available.map((role) => (
                  <AriaButton
                    key={role}
                    isDisabled={adding !== null}
                    onPress={() => add(role)}
                    className={({ isHovered, isDisabled }) => cx(
                      'flex w-full cursor-pointer items-center justify-between rounded-md px-2 py-1.5 text-left text-sm font-medium text-secondary outline-focus-ring',
                      isHovered && 'bg-primary_hover',
                      isDisabled && 'cursor-wait opacity-60',
                    )}
                  >
                    {ROLE_LABELS[role]}
                    {adding === role && <span className="text-xs text-quaternary">Đang gán…</span>}
                  </AriaButton>
              ))}
            </AriaDialog>
          </Popover>
        </DialogTrigger>
      )}
    </div>
  )
}
