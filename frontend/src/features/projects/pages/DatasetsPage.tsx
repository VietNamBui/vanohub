import { PlusOutlined } from '@ant-design/icons'
import { Button, Card, Form, Input, Modal, Progress, Space, Table, Tabs } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router'
import { getErrorMessage } from '../../../shared/api/errors'
import StateView from '../../../shared/components/StateView'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDate } from '../../../shared/utils/format'
import { createDataset, listDatasets, setDatasetLock, updateDataset } from '../api'
import DataStatusTag from '../components/DataStatusTag'
import { useProject } from '../projectContext'
import type { Dataset } from '../types'

/** PM-03 Datasets. Xoá dataset chưa làm vì chưa có đặc tả xoá an toàn. */
export default function DatasetsPage() {
  const { projectId, can } = useProject()
  const [status, setStatus] = useState('')
  const [search, setSearch] = useState('')
  const [version, setVersion] = useState(0)
  const [editing, setEditing] = useState<Dataset | 'new' | null>(null)
  const [form] = Form.useForm<{ name: string; description: string }>()
  const { run, pending } = useAction()
  const { data, error, isLoading, retry } = useRequest(`datasets:${projectId}:${status}:${search}:${version}`, () =>
    listDatasets(projectId, { status, search }),
  )
  const reload = () => setVersion((v) => v + 1)
  const canManage = can('manage_data')

  async function save(values: { name: string; description: string }) {
    const ok = await run(
      () => (editing === 'new' ? createDataset(projectId, values) : updateDataset(projectId, (editing as Dataset).id, values)),
      editing === 'new' ? 'Đã tạo dataset' : 'Đã lưu dataset',
    )
    if (ok) {
      setEditing(null)
      reload()
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Datasets</h1>
          <p>Nhóm dữ liệu của dự án. Mỗi dataset gồm nhiều batch.</p>
        </div>
        {canManage && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing('new')}>Tạo dataset</Button>
        )}
      </div>
      <Card>
        <Tabs
          activeKey={status}
          onChange={setStatus}
          items={[
            { key: '', label: 'Tất cả' },
            { key: 'active', label: 'Đang xử lý' },
            { key: 'locked', label: 'Đã khoá' },
            { key: 'delivered', label: 'Đã bàn giao' },
          ]}
        />
        <Input.Search allowClear placeholder="Tìm dataset" style={{ width: 260, marginBottom: 16 }} onSearch={setSearch} />
        {error != null ? (
          <StateView kind="error" description={getErrorMessage(error)} action={{ label: 'Thử lại', onClick: retry }} />
        ) : (
          <Table<Dataset>
            rowKey="id"
            loading={isLoading}
            dataSource={data ?? []}
            locale={{ emptyText: 'Chưa có dataset' }}
            columns={[
              { title: 'Dataset', dataIndex: 'name', render: (name: string, d) => <Link to={`../batches?dataset=${d.id}`} relative="path">{name}</Link> },
              { title: 'Mô tả', dataIndex: 'description', ellipsis: true },
              { title: 'Trạng thái', dataIndex: 'status', render: (s) => <DataStatusTag status={s} /> },
              { title: 'Batch', dataIndex: 'batch_count', align: 'right' },
              {
                title: 'Tiến độ job', width: 200,
                render: (_, d) => (
                  <Progress size="small" percent={d.job_count ? Math.round((d.done_count * 100) / d.job_count) : 0}
                    format={() => `${d.done_count}/${d.job_count}`} />
                ),
              },
              { title: 'Ngày tạo', dataIndex: 'created_at', render: formatDate },
              {
                title: '', hidden: !canManage,
                render: (_, d) => d.status !== 'delivered' && (
                  <Space>
                    <Button size="small" onClick={() => { form.setFieldsValue(d); setEditing(d) }}>Sửa</Button>
                    <Button size="small" onClick={async () => (await run(() => setDatasetLock(projectId, d.id, d.status === 'active'),
                      d.status === 'active' ? 'Đã khoá dataset' : 'Đã mở khoá')) && reload()}>
                      {d.status === 'active' ? 'Khoá' : 'Mở khoá'}
                    </Button>
                  </Space>
                ),
              },
            ]}
          />
        )}
      </Card>
      <Modal
        open={editing !== null}
        title={editing === 'new' ? 'Tạo dataset' : 'Sửa dataset'}
        okText="Lưu"
        confirmLoading={pending}
        onCancel={() => setEditing(null)}
        onOk={() => form.submit()}
        afterOpenChange={(open) => open && editing === 'new' && form.resetFields()}
      >
        <Form form={form} layout="vertical" onFinish={save}>
          <Form.Item name="name" label="Tên dataset" rules={[{ required: true, message: 'Nhập tên' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="Mô tả">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
