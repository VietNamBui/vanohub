import { AlertCircle, Inbox01, Lock01 } from '@untitledui/icons'
import { Button } from '@/components/base/buttons/button'

/** Bốn trạng thái màn hình dùng chung theo wireframe CMN-04 (Tailwind + Untitled UI). */
type Kind = 'loading' | 'empty' | 'error' | 'forbidden'

interface Props {
  kind: Kind
  title?: string
  description?: string
  action?: { label: string; onClick: () => void }
}

export default function StateView({ kind, title, description, action }: Props) {
  if (kind === 'loading') {
    return (
      <div className="flex items-center justify-center gap-3 py-16 text-sm text-tertiary" role="status">
        <span className="size-5 animate-spin rounded-full border-2 border-secondary border-t-fg-brand-primary" />
        <span>{title ?? 'Đang tải…'}</span>
      </div>
    )
  }

  const defaultTitle =
    kind === 'empty'
      ? 'Chưa có dữ liệu'
      : kind === 'forbidden'
        ? 'Bạn không có quyền xem trang này'
        : 'Không tải được dữ liệu'

  const Icon = kind === 'empty' ? Inbox01 : kind === 'forbidden' ? Lock01 : AlertCircle
  const iconTone =
    kind === 'empty'
      ? 'bg-secondary text-fg-quaternary'
      : kind === 'forbidden'
        ? 'bg-warning-primary text-fg-warning-primary'
        : 'bg-error-primary text-fg-error-primary'

  return (
    <div className="flex flex-col items-center gap-3 px-4 py-14 text-center" role={kind === 'error' ? 'alert' : undefined}>
      <div className={`flex size-11 items-center justify-center rounded-full ${iconTone}`}>
        <Icon className="size-5" aria-hidden="true" />
      </div>
      <div className="flex flex-col gap-1">
        <p className="text-base font-semibold text-primary">{title ?? defaultTitle}</p>
        {description && <p className="max-w-md text-sm text-tertiary">{description}</p>}
      </div>
      {action && (
        <Button color={kind === 'empty' ? 'primary' : 'secondary'} size="sm" className="mt-1" onPress={action.onClick}>
          {action.label}
        </Button>
      )}
    </div>
  )
}
