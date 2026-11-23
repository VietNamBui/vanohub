import { PlusOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Descriptions, Drawer, Form, Input, Popconfirm, Progress, Radio, Select, Slider, Space, Statistic, Table, Tabs, Tag } from 'antd'
import { useState } from 'react'
import { getErrorMessage } from '../../../shared/api/errors'
import StateView from '../../../shared/components/StateView'
import UserName from '../../../shared/components/UserName'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime, formatNumber } from '../../../shared/utils/format'
import { getSettings, listBatches } from '../../projects/api'
import MemberSelect from '../../projects/components/MemberSelect'
import { useProject } from '../../projects/projectContext'
import { assignSampleAuditor, completeAudit, createAudit, listAuditSamples, listAudits, previewAudit } from '../api'
import { METHOD_LABELS, RESULT_COLORS, RESULT_LABELS, STRATIFY_LABELS } from '../constants'
import type { Audit, AuditInput, AuditPreview, AuditSample } from '../types'

/**
 * PM-09 Audits — quản lý QC2 Internal Audit cấp dự án (chỉ PM).
 * Phân biệt: job ĐỦ ĐIỀU KIỆN (Chờ QC2) ≠ job ĐƯỢC CHỌN MẪU ≠ job ĐÃ AUDIT.
 */
