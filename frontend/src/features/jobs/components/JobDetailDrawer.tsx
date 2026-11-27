import { ExportOutlined } from '@ant-design/icons'
import { Alert, Button, Descriptions, Drawer, Empty, Form, Input, Modal, Space, Table, Tag, Timeline, Typography } from 'antd'
import { useState } from 'react'
import { Badge } from '@/components/base/badges/badges'
import { getErrorMessage } from '../../../shared/api/errors'
import StateView from '../../../shared/components/StateView'
import UserName from '../../../shared/components/UserName'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import MemberSelect from '../../projects/components/MemberSelect'
import { useProject } from '../../projects/projectContext'
import { assignJob, getJob, resolveEscalation, setJobDeadline, setJobLock } from '../api'
import { ACTION_LABELS, JOB_STATUS_LABELS } from '../constants'
import type { JobDetail, JobErrorBrief, JobStatus } from '../types'
import AssignModal from './AssignModal'
import DeadlineModal from './DeadlineModal'
import JobStatusBadge from './JobStatusBadge'

interface Props {
  jobId: number | null
  onClose: () => void
  /** Gọi sau mỗi thao tác thay đổi job, để trang cha tải lại danh sách. */
  onChanged?: () => void
}

function describeEvent(event: JobDetail['timeline'][number]) {
  const after = event.after ?? {}
  if (event.action === 'job.status' || event.action.startsWith('qc1.') || event.action.startsWith('qc2.')) {
    const status = after.status as JobStatus | undefined
    return status ? `→ ${JOB_STATUS_LABELS[status] ?? status}` : ''
  }
  if (event.action === 'job.deadline') {
    const d = after.deadline as string | null
    return `→ ${d ? formatDateTime(d) : 'không có deadline'}`
  }
  return ''
}

