import { Modal } from 'antd'
import type { ReactNode } from 'react'

export interface ConfirmDangerProps {
  open: boolean
  title: string
  /** Mô tả hậu quả (vd release xoá annotation). */
  children?: ReactNode
  okText?: string
  onOk: () => void
  onCancel: () => void
}

/** Modal xác nhận thao tác nguy hiểm (nút chính màu đỏ). Page tự try/catch trong onOk. */
export function ConfirmDanger({ open, title, children, okText = 'Xác nhận', onOk, onCancel }: ConfirmDangerProps) {
  return (
    <Modal
      className="cvd-modal" open={open} title={title} okText={okText} cancelText="Huỷ" okButtonProps={{ danger: true }}
      onOk={onOk} onCancel={onCancel} destroyOnClose
    >
      {children}
    </Modal>
  )
}
