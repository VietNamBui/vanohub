import { Button, Card, Col, Form, Input, Row, Select, Switch, Table, Tag } from 'antd'
import { useState } from 'react'
import { getErrorMessage } from '../../../shared/api/errors'
import StateView from '../../../shared/components/StateView'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { useProject } from '../../projects/projectContext'
import { createErrorCategory, listErrorCategories, updateErrorCategory } from '../api'
import { SEVERITY_COLORS, SEVERITY_LABELS } from '../constants'
import type { ErrorCategory } from '../types'

const APPLIES = { qc1: 'QC1', qc2: 'QC2', both: 'QC1 & QC2' }

/** PM-15 Danh mục lỗi — dùng chung cho QC1 và QC2. Không xoá (lỗi đã ghi đang tham chiếu), chỉ tắt. */
export default function ErrorCategoriesPage() {
  const { projectId } = useProject()
  const [version, setVersion] = useState(0)
  const [editing, setEditing] = useState<ErrorCategory | null>(null)
  const [form] = Form.useForm<Partial<ErrorCategory>>()
  const { run, pending } = useAction()
  const { data, error, isLoading, retry } = useRequest(`error-categories:${projectId}:${version}`, () => listErrorCategories(projectId))
  const reload = () => setVersion((v) => v + 1)

  function edit(category: ErrorCategory | null) {
    setEditing(category)
    form.resetFields()
    form.setFieldsValue(category ?? { severity: 'minor', applies_to: 'both', is_active: true })
  }

  async function save(values: Partial<ErrorCategory>) {
    const ok = await run(
      () => (editing ? updateErrorCategory(projectId, editing.id, values) : createErrorCategory(projectId, values)),
      editing ? 'Đã lưu loại lỗi' : 'Đã thêm loại lỗi',
    )
    if (ok) {
      edit(null)
      reload()
    }
  }

  if (error != null) return <StateView kind="error" description={getErrorMessage(error)} action={{ label: 'Thử lại', onClick: retry }} />

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Danh mục lỗi</h1>
          <p>Loại lỗi mà QC1 / QC2 chọn khi Reject.</p>
        </div>
      </div>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={15}>
          <Card>
            <Table<ErrorCategory>
              rowKey="id" loading={isLoading} dataSource={data ?? []} pagination={false}
              locale={{ emptyText: 'Chưa có loại lỗi' }}
              columns={[
                { title: 'Tên', dataIndex: 'name' },
                { title: 'Mô tả', dataIndex: 'description', ellipsis: true },
                { title: 'Mức độ', dataIndex: 'severity', render: (s: ErrorCategory['severity']) => <Tag color={SEVERITY_COLORS[s]}>{SEVERITY_LABELS[s]}</Tag> },
                { title: 'Stage', dataIndex: 'applies_to', render: (a: ErrorCategory['applies_to']) => APPLIES[a] },
                { title: 'Dùng', dataIndex: 'is_active', render: (v: boolean) => (v ? <Tag color="success">Đang dùng</Tag> : <Tag>Đã tắt</Tag>) },
                { title: '', render: (_, c) => <Button size="small" onClick={() => edit(c)}>Sửa</Button> },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} lg={9}>
          <Card title={editing ? `Sửa: ${editing.name}` : 'Thêm loại lỗi'}>
            <Form form={form} layout="vertical" onFinish={save} initialValues={{ severity: 'minor', applies_to: 'both', is_active: true }}>
              <Form.Item name="name" label="Tên lỗi" rules={[{ required: true }]}><Input /></Form.Item>
              <Form.Item name="description" label="Mô tả"><Input.TextArea rows={3} /></Form.Item>
              <Form.Item name="severity" label="Mức độ mặc định">
                <Select options={Object.entries(SEVERITY_LABELS).map(([value, label]) => ({ value, label }))} />
              </Form.Item>
              <Form.Item name="applies_to" label="Stage áp dụng">
                <Select options={Object.entries(APPLIES).map(([value, label]) => ({ value, label }))} />
              </Form.Item>
              <Form.Item name="is_active" label="Đang dùng" valuePropName="checked"><Switch /></Form.Item>
              <Button type="primary" htmlType="submit" loading={pending}>Lưu</Button>
              {editing && <Button style={{ marginLeft: 8 }} onClick={() => edit(null)}>Huỷ</Button>}
            </Form>
          </Card>
        </Col>
      </Row>
    </div>
  )
}
