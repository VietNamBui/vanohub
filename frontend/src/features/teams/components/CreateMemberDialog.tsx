import { useState } from 'react'
import { Dialog, Modal, ModalOverlay } from '@/components/application/modals/modal'
import { Button } from '@/components/base/buttons/button'
import { Checkbox } from '@/components/base/checkbox/checkbox'
import { Input } from '@/components/base/input/input'
import { Select } from '@/components/base/select/select'
import { getErrorMessage } from '../../../shared/api/errors'
import { GRANTABLE_ROLES, ROLE_LABELS, type Role } from '../../../shared/types/roles'
import { createMember } from '../../projects/api'
import type { CreatedMember } from '../../projects/types'
import type { Team } from '../types'
import PasswordText from './PasswordText'

const NO_TEAM = 0

/**
 * PM thêm thành viên mới: hệ thống tạo tài khoản + mật khẩu tạm.
 * Tài khoản để trống → tự sinh từ họ tên (bỏ dấu). Sau khi tạo hiện ngay tài khoản / mật khẩu để PM gửi cho người dùng;
 * mật khẩu vẫn xem lại được ở bảng Thành viên cho đến khi người dùng tự đổi.
 */
export default function CreateMemberDialog({ projectId, teams, onClose, onDone }: {
  projectId: number
  teams: Team[]
  onClose: () => void
  onDone: () => void
}) {
  const [fullName, setFullName] = useState('')
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [roles, setRoles] = useState<Role[]>(['annotator'])
  const [team, setTeam] = useState<number>(NO_TEAM)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [created, setCreated] = useState<CreatedMember | null>(null)

  const toggleRole = (role: Role, on: boolean) => setRoles((rs) => (on ? [...rs, role] : rs.filter((r) => r !== role)))

  async function submit() {
    if (!fullName.trim()) return setError('Nhập họ tên.')
    if (!roles.length) return setError('Chọn ít nhất một vai trò.')
    setPending(true)
    setError(null)
    try {
      setCreated(await createMember(projectId, {
        full_name: fullName.trim(),
        username: username.trim() || undefined,
        email: email.trim() || undefined,
        roles,
        team: team === NO_TEAM ? null : team,
      }))
    } catch (e) {
      setError(getErrorMessage(e))
    } finally {
      setPending(false)
    }
  }

  // Đóng sau khi đã tạo → tải lại bảng thành viên.
  const close = created ? onDone : onClose

  return (
    <ModalOverlay isOpen onOpenChange={(open) => !open && close()} isDismissable={!created}>
      <Modal className="max-w-md">
        <Dialog aria-label="Thêm thành viên">
          {created ? (
            <div className="flex w-full flex-col gap-5 p-6">
              <div>
                <h2 className="text-lg font-semibold text-primary">Đã tạo tài khoản</h2>
                <p className="mt-1 text-sm text-tertiary">
                  Gửi thông tin đăng nhập cho <span className="font-medium text-secondary">{created.user.full_name}</span>.
                  Mật khẩu tạm vẫn xem lại được ở bảng Thành viên cho đến khi người dùng tự đổi.
                </p>
              </div>
              <dl className="flex flex-col gap-3 rounded-xl bg-secondary p-4 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-tertiary">Tài khoản</dt>
                  <dd className="font-mono font-medium text-primary">{created.username}</dd>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-tertiary">Mật khẩu</dt>
                  <dd><PasswordText password={created.password} /></dd>
                </div>
              </dl>
              <div className="flex justify-end">
                <Button size="md" onPress={onDone}>Xong</Button>
              </div>
            </div>
          ) : (
            <form className="flex w-full flex-col gap-5 p-6" onSubmit={(e) => { e.preventDefault(); submit() }}>
              <div>
                <h2 className="text-lg font-semibold text-primary">Thêm thành viên</h2>
                <p className="mt-1 text-sm text-tertiary">Hệ thống tạo tài khoản và mật khẩu tạm cho người này.</p>
              </div>
              <Input label="Họ tên" isRequired placeholder="Nguyễn Văn An" value={fullName} onChange={setFullName} autoFocus />
              <Input label="Tài khoản" placeholder="Để trống để tự tạo từ họ tên" hint="Chữ không dấu, số và . _ -"
                value={username} onChange={setUsername} />
              <Input label="Email" type="email" placeholder="Không bắt buộc" value={email} onChange={setEmail} />
              <fieldset>
                <legend className="mb-2 text-sm font-medium text-secondary">Vai trò <span className="text-brand-tertiary">*</span></legend>
                <div className="grid grid-cols-2 gap-2.5">
                  {GRANTABLE_ROLES.map((role) => (
                    <Checkbox key={role} label={ROLE_LABELS[role]} isSelected={roles.includes(role)} onChange={(on) => toggleRole(role, on)} />
                  ))}
                </div>
              </fieldset>
              <Select label="Team" placeholder="Chưa xếp team"
                items={[{ id: NO_TEAM, label: 'Chưa xếp team' }, ...teams.map((t) => ({ id: t.id, label: t.name }))]}
                selectedKey={team} onSelectionChange={(key) => setTeam(Number(key))}>
                {(item) => <Select.Item id={item.id} label={item.label} />}
              </Select>
              {error && <p role="alert" className="text-sm text-error-primary">{error}</p>}
              <div className="flex justify-end gap-3 pt-1">
                <Button color="secondary" size="md" onPress={onClose}>Huỷ</Button>
                <Button type="submit" size="md" isLoading={pending}>Tạo tài khoản</Button>
              </div>
            </form>
          )}
        </Dialog>
      </Modal>
    </ModalOverlay>
  )
}
