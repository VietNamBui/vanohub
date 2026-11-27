import { Check, Copy01, Eye, EyeOff } from '@untitledui/icons'
import { useState } from 'react'
import { cx } from '@/utils/cx'

const MASK = '••••••••'

/** Mật khẩu mặc định ẩn; bấm con mắt để hiện, có nút copy. */
export default function PasswordText({ password, defaultVisible = false }: { password: string; defaultVisible?: boolean }) {
  const [visible, setVisible] = useState(defaultVisible)
  const [copied, setCopied] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(password)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // Trình duyệt chặn clipboard (vd. không phải HTTPS) → người dùng tự bôi đen để copy.
      setVisible(true)
    }
  }

  return (
    <span className="inline-flex items-center gap-1">
      <span className={cx('min-w-[6.5rem] font-mono text-sm', visible ? 'text-primary' : 'tracking-widest text-tertiary')}>
        {visible ? password : MASK}
      </span>
      <IconButton label={visible ? 'Ẩn mật khẩu' : 'Hiện mật khẩu'} onClick={() => setVisible((v) => !v)}>
        {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </IconButton>
      <IconButton label={copied ? 'Đã copy' : 'Copy mật khẩu'} onClick={copy}>
        {copied ? <Check className="size-4 text-fg-success-primary" /> : <Copy01 className="size-4" />}
      </IconButton>
    </span>
  )
}

export function IconButton({ label, onClick, children, disabled }: {
  label: string
  onClick: () => void
  children: React.ReactNode
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={(event) => {
        event.stopPropagation()
        onClick()
      }}
      className="rounded-md p-1 text-fg-quaternary outline-focus-ring hover:bg-primary_hover hover:text-fg-quaternary_hover focus-visible:outline-2 disabled:cursor-wait disabled:opacity-50"
    >
      {children}
    </button>
  )
}
