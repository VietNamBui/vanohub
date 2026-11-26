import { CloudDownloadOutlined, PlusOutlined, SyncOutlined } from '@ant-design/icons'
import { Alert, App, Button, Card, Checkbox, DatePicker, Dropdown, Form, Input, InputNumber, Modal, Progress, Select, Space, Table, Tag, Typography } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { getErrorMessage } from '../../../shared/api/errors'
import StateView from '../../../shared/components/StateView'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import { listTeams } from '../../teams/api'
import {
  createBatch,
  getCvatStatus,
  importBatchFromCvat,
  listBatches,
  listDatasets,
  setBatchLock,
  syncBatchWithCvat,
  updateBatch,
} from '../api'
import DataStatusTag from '../components/DataStatusTag'
import { useProject } from '../projectContext'
import type { Batch } from '../types'

type ModalState = { type: 'create' } | { type: 'edit'; batch: Batch } | { type: 'import'; batch: Batch } | null

/**
 * PM-04 Batches. Tạo batch rồi "Nhập job từ CVAT" (1 batch ↔ 1 CVAT task — ánh xạ đề xuất).
 * Release / auto-lock / post-processing chưa có đặc tả nên chưa làm.
 */
export default function BatchesPage() {
  const { projectId, can } = useProject()
  const [searchParams] = useSearchParams()
  const [dataset, setDataset] = useState<number | undefined>(() =>
    searchParams.get('dataset') ? Number(searchParams.get('dataset')) : undefined,
  )
  const [version, setVersion] = useState(0)
  const [modal, setModal] = useState<ModalState>(null)
  const [form] = Form.useForm()
  const { run, pending } = useAction()
  const { modal: modalApi } = App.useApp()
  const { data, error, isLoading, retry } = useRequest(`batches:${projectId}:${dataset ?? ''}:${version}`, () =>
    listBatches(projectId, { dataset }),
  )
  const { data: datasets } = useRequest(`datasets:${projectId}`, () => listDatasets(projectId))
  const { data: cvat } = useRequest('cvat-status', getCvatStatus)
  const { data: teams } = useRequest(`teams:${projectId}`, () => listTeams(projectId))
  const reload = () => setVersion((v) => v + 1)
  const canManage = can('manage_data')

  async function submit(values: { dataset?: number; name?: string; deadline?: Dayjs | null; cvat_task_id?: number }) {
    let ok: unknown
    if (modal?.type === 'create') {
      ok = await run(() => createBatch(projectId, {
        dataset: values.dataset!, name: values.name!, deadline: values.deadline?.isValid() ? values.deadline.toISOString() : null,
      }), 'Đã tạo batch')
    } else if (modal?.type === 'edit') {
      ok = await run(() => updateBatch(projectId, modal.batch.id, {
        name: values.name, deadline: values.deadline?.isValid() ? values.deadline.toISOString() : null,
      }), 'Đã lưu batch')
    } else if (modal?.type === 'import') {
      const result = await run(() => importBatchFromCvat(projectId, modal.batch.id, values.cvat_task_id!))
      if (result) modalApi.success({ title: 'Đã nhập từ CVAT', content: `Task "${result.task_name}": tạo mới ${result.created}, cập nhật ${result.updated} / ${result.total} job.` })
      ok = result
    }
    if (ok) {
      setModal(null)
      reload()
    }
  }

  async function sync(batch: Batch, countObjects: boolean) {
    const result = await run(() => syncBatchWithCvat(projectId, batch.id, countObjects))
    if (result) {
      modalApi.info({ title: 'Đồng bộ CVAT xong', content: `${result.updated} / ${result.total} job có thay đổi.` })
      reload()
    }
  }

  function open(state: ModalState) {
    form.resetFields()
    if (state?.type === 'edit') {
      const parsed = state.batch.deadline ? dayjs(state.batch.deadline) : null
      form.setFieldsValue({ name: state.batch.name, deadline: parsed?.isValid() ? parsed : null })
    }
    if (state?.type === 'create') form.setFieldsValue({ dataset })
    setModal(state)
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Batches</h1>
          <p>Mỗi batch tương ứng một CVAT task. Job được nhập từ CVAT.</p>
        </div>
        <Space>
          <Select allowClear placeholder="Tất cả dataset" style={{ width: 220 }} value={dataset} onChange={setDataset}
            options={datasets?.map((d) => ({ value: d.id, label: d.name }))} />
          {canManage && <Button type="primary" icon={<PlusOutlined />} onClick={() => open({ type: 'create' })}>Tạo batch</Button>}
        </Space>
      </div>
      {cvat && !cvat.connected && (
        <Alert type="warning" showIcon style={{ marginBottom: 16 }} title="Chưa kết nối được CVAT — nhập / đồng bộ job sẽ không chạy." description={cvat.detail} />
      )}
      <Card>
        {error != null ? (
          <StateView kind="error" description={getErrorMessage(error)} action={{ label: 'Thử lại', onClick: retry }} />
        ) : (
          <Table<Batch>
            rowKey="id"
            loading={isLoading}
            dataSource={data ?? []}
            scroll={{ x: 1000 }}
            locale={{ emptyText: 'Chưa có batch' }}
            columns={[
              { title: 'Batch', dataIndex: 'name', render: (name: string, b) => <Link to={`../jobs?batch=${b.id}`} relative="path">{name}</Link> },
              { title: 'Dataset', dataIndex: 'dataset_name' },
              { title: 'Trạng thái', dataIndex: 'status', render: (s) => <DataStatusTag status={s} /> },
              {
                title: 'Tiến độ', width: 180,
                render: (_, b) => <Progress size="small" percent={b.job_count ? Math.round((b.done_count * 100) / b.job_count) : 0} format={() => `${b.done_count}/${b.job_count}`} />,
              },
              { title: 'Chờ QC2', dataIndex: 'pending_qc2_count', align: 'right' },
              { title: 'Escalated', dataIndex: 'escalated_count', align: 'right', render: (n: number) => (n ? <Tag color="error">{n}</Tag> : 0) },
              { title: 'Deadline', dataIndex: 'deadline', render: formatDateTime },
              {
                title: 'Team phụ trách', width: 190,
                render: (_, b) => canManage && b.status !== 'delivered' ? (
                  <Select
                    size="small" allowClear placeholder="Chưa giao" style={{ width: 170 }}
                    value={b.team ?? undefined}
                    options={teams?.map((t) => ({ value: t.id, label: t.name }))}
                    onChange={async (team?: number) => {
                      const ok = await run(() => updateBatch(projectId, b.id, { team: team ?? null }),
                        team ? `Đã giao ${b.name} cho ${teams?.find((t) => t.id === team)?.name}` : `Đã bỏ giao ${b.name}`)
                      if (ok) reload()
                    }}
                  />
                ) : (b.team_name ?? <Typography.Text type="secondary">Chưa giao</Typography.Text>),
              },
              {
                title: '', hidden: !canManage, fixed: 'right',
                render: (_, b) => b.status !== 'delivered' && (
                  <Dropdown
                    menu={{
                      items: [
                        { key: 'import', icon: <CloudDownloadOutlined />, label: b.cvat_task_id ? 'Nhập lại job từ CVAT' : 'Nhập job từ CVAT', onClick: () => open({ type: 'import', batch: b }) },
                        { key: 'sync', icon: <SyncOutlined />, label: 'Đồng bộ trạng thái', disabled: !b.cvat_task_id, onClick: () => sync(b, false) },
                        { key: 'sync-objects', icon: <SyncOutlined />, label: 'Đồng bộ + đếm object', disabled: !b.cvat_task_id, onClick: () => sync(b, true) },
                        { type: 'divider' },
                        { key: 'edit', label: 'Sửa tên / deadline', onClick: () => open({ type: 'edit', batch: b }) },
                        {
                          key: 'lock', label: b.status === 'active' ? 'Khoá batch' : 'Mở khoá batch',
                          onClick: async () => (await run(() => setBatchLock(projectId, b.id, b.status === 'active'), 'Đã cập nhật')) && reload(),
                        },
                      ],
                    }}
                  >
                    <Button size="small">Thao tác</Button>
                  </Dropdown>
                ),
              },
            ]}
          />
        )}
      </Card>

      <Modal
        open={modal !== null}
        title={modal?.type === 'create' ? 'Tạo batch' : modal?.type === 'edit' ? 'Sửa batch' : 'Nhập job từ CVAT'}
        okText={modal?.type === 'import' ? 'Nhập' : 'Lưu'}
        confirmLoading={pending}
        onCancel={() => setModal(null)}
        onOk={() => form.submit()}
      >
        <Form form={form} layout="vertical" onFinish={submit}>
          {modal?.type === 'create' && (
            <Form.Item name="dataset" label="Dataset" rules={[{ required: true, message: 'Chọn dataset' }]}>
              <Select options={datasets?.filter((d) => d.status === 'active').map((d) => ({ value: d.id, label: d.name }))} />
            </Form.Item>
          )}
          {modal?.type !== 'import' && (
            <>
              <Form.Item name="name" label="Tên batch" rules={[{ required: true, message: 'Nhập tên' }]}><Input /></Form.Item>
              <Form.Item
                name="deadline"
                label="Deadline"
                extra="Giờ Việt Nam (UTC+7)."
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
            </>
          )}
          {modal?.type === 'import' && (
            <>
              <Typography.Paragraph type="secondary">
                Vanohub đọc danh sách job của CVAT task và tạo job tương ứng. Annotator được gán theo assignee CVAT nếu trùng username.
              </Typography.Paragraph>
              <Form.Item name="cvat_task_id" label="ID task CVAT" initialValue={modal.batch.cvat_task_id ?? undefined}
                rules={[{ required: true, message: 'Nhập ID task' }]}>
                <InputNumber min={1} style={{ width: '100%' }} disabled={!!modal.batch.cvat_task_id} />
              </Form.Item>
              <Checkbox disabled checked>Không ghi gì ngược lại CVAT (chỉ đọc)</Checkbox>
            </>
          )}
        </Form>
      </Modal>
    </div>
  )
}
