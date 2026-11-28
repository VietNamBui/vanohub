import { Form, Input, Modal, Radio, Select } from 'antd'
import { useEffect } from 'react'

export type ReworkTarget = 'qc1' | 'annotator'

export interface ReworkResult {
  reason: string
  errorCategory: string
  /** Chỉ có khi `showReturnTarget` bật (QC2). */
  target?: ReworkTarget
}

export interface ReworkDialogProps {
  open: boolean
  onCancel: () => void
  /** Gọi khi đã hợp lệ (lý do không rỗng, đã chọn loại lỗi). */
  onSubmit: (result: ReworkResult) => void
  /** Danh mục lỗi của loại dữ liệu của dự án (DataType.errorCategories). */
  errorCategories: string[]
  /** Bật lựa chọn 'Trả về QC1' / 'Trả thẳng annotator' (dùng cho QC2). */
  showReturnTarget?: boolean
  title?: string
}

interface FormValues { reason: string; errorCategory: string; target?: ReworkTarget }

export function ReworkDialog({ open, onCancel, onSubmit, errorCategories, showReturnTarget = false, title = 'Trả về làm lại' }: ReworkDialogProps) {
  const [form] = Form.useForm<FormValues>()
  useEffect(() => { if (open) form.resetFields() }, [open, form])
  return (
    <Modal
      className="cvd-modal" open={open} title={title} okText="Trả về" cancelText="Huỷ" onCancel={onCancel} okButtonProps={{ danger: true }}
      onOk={() => form.validateFields().then((v) => onSubmit({ reason: v.reason.trim(), errorCategory: v.errorCategory, target: showReturnTarget ? v.target : undefined }))}
    >
      <Form<FormValues> form={form} layout="vertical" initialValues={{ target: 'qc1' }}>
        {showReturnTarget && (
          <Form.Item name="target" label="Trả về cho">
            <Radio.Group>
              <Radio value="qc1">Trả về QC1</Radio>
              <Radio value="annotator">Trả thẳng annotator</Radio>
            </Radio.Group>
          </Form.Item>
        )}
        <Form.Item name="errorCategory" label="Loại lỗi" rules={[{ required: true, message: 'Chọn loại lỗi' }]}>
          <Select placeholder="Chọn loại lỗi" options={errorCategories.map((c) => ({ value: c, label: c }))} />
        </Form.Item>
        <Form.Item
          name="reason" label="Lý do" rules={[{ required: true, whitespace: true, message: 'Bắt buộc nhập lý do' }]}
        >
          <Input.TextArea rows={4} placeholder="Mô tả lỗi cần sửa" />
        </Form.Item>
      </Form>
    </Modal>
  )
}