/** Chi tiết Job: thông tin, dòng thời gian, lỗi đã ghi, lịch sử deadline, thao tác theo quyền. */
export default function JobDetailDrawer({ jobId, onClose, onChanged }: Props) {
  const { projectId, project, can } = useProject()
  const [version, setVersion] = useState(0)
  const { data: job, error, isLoading, retry } = useRequest(`job:${jobId}:${version}`, () =>
    jobId ? getJob(projectId, jobId) : Promise.resolve(null),
  )
  const { run, pending } = useAction()
  const [modal, setModal] = useState<'assign' | 'deadline' | 'escalation' | null>(null)
  const [escalationForm] = Form.useForm<{ annotator?: number; note: string }>()

  const canManage = can('manage_jobs')
  const refresh = () => {
    setVersion((v) => v + 1)
    onChanged?.()
  }
  async function act(action: () => Promise<unknown>, success: string) {
    if (await run(action, success)) {
      setModal(null)
      refresh()
    }
  }

  const deadlineHistory = job?.timeline.filter((e) => e.action === 'job.deadline') ?? []
  const escalationPolicy = job?.escalation_policy ?? project.escalation_policy ?? 'block'

  return (
    <Drawer
      open={jobId !== null}
      onClose={onClose}
      size={680}
      title={job ? job.name : 'Chi tiết Job'}
      extra={
        job && (
          <JobStatusBadge
            status={job.status}
            escalated={job.is_escalated}
            locked={job.is_locked}
            overdue={job.is_overdue}
            sourceMissing={job.source_missing}
          />
        )
      }
      footer={
        job && canManage && (
          <Space wrap style={{ justifyContent: 'flex-end', width: '100%' }}>
            {job.is_escalated && (
              <Button danger onClick={() => setModal('escalation')}>
                Xử lý escalation
              </Button>
            )}
            <Button onClick={() => act(() => setJobLock(projectId, job.id, !job.is_locked), job.is_locked ? 'Đã mở khoá' : 'Đã khoá job')}>
              {job.is_locked ? 'Mở khoá' : 'Khoá job'}
            </Button>
            <Button onClick={() => setModal('assign')} disabled={job.is_locked || job.status === 'delivered'}>
              Giao lại
            </Button>
            <Button type="primary" onClick={() => setModal('deadline')} disabled={job.is_locked || job.status === 'delivered'}>
              Đặt deadline
            </Button>
          </Space>
        )
      }
    >
      {isLoading && <StateView kind="loading" />}
      {error != null && <StateView kind="error" description={getErrorMessage(error)} action={{ label: 'Thử lại', onClick: retry }} />}
      {job && (
        <Space orientation="vertical" size="large" style={{ width: '100%' }}>
          {job.source_missing && (
            <Alert
              type="warning"
              showIcon
              title="Không còn tìm thấy job nguồn trên CVAT ở lần đồng bộ gần nhất. Trạng thái trên VanoHub vẫn được giữ nguyên."
            />
          )}
          {job.is_escalated && (
            <Alert
              type={escalationPolicy === 'warn_only' ? 'warning' : 'error'}
              showIcon
              title={
                escalationPolicy === 'warn_only'
                  ? `Job vượt số vòng rework tối đa (${job.rework_round}/${job.max_rework_rounds}) — chế độ cảnh báo.`
                  : `Job vượt số vòng rework tối đa (${job.rework_round}/${job.max_rework_rounds}).`
              }
            />
          )}
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="Project">{job.dataset_name}</Descriptions.Item>
            <Descriptions.Item label="Task">{job.batch_name ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="Annotator"><UserName user={job.annotator} empty="Chưa giao" /></Descriptions.Item>
            <Descriptions.Item label="Người QC1"><UserName user={job.qc1_reviewer} empty="Chưa giao" /></Descriptions.Item>
            <Descriptions.Item label="Deadline">{formatDateTime(job.deadline)}</Descriptions.Item>
            <Descriptions.Item label="Round rework">{job.rework_round} / {job.max_rework_rounds}</Descriptions.Item>
            <Descriptions.Item label="Số object">{job.object_count}</Descriptions.Item>
            <Descriptions.Item label="Số frame">{job.frame_count}</Descriptions.Item>
            <Descriptions.Item label="CVAT" span={2}>
              {job.cvat_job_id ? (
                <Space wrap>
                  <span>Job #{job.cvat_job_id}</span>
                  {job.cvat_stage && <Tag>{job.cvat_stage} / {job.cvat_state}</Tag>}
                  {job.source_missing && (
                    <Badge type="pill-color" size="sm" color="warning">
                      Thiếu nguồn CVAT
                    </Badge>
                  )}
                  {job.cvat_url && (
                    <Button size="small" icon={<ExportOutlined />} href={job.cvat_url} target="_blank" rel="noreferrer">
                      Mở trong CVAT
                    </Button>
                  )}
                </Space>
              ) : (
                <Typography.Text type="secondary">Chưa liên kết CVAT</Typography.Text>
              )}
            </Descriptions.Item>
          </Descriptions>

          <div>
            <Typography.Title level={5}>Dòng thời gian</Typography.Title>
            {job.timeline.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Chưa có sự kiện" />
            ) : (
              <Timeline
                items={job.timeline.map((e) => ({
                  color: e.action === 'qc2.reject' ? 'red' : e.action === 'qc2.pass' ? 'green' : 'blue',
                  content: (
                    <div>
                      <strong>{ACTION_LABELS[e.action] ?? e.action}</strong> {describeEvent(e)}
                      <div className="text-xs text-tertiary">
                        {formatDateTime(e.created_at)} · {e.actor?.full_name ?? 'Hệ thống'}
                        {e.note ? ` · ${e.note}` : ''}
                      </div>
                    </div>
                  ),
                }))}
              />
            )}
          </div>

          <div>
            <Typography.Title level={5}>Lỗi đã ghi</Typography.Title>
            <Table<JobErrorBrief>
              size="small"
              rowKey="id"
              pagination={false}
              dataSource={job.errors}
              rowClassName={(err) => (err.is_voided ? 'opacity-60' : '')}
              locale={{ emptyText: 'Chưa có lỗi' }}
              columns={[
                { title: 'Stage', dataIndex: 'stage', render: (s: string) => <Tag>{s.toUpperCase()}</Tag> },
                { title: 'Round', dataIndex: 'rework_round' },
                {
                  title: 'Loại lỗi',
                  render: (_, err) => (
                    <div className="flex flex-col gap-1">
                      <span className={err.is_voided ? 'text-tertiary line-through' : 'font-medium text-primary'}>
                        {err.category}
                      </span>
                      <div className="flex flex-wrap gap-1">
                        {err.verdict === 'edge' && (
                          <Badge type="pill-color" size="sm" color="warning">
                            Cận biên
                          </Badge>
                        )}
                        {err.verdict === 'fail' && (
                          <Badge type="pill-color" size="sm" color="error">
                            Lỗi
                          </Badge>
                        )}
                        {err.is_voided && (
                          <Badge type="pill-color" size="sm" color="gray">
                            Đã huỷ lỗi
                          </Badge>
                        )}
                      </div>
                    </div>
                  ),
                },
                {
                  title: 'Vị trí / Cuboid',
                  render: (_, err) => {
                    const hasStructured =
                      err.frame_number != null || err.cvat_object_id != null || Boolean(err.is_missing_object)
                    return (
                      <div className="flex flex-col gap-1">
                        {hasStructured && (
                          <div className="flex flex-wrap gap-1">
                            {err.frame_number != null && (
                              <Badge type="pill-color" size="sm" color="gray">
                                Frame #{err.frame_number}
                              </Badge>
                            )}
                            {err.cvat_object_id != null && (
                              <Badge type="pill-color" size="sm" color="blue">
                                Object #{err.cvat_object_id}
                              </Badge>
                            )}
                            {err.is_missing_object && (
                              <Badge type="pill-color" size="sm" color="orange">
                                Thiếu đối tượng
                              </Badge>
                            )}
                          </div>
                        )}
                        {err.location ? (
                          <span className={err.is_voided ? 'text-xs text-tertiary line-through' : 'text-xs text-secondary'}>
                            {err.location}
                          </span>
                        ) : !hasStructured ? (
                          <span className="text-xs text-tertiary">—</span>
                        ) : null}
                      </div>
                    )
                  },
                },
                {
                  title: 'Mô tả',
                  dataIndex: 'description',
                  render: (desc: string, err) => (
                    <span className={err.is_voided ? 'text-tertiary line-through' : undefined}>
                      {desc || '—'}
                    </span>
                  ),
                },
              ]}
            />
          </div>

          <div>
            <Typography.Title level={5}>Lịch sử deadline</Typography.Title>
            {deadlineHistory.length === 0 ? (
              <Typography.Text type="secondary">Chưa đổi deadline.</Typography.Text>
            ) : (
              <ul style={{ paddingLeft: 18, margin: 0 }}>
                {deadlineHistory.map((e) => (
                  <li key={e.id}>
                    {formatDateTime(e.before?.deadline as string | null)} → {formatDateTime(e.after?.deadline as string | null)}
                    <Typography.Text type="secondary"> · {e.actor?.full_name} · {formatDateTime(e.created_at)}</Typography.Text>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Space>
      )}

      {job && (
        <>
          <AssignModal
            open={modal === 'assign'}
            projectId={projectId}
            initial={{ annotator: job.annotator?.id ?? null, qc1_reviewer: job.qc1_reviewer?.id ?? null }}
            confirmLoading={pending}
            onCancel={() => setModal(null)}
            onSubmit={(values) => act(() => assignJob(projectId, job.id, values), 'Đã giao lại job')}
          />
          <DeadlineModal
            open={modal === 'deadline'}
            currentDeadline={job.deadline}
            confirmLoading={pending}
            onCancel={() => setModal(null)}
            onSubmit={(deadline, note) => act(() => setJobDeadline(projectId, job.id, deadline, note), 'Đã cập nhật deadline')}
          />
          <Modal
            open={modal === 'escalation'}
            title="Xử lý job Escalated"
            okText="Xác nhận"
            confirmLoading={pending}
            onCancel={() => setModal(null)}
            onOk={() => escalationForm.submit()}
            destroyOnHidden
          >
            <Typography.Paragraph type="secondary">
              Gỡ cờ Escalated và đặt lại số vòng rework về 0 (lịch sử lỗi vẫn được giữ). Có thể giao cho annotator khác.
            </Typography.Paragraph>
            <Form
              form={escalationForm}
              layout="vertical"
              preserve={false}
              onFinish={(v) => act(() => resolveEscalation(projectId, job.id, v.annotator, v.note ?? ''), 'Đã xử lý escalation')}
            >
              <Form.Item name="annotator" label="Giao cho annotator khác (tuỳ chọn)">
                <MemberSelect projectId={projectId} role="annotator" />
              </Form.Item>
              <Form.Item name="note" label="Ghi chú">
                <Input.TextArea rows={2} />
              </Form.Item>
            </Form>
          </Modal>
        </>
      )}
    </Drawer>
  )
}
