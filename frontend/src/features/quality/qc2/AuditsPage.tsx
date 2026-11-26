import { Alert, Card, Drawer, Progress, Space, Table, Tabs, Tag } from 'antd'
import { useState } from 'react'
import { getErrorMessage } from '../../../shared/api/errors'
import StateView from '../../../shared/components/StateView'
import UserName from '../../../shared/components/UserName'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import MemberSelect from '../../projects/components/MemberSelect'
import { useProject } from '../../projects/projectContext'
import { assignSampleAuditor, listAuditSamples, listAudits } from '../api'
import { RESULT_COLORS, RESULT_LABELS } from '../constants'
import type { Audit, AuditSample } from '../types'

/**
 * PM-09 Audit QC2 — theo dõi QC2 theo từng task (chỉ PM).
 * Quy tắc (chốt 2026-11-25): MỌI job qua QC1 đều vào QC2, mỗi job kiểm ngẫu nhiên một tỉ lệ % frame.
 * Đợt QC2 của task tự tạo khi job đầu tiên vào Chờ QC2 và tự chốt khi task bàn giao — PM không tạo tay.
 * PM chỉ phân lại người kiểm khi cần (lượt QC2 tự giao cho người QC2 đang ít việc nhất).
 */
export default function AuditsPage() {
  const { projectId } = useProject()
  const [status, setStatus] = useState('in_progress')
  const [version, setVersion] = useState(0)
  const [openAudit, setOpenAudit] = useState<Audit | null>(null)
  const { run } = useAction()
  const audits = useRequest(`audits:${projectId}:${status}:${version}`, () => listAudits(projectId, { status }))
  const samples = useRequest(`samples:${projectId}:${openAudit?.id}:${version}`, () =>
    openAudit ? listAuditSamples(projectId, { audit: openAudit.id }) : Promise.resolve([] as AuditSample[]),
  )
  const reload = () => setVersion((v) => v + 1)

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Audit QC2 theo task</h1>
          <p>Mọi job qua QC1 đều được QC2 kiểm một phần frame. Đợt QC2 của task tự tạo khi có job chờ QC2 và tự chốt khi bàn giao task.</p>
        </div>
      </div>
      <Card>
        <Tabs activeKey={status} onChange={setStatus} items={[{ key: 'in_progress', label: 'Đang kiểm' }, { key: 'completed', label: 'Đã chốt' }, { key: '', label: 'Tất cả' }]} />
        {audits.error != null ? (
          <StateView kind="error" description={getErrorMessage(audits.error)} action={{ label: 'Thử lại', onClick: audits.retry }} />
        ) : (
          <Table<Audit>
            rowKey="id"
            loading={audits.isLoading}
            dataSource={audits.data ?? []}
            locale={{ emptyText: 'Chưa có job nào tới bước QC2' }}
            columns={[
              { title: 'Task', render: (_, a) => <a onClick={() => setOpenAudit(a)}>{a.batch_name}</a> },
              { title: 'Project', dataIndex: 'dataset_name' },
              { title: 'Lượt QC2', dataIndex: 'sample_count', align: 'right' },
              {
                title: 'Kết quả', width: 260,
                render: (_, a) => (
                  <Space orientation="vertical" size={0} style={{ width: '100%' }}>
                    <Progress size="small" percent={a.sample_count ? Math.round(((a.passed + a.rejected) * 100) / a.sample_count) : 0} />
                    <span style={{ fontSize: 12 }}>Pass {a.passed} · Reject {a.rejected} · Chờ {a.pending}</span>
                  </Space>
                ),
              },
              { title: 'Trạng thái', render: (_, a) => <Tag color={a.status === 'completed' ? 'success' : 'processing'}>{a.status === 'completed' ? 'Đã chốt' : 'Đang kiểm'}</Tag> },
              { title: 'Bắt đầu', dataIndex: 'created_at', render: formatDateTime },
            ]}
          />
        )}
      </Card>

      <Drawer open={openAudit !== null} onClose={() => setOpenAudit(null)} size={860}
        title={openAudit && `QC2 · ${openAudit.dataset_name} / ${openAudit.batch_name}`}>
        {openAudit && (
          <Space orientation="vertical" style={{ width: '100%' }} size="large">
            {samples.error != null && <Alert type="error" title={getErrorMessage(samples.error)} />}
            <Table<AuditSample>
              rowKey="id" size="small" loading={samples.isLoading} dataSource={samples.data ?? []} pagination={{ pageSize: 20 }}
              columns={[
                { title: 'Job', render: (_, s) => <>{s.job.name}{s.rework_round > 0 && <Tag style={{ marginLeft: 6 }}>vòng {s.rework_round}</Tag>}</> },
                { title: 'Frame kiểm', render: (_, s) => `${s.frames.length}/${s.job.frame_count}` },
                { title: 'Annotator', render: (_, s) => <UserName user={s.job.annotator} /> },
                {
                  title: 'Người kiểm',
                  render: (_, s) => s.result === 'pending' && openAudit.status === 'in_progress' ? (
                    <MemberSelect projectId={projectId} role="qc2" size="small" style={{ width: 200 }} value={s.auditor?.id}
                      allowClear={false} placeholder="Chưa phân"
                      onChange={async (v) => (await run(() => assignSampleAuditor(projectId, s.id, v), 'Đã phân người kiểm')) && reload()} />
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
