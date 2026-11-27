import { useState } from 'react'
import { Input } from '@/components/base/input/input'
import { getErrorMessage } from '../../shared/api/errors'
import FormDialog from '../../shared/components/ui/FormDialog'
import { changePassword } from './api'

/** Người dùng tự đổi mật khẩu. Đổi xong, PM không còn xem được mật khẩu tạm trong bảng thành viên. */
export default function ChangePasswordDialog({ onClose }: { onClose: () => void }) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  async function submit() {
    if (done) return onClose()
    if (!current || !next) return setError('Nhập đủ mật khẩu hiện tại và mật khẩu mới.')
    if (next !== confirm) return setError('Mật khẩu nhập lại không khớp.')
    setPending(true)
    setError(null)
    try {
      await changePassword(current, next)
      setDone(true)
    } catch (e) {
      setError(getErrorMessage(e))
    } finally {
      setPending(false)
    }
  }

  return (
    <FormDialog
      isOpen
      title="Đổi mật khẩu"
      description={done ? undefined : 'Nên đổi mật khẩu tạm do PM cấp ngay lần đăng nhập đầu tiên.'}
      submitLabel={done ? 'Đóng' : 'Đổi mật khẩu'}
      onClose={onClose}
      onSubmit={submit}
      pending={pending}
    >
      {done ? (
        <p role="status" className="text-sm text-secondary">Đã đổi mật khẩu. Lần đăng nhập sau dùng mật khẩu mới.</p>
      ) : (
        <>
          <Input label="Mật khẩu hiện tại" type="password" autoComplete="current-password" isRequired value={current} onChange={setCurrent} autoFocus />
          <Input label="Mật khẩu mới" type="password" autoComplete="new-password" isRequired value={next} onChange={setNext}
            hint="Ít nhất 8 ký tự, không toàn số, không quá giống tên tài khoản." />
          <Input label="Nhập lại mật khẩu mới" type="password" autoComplete="new-password" isRequired value={confirm} onChange={setConfirm} />
          {error && <p role="alert" className="text-sm text-error-primary">{error}</p>}
        </>
      )}
    </FormDialog>
  )
}
