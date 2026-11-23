import { AlertCircle } from '@untitledui/icons'
import { Button } from '@/components/base/buttons/button'

/** Trạng thái cả trang: đang tải / lỗi (kèm nút thử lại) / trống. */
export default function PageState({ kind, title, description, onRetry }: {
  kind: 'loading' | 'error' | 'empty'
  title?: string
  description?: string
  onRetry?: () => void
}) {
  if (kind === 'loading') {
    return (
      <div className="flex items-center justify-center gap-3 py-16 text-sm text-tertiary" role="status">
        <span className="size-5 animate-spin rounded-full border-2 border-secondary border-t-fg-brand-primary" />
        Đang tải…
      </div>
    )
  }
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-14 text-center">
      {kind === 'error' && <AlertCircle className="size-6 text-fg-error-primary" />}
      <p className="text-sm font-semibold text-secondary">{title ?? (kind === 'error' ? 'Không tải được dữ liệu' : 'Chưa có dữ liệu')}</p>
      {description && <p className="max-w-md text-sm text-tertiary">{description}</p>}
      {onRetry && <Button color="secondary" size="sm" className="mt-2" onPress={onRetry}>Thử lại</Button>}
    </div>
  )
}
