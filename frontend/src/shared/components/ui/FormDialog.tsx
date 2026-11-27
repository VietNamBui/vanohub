import type { ReactNode } from 'react'
import { Button } from '@/components/base/buttons/button'
import { Dialog, Modal, ModalOverlay } from '@/components/application/modals/modal'

interface FormDialogProps {
  isOpen: boolean
  onClose: () => void
  title: string
  description?: ReactNode
  children?: ReactNode
  submitLabel?: string
  onSubmit: () => void
  pending?: boolean
  /** Nút xác nhận màu đỏ (xoá, bỏ khỏi team...). */
  destructive?: boolean
  maxWidthClass?: string
}

/** Hộp thoại có form + 2 nút Huỷ / Lưu, dựng trên Modal của Untitled UI. */
export default function FormDialog({
  isOpen, onClose, title, description, children, submitLabel = 'Lưu', onSubmit, pending, destructive, maxWidthClass = 'max-w-md',
}: FormDialogProps) {
  return (
    <ModalOverlay isOpen={isOpen} onOpenChange={(open) => !open && onClose()} isDismissable>
      <Modal className={maxWidthClass}>
        <Dialog aria-label={title}>
          <form
            className="flex w-full flex-col gap-5 p-6"
            onSubmit={(event) => {
              event.preventDefault()
              onSubmit()
            }}
          >
            <div>
              <h2 className="text-lg font-semibold text-primary">{title}</h2>
              {description && <p className="mt-1 text-sm text-tertiary">{description}</p>}
            </div>
            {children}
            <div className="flex justify-end gap-3 pt-1">
              <Button color="secondary" size="md" onPress={onClose}>Huỷ</Button>
              <Button type="submit" size="md" color={destructive ? 'primary-destructive' : 'primary'} isLoading={pending}>
                {submitLabel}
              </Button>
            </div>
          </form>
        </Dialog>
      </Modal>
    </ModalOverlay>
  )
}
