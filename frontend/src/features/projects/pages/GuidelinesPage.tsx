import { Button, Card, Col, Form, Input, List, Modal, Row, Tag, Typography } from 'antd'
import { useState } from 'react'
import { getErrorMessage } from '../../../shared/api/errors'
import StateView from '../../../shared/components/StateView'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import { listGuidelines, publishGuideline } from '../api'
import { useProject } from '../projectContext'

/** PM-18 Hướng dẫn gán nhãn có phiên bản. Mọi vai trò đọc được; PM xuất bản phiên bản mới. */
export default function GuidelinesPage() {
  const { projectId, can } = useProject()
  const [version, setVersion] = useState(0)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [editing, setEditing] = useState(false)
  const [form] = Form.useForm<{ title: string; content: string }>()
  const { run, pending } = useAction()
  const { data, error, isLoading, retry } = useRequest(`guidelines:${projectId}:${version}`, () => listGuidelines(projectId))

  if (isLoading) return <StateView kind="loading" />
  if (error != null) return <StateView kind="error" description={getErrorMessage(error)} action={{ label: 'Thử lại', onClick: retry }} />

  const current = data?.find((g) => g.id === selectedId) ?? data?.[0]

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Hướng dẫn gán nhãn</h1>
          <p>Mỗi lần lưu tạo một phiên bản mới; phiên bản cũ được giữ lại.</p>
        </div>
        {can('manage_quality_catalog') && (
          <Button type="primary" onClick={() => { form.setFieldsValue({ title: current?.title ?? '', content: current?.content ?? '' }); setEditing(true) }}>
            {current ? 'Soạn phiên bản mới' : 'Tạo hướng dẫn'}
          </Button>
        )}
      </div>
      {!current ? (
        <StateView kind="empty" title="Chưa có hướng dẫn" />
      ) : (
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={6}>
            <Card title="Phiên bản" size="small">
              <List
                dataSource={data ?? []}
                renderItem={(g) => (
                  <List.Item style={{ cursor: 'pointer', fontWeight: g.id === current.id ? 600 : 400 }} onClick={() => setSelectedId(g.id)}>
                    v{g.version} {g.id === data?.[0].id && <Tag color="green">Mới nhất</Tag>}
                    <div style={{ fontSize: 12, color: 'rgba(0,0,0,.45)' }}>{formatDateTime(g.created_at)}</div>
                  </List.Item>
                )}
              />
            </Card>
          </Col>
          <Col xs={24} lg={18}>
            <Card title={`${current.title} · v${current.version}`} extra={<span>{current.created_by?.full_name} · {formatDateTime(current.created_at)}</span>}>
              <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{current.content}</Typography.Paragraph>
            </Card>
          </Col>
        </Row>
      )}
      <Modal open={editing} title="Xuất bản phiên bản mới" okText="Lưu phiên bản" width={720} confirmLoading={pending}
        onCancel={() => setEditing(false)} onOk={() => form.submit()}>
        <Form form={form} layout="vertical" onFinish={async (v) => {
          if (await run(() => publishGuideline(projectId, v), 'Đã xuất bản phiên bản mới')) {
            setEditing(false)
            setSelectedId(null)
            setVersion((n) => n + 1)
          }
        }}>
          <Form.Item name="title" label="Tiêu đề" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="content" label="Nội dung (Markdown)" rules={[{ required: true }]}><Input.TextArea rows={14} /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
