import { Form, Input, Modal } from 'antd'
import MemberSelect from '../../projects/components/MemberSelect'

export interface AssignValues {
  annotator?: number | null
  qc1_reviewer?: number | null
  note?: string
}

interface Props {
  open: boolean
  projectId: number
  title?: string
  initial?: AssignValues
  confirmLoading?: boolean
  onCancel: () => void
  onSubmit: (values: AssignValues) => void
}

/**
 * Giao lại annotator / người QC1. Chỉ field nào được đổi mới gửi lên backend
 * (để giao nhiều job cùng lúc mà không ghi đè field còn lại).
 */
export default function AssignModal({ open, projectId, title, initial, confirmLoading, onCancel, onSubmit }: Props) {
  const [form] = Form.useForm<AssignValues>()

  function handleOk() {
    const touched = form.isFieldsTouched(['annotator']) || form.isFieldsTouched(['qc1_reviewer'])
    if (!touched) {
      onCancel()
      return
    }
    const values = form.getFieldsValue()
    const payload: AssignValues = { note: values.note ?? '' }
    if (form.isFieldTouched('annotator')) payload.annotator = values.annotator ?? null
    if (form.isFieldTouched('qc1_reviewer')) payload.qc1_reviewer = values.qc1_reviewer ?? null
    onSubmit(payload)
  }

  return (
    <Modal
      open={open}
      title={title ?? 'Giao lại job'}
      okText="Lưu"
      onOk={handleOk}
      onCancel={onCancel}
      confirmLoading={confirmLoading}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" initialValues={initial} preserve={false}>
        <Form.Item name="annotator" label="Annotator" extra="Chỉ hiện người có vai trò Annotator. Số job là số job đang giữ.">
          <MemberSelect projectId={projectId} role="annotator" />
        </Form.Item>
        <Form.Item name="qc1_reviewer" label="Người QC1" extra="Luật bốn mắt: không được trùng annotator.">
          <MemberSelect projectId={projectId} role="qc1" />
        </Form.Item>
        <Form.Item name="note" label="Ghi chú">
          <Input.TextArea rows={2} placeholder="Lý do giao lại (lưu vào lịch sử)" />
        </Form.Item>
      </Form>
    </Modal>
  )
}