export default function AuditsPage() {
  const { projectId } = useProject()
  const [status, setStatus] = useState('in_progress')
  const [version, setVersion] = useState(0)
  const [creating, setCreating] = useState(false)
  const [preview, setPreview] = useState<AuditPreview | null>(null)
  const [openAudit, setOpenAudit] = useState<Audit | null>(null)
  const [form] = Form.useForm<AuditInput>()
  const method = Form.useWatch('method', form)
  const { run, pending } = useAction()
  const audits = useRequest(`audits:${projectId}:${status}:${version}`, () => listAudits(projectId, { status }))
  const batches = useRequest(`batches:${projectId}:${version}`, () => listBatches(projectId, { status: 'active' }))
  const samples = useRequest(`samples:${projectId}:${openAudit?.id}:${version}`, () =>
    openAudit ? listAuditSamples(projectId, { audit: openAudit.id }) : Promise.resolve([] as AuditSample[]),
  )
  const reload = () => setVersion((v) => v + 1)

  async function startCreate() {
    const settings = await run(() => getSettings(projectId))
    form.resetFields()
    if (settings) form.setFieldsValue({ method: settings.sampling_method, sampling_rate: settings.sampling_rate, stratify_by: settings.stratify_by })
    setPreview(null)
    setCreating(true)
  }

  async function doPreview() {
    const values = await form.validateFields()
    const result = await run(() => previewAudit(projectId, { ...values, seed: undefined }))
    if (result) setPreview(result)
  }

  async function doCreate() {
    const values = await form.validateFields()
    // Gửi lại seed của bản xem trước → backend chọn đúng những job đã xem.
    const created = await run(() => createAudit(projectId, { ...values, seed: preview?.seed }), 'Đã tạo audit')
    if (created) {
      setCreating(false)
      setStatus('in_progress')
      reload()
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Quản lý Audit QC2</h1>
          <p>Tạo đợt audit theo batch, chọn mẫu Random / Stratified, phân auditor, chốt kết quả.</p>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={startCreate}>Tạo audit</Button>
      </div>
      <Card>
        <Tabs activeKey={status} onChange={setStatus} items={[{ key: 'in_progress', label: 'Đang audit' }, { key: 'completed', label: 'Đã chốt' }, { key: '', label: 'Tất cả' }]} />
        {audits.error != null ? (
          <StateView kind="error" description={getErrorMessage(audits.error)} action={{ label: 'Thử lại', onClick: audits.retry }} />
        ) : (
          <Table<Audit>
            rowKey="id"
            loading={audits.isLoading}
            dataSource={audits.data ?? []}
            locale={{ emptyText: 'Chưa có audit' }}
            columns={[
              { title: 'Audit', render: (_, a) => <a onClick={() => setOpenAudit(a)}>#{a.id} · {a.dataset_name} / {a.batch_name}</a> },
              { title: 'Phương pháp', render: (_, a) => `${METHOD_LABELS[a.method]} ${a.sampling_rate}%${a.stratify_by ? ` · theo ${STRATIFY_LABELS[a.stratify_by]}` : ''}` },
              { title: 'Đủ điều kiện → mẫu', render: (_, a) => `${a.eligible_count} → ${a.sample_count}` },
              {
                title: 'Kết quả', width: 260,
                render: (_, a) => (
                  <Space orientation="vertical" size={0} style={{ width: '100%' }}>
                    <Progress size="small" percent={a.sample_count ? Math.round(((a.passed + a.rejected) * 100) / a.sample_count) : 0} />
                    <span style={{ fontSize: 12 }}>Pass {a.passed} · Reject {a.rejected} · Chờ {a.pending}</span>
                  </Space>
                ),
              },
              { title: 'Trạng thái', render: (_, a) => <Tag color={a.status === 'completed' ? 'success' : 'processing'}>{a.status === 'completed' ? 'Đã chốt' : 'Đang audit'}</Tag> },
              { title: 'Tạo lúc', dataIndex: 'created_at', render: formatDateTime },
              {
                title: '',
                render: (_, a) => a.status === 'in_progress' && (
                  <Popconfirm
                    title="Chốt audit?"
                    description="Job đủ điều kiện nhưng không được chọn mẫu sẽ chuyển sang Đã duyệt."
                    disabled={a.pending > 0}
                    onConfirm={async () => (await run(() => completeAudit(projectId, a.id), 'Đã chốt audit')) && reload()}
                  >
                    <Button size="small" disabled={a.pending > 0} title={a.pending > 0 ? 'Còn mẫu chưa audit' : undefined}>Chốt</Button>
                  </Popconfirm>
                ),
              },
            ]}
          />
        )}
      </Card>

      {/* Tạo audit + xem trước mẫu */}
      <Drawer open={creating} onClose={() => setCreating(false)} size={720} title="Tạo audit"
        footer={
          <Space style={{ justifyContent: 'flex-end', width: '100%' }}>
            <Button onClick={doPreview} loading={pending}>Xem trước mẫu</Button>
            <Button type="primary" onClick={doCreate} loading={pending} disabled={!preview}>Tạo audit với mẫu này</Button>
          </Space>
        }>
        <Form form={form} layout="vertical" onValuesChange={() => setPreview(null)}>
          <Form.Item name="batch" label="Batch" rules={[{ required: true, message: 'Chọn batch' }]}>
            <Select
              placeholder="Chọn batch có job Chờ QC2"
              options={batches.data?.map((b) => ({ value: b.id, label: `${b.dataset_name} / ${b.name} — ${b.pending_qc2_count} job chờ QC2`, disabled: b.pending_qc2_count === 0 }))}
            />
          </Form.Item>
          <Form.Item name="method" label="Phương pháp sampling">
            <Radio.Group options={[{ value: 'random', label: 'Random' }, { value: 'stratified', label: 'Stratified' }]} />
          </Form.Item>
          <Form.Item name="sampling_rate" label="Tỉ lệ lấy mẫu (%)">
            <Slider min={1} max={100} marks={{ 1: '1%', 50: '50%', 100: '100%' }} />
          </Form.Item>
          {method === 'stratified' && (
            <Form.Item name="stratify_by" label="Phân tầng theo">
              <Select options={[{ value: 'annotator', label: 'Annotator' }, { value: 'qc1_reviewer', label: 'Người QC1' }, { value: 'dataset', label: 'Dataset' }]} />
            </Form.Item>
          )}
          <Form.Item name="auditors" label="Auditor QC2" extra="Mẫu được chia đều; tự bỏ qua auditor vi phạm luật bốn mắt. Để trống thì phân sau.">
            <MemberSelect projectId={projectId} role="qc2" mode="multiple" />
          </Form.Item>
          <Form.Item name="note" label="Ghi chú"><Input.TextArea rows={2} /></Form.Item>
        </Form>
        {preview && (
          <Card size="small" title="Xem trước mẫu">
            <Space size="large" wrap>
              <Statistic title="Job đủ điều kiện" value={preview.eligible_count} />
              <Statistic title="Số mẫu" value={preview.sample_count} />
              <Statistic title="Object ước tính" value={formatNumber(preview.estimated_objects)} />
              <Statistic title="Frame ước tính" value={formatNumber(preview.estimated_frames)} />
            </Space>
            <Table
              size="small" rowKey={(s) => s.job.id} style={{ marginTop: 12 }} pagination={{ pageSize: 10 }}
              dataSource={preview.samples}
              columns={[
                { title: 'Job', render: (_, s) => s.job.name },
                { title: 'Tầng', dataIndex: 'stratum', render: (v: string) => v || '—' },
                { title: 'Annotator', render: (_, s) => <UserName user={s.job.annotator} /> },
                { title: 'QC1', render: (_, s) => <UserName user={s.job.qc1_reviewer} /> },
              ]}
            />
          </Card>
        )}
      </Drawer>

      {/* Chi tiết audit */}
      <Drawer open={openAudit !== null} onClose={() => setOpenAudit(null)} size={820} title={openAudit && `Audit #${openAudit.id} · ${openAudit.batch_name}`}>
        {openAudit && (
          <Space orientation="vertical" style={{ width: '100%' }} size="large">
            <Descriptions size="small" bordered column={2}>
              <Descriptions.Item label="Phương pháp">{METHOD_LABELS[openAudit.method]} {openAudit.sampling_rate}%</Descriptions.Item>
              <Descriptions.Item label="Phân tầng">{openAudit.stratify_by ? STRATIFY_LABELS[openAudit.stratify_by] : '—'}</Descriptions.Item>
              <Descriptions.Item label="Đủ điều kiện">{openAudit.eligible_count} job</Descriptions.Item>
              <Descriptions.Item label="Seed">{openAudit.seed}</Descriptions.Item>
              <Descriptions.Item label="Người tạo"><UserName user={openAudit.created_by} /></Descriptions.Item>
              <Descriptions.Item label="Ghi chú">{openAudit.note || '—'}</Descriptions.Item>
            </Descriptions>
            {samples.error != null && <Alert type="error" title={getErrorMessage(samples.error)} />}
            <Table<AuditSample>
              rowKey="id" size="small" loading={samples.isLoading} dataSource={samples.data ?? []} pagination={false}
              columns={[
                { title: 'Job', render: (_, s) => s.job.name },
                { title: 'Tầng', dataIndex: 'stratum', render: (v: string) => v || '—' },
                { title: 'Annotator', render: (_, s) => <UserName user={s.job.annotator} /> },
                {
                  title: 'Auditor',
                  render: (_, s) => s.result === 'pending' && openAudit.status === 'in_progress' ? (
                    <MemberSelect projectId={projectId} role="qc2" size="small" style={{ width: 200 }} value={s.auditor?.id}
                      allowClear={false}
                      onChange={async (v) => (await run(() => assignSampleAuditor(projectId, s.id, v), 'Đã phân auditor')) && reload()} />
                  ) : <UserName user={s.auditor} />,
                },
                { title: 'Kết quả', render: (_, s) => <Tag color={RESULT_COLORS[s.result]}>{RESULT_LABELS[s.result]}</Tag> },
                { title: 'Lỗi', render: (_, s) => s.errors.length || '—' },
              ]}
            />
          </Space>
        )}
      </Drawer>
    </div>
  )
}
