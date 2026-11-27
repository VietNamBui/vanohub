import { XClose } from '@untitledui/icons'
import type { ReactNode } from 'react'
import { Dialog as AriaDialog, Modal as AriaModal, ModalOverlay as AriaModalOverlay } from 'react-aria-components'
import { Button } from '@/components/base/buttons/button'
import { cx } from '@/utils/cx'

interface SlideoverProps {
  isOpen: boolean
  onClose: () => void
  title: ReactNode
  extra?: ReactNode
  footer?: ReactNode
  maxWidthClass?: string
  children: ReactNode
}

/** Ngăn kéo trượt bên phải dựng trên React Aria Modal/Dialog (hỗ trợ Escape, backdrop, focus trap). */
export default function Slideover({
  isOpen,
  onClose,
  title,
  extra,
  footer,
  maxWidthClass = 'max-w-[680px]',
  children,
}: SlideoverProps) {
  return (
    <AriaModalOverlay
      isOpen={isOpen}
      onOpenChange={(open) => !open && onClose()}
      isDismissable
      className={(state) =>
        cx(
          'fixed inset-0 z-50 flex justify-end bg-overlay/70 backdrop-blur-[2px] outline-hidden',
          state.isEntering && 'duration-200 ease-out animate-in fade-in',
          state.isExiting && 'duration-150 ease-in animate-out fade-out',
        )
      }
    >
      <AriaModal
        className={(state) =>
          cx(
            'flex h-dvh w-full flex-col border-l border-secondary bg-primary shadow-2xl outline-hidden',
            maxWidthClass,
            state.isEntering && 'duration-200 ease-out animate-in slide-in-from-right',
            state.isExiting && 'duration-150 ease-in animate-out slide-out-to-right',
          )
        }
      >
        <AriaDialog
          aria-label={typeof title === 'string' && title ? title : 'Chi tiết'}
          className="flex h-full flex-col outline-hidden"
        >
          <header className="flex flex-wrap items-center justify-between gap-3 border-b border-secondary px-6 py-4">
            <div className="flex min-w-0 flex-wrap items-center gap-2.5">
              <h2 className="truncate text-lg font-semibold text-primary">{title}</h2>
              {extra}
            </div>
            <Button color="tertiary" size="sm" iconLeading={XClose} aria-label="Đóng" onPress={onClose} />
          </header>

          <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>

          {footer != null && (
            <footer className="border-t border-secondary bg-primary px-6 py-4">{footer}</footer>
          )}
        </AriaDialog>
      </AriaModal>
    </AriaModalOverlay>
  )
}
