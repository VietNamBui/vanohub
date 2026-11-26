import { Alert, Button, Card, Form, Input, Modal, Progress, Space, Table, Tag } from 'antd'
import { useState } from 'react'
import UserName from '../../../shared/components/UserName'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import { createDelivery, listDeliveries, listDeliveryCandidates, updateDelivery } from '../api'
import { useProject } from '../projectContext'
import type { Delivery, DeliveryCandidate } from '../types'

/** PM-14 Delivery. Điều kiện (đề xuất, L4 bỏ qua): mọi job của batch Đã duyệt và không còn audit mở. */
export default function DeliveryPage() {
  const { projectId } = useProject()
  const [version, setVersion] = useState(0)
  const [delivering, setDelivering] = useState<DeliveryCandidate | null>(null)
  const [feedbackFor, setFeedbackFor] = useState<Delivery | null>(null)
  const [form] = Form.useForm()
  const { run, pending } = useAction()
  const candidates = useRequest(`delivery-candidates:${projectId}:${version}`, () => listDeliveryCandidates(projectId))
  const history = useRequest(`deliveries:${projectId}:${version}`, () => listDeliveries(projectId))
  const reload = () => setVersion((v) => v + 1)

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Delivery</h1>
          <p>Bàn giao batch cho khách hàng khi đủ điều kiện.</p>
        </div>
      </div>
      <Alert type="info" showIcon style={{ marginBottom: 16 }}
        title="Quy tắc tạm: chỉ bàn giao khi mọi job trong batch đã ở trạng thái Đã duyệt và batch không còn audit QC2 đang mở. Bước PM Accept / Reject batch (L4) đang bỏ qua." />
      <Card title="Batch chờ bàn giao" style={{ marginBottom: 16 }}>
        <Table<DeliveryCandidate>
          rowKey="batch"
          loading={candidates.isLoading}
          dataSource={candidates.data ?? []}
          pagination={false}
          locale={{ emptyText: 'Không có batch nào đang chờ' }}
          columns={[
            { title: 'Batch', render: (_, c) => `${c.dataset_name} / ${c.batch_name}` },
            { title: 'Đã duyệt', width: 220, render: (_, c) => <Progress size="small" percent={c.job_count ? Math.round((c.approved_count * 100) / c.job_count) : 0} format={() => `${c.approved_count}/${c.job_count}`} /> },
            { title: 'Audit đang mở', dataIndex: 'open_audits', align: 'right' },
            { title: 'Điều kiện', render: (_, c) => (c.ready ? <Tag color="success">Đủ điều kiện</Tag> : <Tag>Chưa đủ</Tag>) },
            { title: '', render: (_, c) => <Button type="primary" size="small" disabled={!c.ready} onClick={() => { form.resetFields(); setDelivering(c) }}>Tạo delivery</Button> },
          ]}
        />
      </Card>
      <Card title="Lịch sử bàn giao">
        <Table<Delivery>
          rowKey="id"
          loading={history.isLoading}
          dataSource={history.data ?? []}
          locale={{ emptyText: 'Chưa bàn giao lần nào' }}
          columns={[
            { title: 'Batch', render: (_, d) => `${d.dataset_name} / ${d.batch_name}` },
            { title: 'Người nhận', dataIndex: 'recipient' },
            { title: 'Đầu ra', dataIndex: 'output_path', ellipsis: true },
            { title: 'Số job', dataIndex: 'job_count', align: 'right' },
            { title: 'Người bàn giao', render: (_, d) => <UserName user={d.delivered_by} /> },
            { title: 'Thời gian', dataIndex: 'delivered_at', render: formatDateTime },
            { title: 'Ghi chú', dataIndex: 'note', ellipsis: true },
            { title: 'Phản hồi khách hàng', dataIndex: 'client_feedback', ellipsis: true },
            { title: '', render: (_, d) => <Button size="small" onClick={() => { form.setFieldsValue(d); setFeedbackFor(d) }}>Ghi phản hồi</Button> },
          ]}
        />
      </Card>

      <Modal open={delivering !== null} title={`Bàn giao ${delivering?.batch_name}`} okText="Bàn giao" confirmLoading={pending}
        onCancel={() => setDelivering(null)} onOk={() => form.submit()} destroyOnHidden>
        <Form form={form} layout="vertical" preserve={false} onFinish={async (v: { recipient: string; output_path: string; note?: string }) => {
          if (delivering && (await run(() => createDelivery(projectId, { batch: delivering.batch, recipient: v.recipient, output_path: v.output_path, note: v.note }), 'Đã bàn giao'))) {
            setDelivering(null)
            reload()
          }
        }}>
          <Space orientation="vertical" style={{ width: '100%' }}>
            <span>{delivering?.job_count} job sẽ chuyển sang trạng thái Đã bàn giao và batch bị khoá.</span>
            <Form.Item name="recipient" label="Người nhận" rules={[{ required: true, message: 'Vui lòng nhập người nhận bàn giao.' }]}><Input placeholder="Tên khách hàng / người nhận" /></Form.Item>
            <Form.Item name="output_path" label="Đường dẫn đầu ra" rules={[{ required: true, message: 'Vui lòng nhập đường dẫn đầu ra.' }]}><Input placeholder="VD: s3://bucket/path hoặc link bàn giao" /></Form.Item>
            <Form.Item name="note" label="Ghi chú"><Input.TextArea rows={3} /></Form.Item>
          </Space>
        </Form>
      </Modal>
      <Modal open={feedbackFor !== null} title="Phản hồi khách hàng" okText="Lưu" confirmLoading={pending}
        onCancel={() => setFeedbackFor(null)} onOk={() => form.submit()} destroyOnHidden>
        <Form form={form} layout="vertical" preserve={false} onFinish={async (v) => {
          if (feedbackFor && (await run(() => updateDelivery(projectId, feedbackFor.id, v), 'Đã lưu'))) {
            setFeedbackFor(null)
            reload()
          }
        }}>
          <Form.Item name="client_feedback" label="Phản hồi"><Input.TextArea rows={4} /></Form.Item>
          <Form.Item name="note" label="Ghi chú"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
