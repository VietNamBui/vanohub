import { Eye, RefreshCw01 } from '@untitledui/icons'
import { useState } from 'react'
import { getErrorMessage } from '../../../shared/api/errors'
import FormDialog from '../../../shared/components/ui/FormDialog'
import { getMemberCredential, resetMemberPassword } from '../../projects/api'
import type { Member, MemberCredential } from '../../projects/types'
import PasswordText, { IconButton } from './PasswordText'

const MASK = '••••••••'

/**
 * Ô "Mật khẩu" trong bảng thành viên. Mặc định ẩn; bấm con mắt mới gọi API lấy mật khẩu tạm
 * (mỗi lần xem được ghi lịch sử). Người dùng đã tự đổi mật khẩu → không xem được, chỉ "Cấp lại".
 */
export default function MemberPasswordCell({ projectId, member, canReset }: { projectId: number; member: Member; canReset: boolean }) {
  const [credential, setCredential] = useState<MemberCredential | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmReset, setConfirmReset] = useState(false)

  async function reveal() {
    setLoading(true)
    setError(null)
    try {
      setCredential(await getMemberCredential(projectId, member.user.id))
    } catch (e) {
      setError(getErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  async function reset() {
    setLoading(true)
    setError(null)
    try {
      setCredential(await resetMemberPassword(projectId, member.user.id))
      setConfirmReset(false)
    } catch (e) {
      setError(getErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  const status = credential?.status ?? (member.has_initial_password ? 'initial' : 'changed')
  const resetButton = canReset && (
    <IconButton label="Cấp lại mật khẩu" onClick={() => setConfirmReset(true)} disabled={loading}>
      <RefreshCw01 className="size-4" />
    </IconButton>
  )

  let content
  if (credential?.password) {
    content = <PasswordText password={credential.password} defaultVisible />
  } else if (status === 'initial') {
    content = (
      <span className="inline-flex items-center gap-1">
        <span className="min-w-[6.5rem] font-mono text-sm tracking-widest text-tertiary">{MASK}</span>
        <IconButton label="Hiện mật khẩu" onClick={reveal} disabled={loading}><Eye className="size-4" /></IconButton>
      </span>
    )
  } else {
    content = (
      <span className="text-xs text-quaternary" title={status === 'unreadable' ? 'Không đọc được mật khẩu tạm — hãy cấp lại.' : undefined}>
        {status === 'unreadable' ? 'Không đọc được' : 'Người dùng đã đổi'}
      </span>
    )
  }

  return (
    <div onClick={(e) => e.stopPropagation()}>
      <div className="flex items-center gap-1">
        {content}
        {resetButton}
      </div>
      {error && <p className="text-xs text-error-primary">{error}</p>}
      {confirmReset && (
        <FormDialog
          isOpen
          title="Cấp lại mật khẩu?"
          description={<>Mật khẩu hiện tại của <b>{member.user.full_name}</b> sẽ không dùng được nữa. Hệ thống tạo mật khẩu tạm mới để bạn gửi cho họ.</>}
          submitLabel="Cấp lại"
          onClose={() => setConfirmReset(false)}
          onSubmit={reset}
          pending={loading}
        >
          {error && <p className="text-sm text-error-primary">{error}</p>}
        </FormDialog>
      )}
    </div>
  )
}
