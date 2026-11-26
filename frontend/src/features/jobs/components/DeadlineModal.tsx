import { DatePicker, Form, Input, Modal } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'

interface Props {
  open: boolean
  title?: string
  initial?: string | null
  confirmLoading?: boolean
  onCancel: () => void
  onSubmit: (deadline: string | null, note: string) => void
}

export default function DeadlineModal({ open, title, initial, confirmLoading, onCancel, onSubmit }: Props) {
  const [form] = Form.useForm<{ deadline: Dayjs | null; note: string }>()

  return (
    <Modal
      open={open}
      title={title ?? 'Đặt deadline'}
      okText="Lưu"
      onOk={() => form.submit()}
      onCancel={onCancel}
      confirmLoading={confirmLoading}
      destroyOnHidden
    >
      <Form
        key={initial ?? ''}
        form={form}
        layout="vertical"
        preserve={false}
        initialValues={{ deadline: initial && dayjs(initial).isValid() ? dayjs(initial) : null, note: '' }}
        onFinish={(v) => onSubmit(v.deadline?.isValid() ? v.deadline.toISOString() : null, v.note ?? '')}
      >
        <Form.Item
          name="deadline"
          label="Deadline"
          extra="Giờ Việt Nam (UTC+7). Để trống để bỏ deadline."
          rules={[
            {
              validator: (_, value) =>
                value == null || (dayjs.isDayjs(value) && value.isValid())
                  ? Promise.resolve()
                  : Promise.reject(new Error('Thời gian deadline không hợp lệ.')),
            },
          ]}
        >
          <DatePicker showTime={{ format: 'HH:mm' }} format="DD/MM/YYYY HH:mm" style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="note" label="Ghi chú">
          <Input.TextArea rows={2} placeholder="Lý do đổi deadline (lưu vào lịch sử)" />
        </Form.Item>
      </Form>
    </Modal>
  )
}
