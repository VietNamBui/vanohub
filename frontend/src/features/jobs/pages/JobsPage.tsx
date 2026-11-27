import { ExportOutlined, ReloadOutlined } from '@ant-design/icons'
import { App, Button, Card, Checkbox, Input, Select, Space, Table, Tabs, Tag, Tooltip, Typography, type TableProps } from 'antd'
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
import { getErrorMessage } from '../../../shared/api/errors'
import StateView from '../../../shared/components/StateView'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import { listBatches, listDatasets, listMembers } from '../../projects/api'
import { assignSampleAuditor } from '../../quality/api'
import { useProject } from '../../projects/projectContext'
import { assignJob, bulkAssign, bulkDeadline, listJobs } from '../api'
import AssigneeSelect from '../components/AssigneeSelect'
import AssignModal from '../components/AssignModal'
import DeadlineModal from '../components/DeadlineModal'
import JobDetailDrawer from '../components/JobDetailDrawer'
import JobStatusTag from '../components/JobStatusTag'
import { JOB_STATUS_LABELS } from '../constants'
import type { Job, JobFilters, JobStatus, Stage } from '../types'

const TABS: { key: Stage | ''; label: string }[] = [
  { key: '', label: 'Tất cả' },
  { key: 'annotation', label: 'Annotation' },
  { key: 'qc1', label: 'QC1' },
  { key: 'qc2', label: 'QC2' },
  { key: 'done', label: 'Hoàn tất' },
]

const VALID_STAGES = new Set<Stage>(['annotation', 'qc1', 'qc2', 'done'])

function parsePositiveInt(raw: string | null): number | undefined {
  if (!raw) return undefined
  const num = Number(raw)
  return Number.isInteger(num) && num > 0 ? num : undefined
}

function parseUrlFilters(sp: URLSearchParams): Omit<JobFilters, 'page' | 'page_size' | 'ordering'> {
  const rawStage = sp.get('stage') ?? ''
  const stage: Stage | '' = VALID_STAGES.has(rawStage as Stage) ? (rawStage as Stage) : ''
  return {
    stage,
    status: sp.get('status') || undefined,
    dataset: parsePositiveInt(sp.get('dataset')),
    batch: parsePositiveInt(sp.get('batch')),
    assignee: parsePositiveInt(sp.get('assignee')),
    search: sp.get('search') || undefined,
    escalated: sp.get('escalated') === '1',
    overdue: sp.get('overdue') === '1',
    due_soon: sp.get('due_soon') === '1',
    unassigned: sp.get('unassigned') === '1',
  }
}

/** PM-05 Jobs — danh sách job dùng chung, lọc theo stage / dataset / batch / cờ. */
export default function JobsPage() {
  const { projectId, can } = useProject()
  const [searchParams, setSearchParams] = useSearchParams()
  const spKey = searchParams.toString()
  const urlFilters = useMemo(() => parseUrlFilters(searchParams), [searchParams])
  const [pager, setPager] = useState<{ spKey: string; page: number; page_size: number; ordering?: string }>({
    spKey,
    page: 1,
    page_size: 50,
    ordering: undefined,
  })
  const filters: JobFilters = useMemo(
    () => ({
      ...urlFilters,
      page: pager.spKey === spKey ? pager.page : 1,
      page_size: pager.page_size,
      ordering: pager.ordering,
    }),
    [urlFilters, pager, spKey],
  )
  const [searchDraft, setSearchDraft] = useState(urlFilters.search ?? '')
  const [syncedSearch, setSyncedSearch] = useState(urlFilters.search ?? '')
  if (syncedSearch !== (urlFilters.search ?? '')) {
    setSyncedSearch(urlFilters.search ?? '')
    setSearchDraft(urlFilters.search ?? '')
  }

  const [version, setVersion] = useState(0)
  const [selected, setSelected] = useState<number[]>([])
  const [openJob, setOpenJob] = useState<number | null>(null)
  const [bulk, setBulk] = useState<'assign' | 'deadline' | null>(null)
  const { run, pending } = useAction()
  const { message } = App.useApp()

  const key = `jobs:${projectId}:${JSON.stringify(filters)}:${version}`
  const { data, error, isLoading, retry } = useRequest(key, () => listJobs(projectId, filters))
  const { data: datasets } = useRequest(`datasets:${projectId}`, () => listDatasets(projectId))
  // Task (model Batch) thuộc một Project (model Dataset) → lọc task theo project đang chọn.
  const { data: batches } = useRequest(`batches:${projectId}:${filters.dataset ?? ''}`, () =>
    listBatches(projectId, { dataset: filters.dataset }),
  )

  const { data: members } = useRequest(`members:${projectId}:all`, () => listMembers(projectId))
  const withRole = (role: string) => members?.filter((m) => m.roles.some((r) => r === role)) ?? []
  const canAssign = can('manage_jobs')

  /** Lý do không sửa được người phụ trách (khớp ensure_editable ở backend), null = sửa được. */
  const lockReason = (job: Job) =>
    !canAssign ? 'Bạn không có quyền giao job'
      : job.is_locked ? 'Job đang bị khoá'
        : job.status === 'delivered' ? 'Job đã bàn giao' : null

  /** Giao cho người chưa liên kết CVAT: vẫn giao, nhưng nhắc rằng CVAT sẽ đồng bộ sau. */
  function warnIfUnlinked(userId: number | null) {
    const member = members?.find((m) => m.user.id === userId)
    if (member && !member.cvat_linked) {
      message.warning(`${member.user.full_name} chưa liên kết CVAT — job đã giao trên VanoHub, sẽ đồng bộ sang CVAT khi họ liên kết.`, 6)
    }
  }

  async function assign(job: Job, field: 'annotator' | 'qc1_reviewer', userId: number | null) {
    const label = field === 'annotator' ? 'annotator' : 'người QC1'
    const ok = await run(() => assignJob(projectId, job.id, { [field]: userId }),
      userId ? `Đã đổi ${label} cho ${job.name}` : `Đã bỏ ${label} của ${job.name}`)
    if (ok) {
      warnIfUnlinked(userId)
      reload()
    }
  }

  async function assignQc2(job: Job, userId: number | null) {
    if (!job.qc2 || userId === null) return
    const ok = await run(() => assignSampleAuditor(projectId, job.qc2!.sample_id, userId), `Đã đổi người QC2 cho ${job.name}`)
    if (ok) {
      warnIfUnlinked(userId)
      reload()
    }
  }

  function qc2Cell(job: Job) {
    const qc2 = job.qc2
    if (!qc2) {
      return <Tooltip title="Job chưa được lấy mẫu trong đợt audit QC2 đang mở"><Typography.Text type="secondary">—</Typography.Text></Tooltip>
    }
    const reason = !can('manage_audits') ? 'Bạn không có quyền phân auditor'
      : qc2.result !== 'pending' ? `Mẫu đã có kết quả (${qc2.result === 'pass' ? 'Pass' : 'Reject'})` : null
    return (
      <AssigneeSelect
        value={qc2.auditor}
        options={withRole('qc2')}
        allowClear={false}
        placeholder="Chưa phân"
        disabled={reason !== null}
        disabledReason={reason ?? undefined}
        blockedIds={[job.annotator?.id, job.qc1_reviewer?.id].filter((id): id is number => id != null)}
        onChange={(id) => assignQc2(job, id)}
      />
    )
  }

  const update = (patch: Partial<JobFilters>) => {
    const next = { ...urlFilters, ...patch }
    const params = new URLSearchParams()
    if (next.stage) params.set('stage', next.stage)
    if (next.status) params.set('status', next.status)
    if (next.dataset) params.set('dataset', String(next.dataset))
    if (next.batch) params.set('batch', String(next.batch))
    if (next.assignee) params.set('assignee', String(next.assignee))
    if (next.search?.trim()) params.set('search', next.search.trim())
    if (next.escalated) params.set('escalated', '1')
    if (next.overdue) params.set('overdue', '1')
    if (next.due_soon) params.set('due_soon', '1')
    if (next.unassigned) params.set('unassigned', '1')
    setSearchParams(params, { replace: true })
    setPager((p) => ({ ...p, spKey: params.toString(), page: 1 }))
    setSelected([])
  }
  const reload = () => setVersion((v) => v + 1)
  const assigneeMember = filters.assignee != null ? members?.find((m) => m.user.id === filters.assignee) : undefined

  async function doBulk(action: () => Promise<{ updated: number }>) {
    const result = await run(action)
    if (result) {
      setBulk(null)
      setSelected([])
      reload()
    }
  }

  const columns: TableProps<Job>['columns'] = [
    { title: 'Job', dataIndex: 'name', render: (name: string, job) => <a onClick={() => setOpenJob(job.id)}>{name}</a> },
    { title: 'Project / Task', render: (_, job) => `${job.dataset_name} / ${job.batch_name}` },
    {
      title: 'Trạng thái',
      render: (_, job) => (
        <JobStatusTag status={job.status} escalated={job.is_escalated} locked={job.is_locked} overdue={job.is_overdue} />
      ),
    },
    {
      title: 'Annotator', width: 160,
      render: (_, job) => (
        <AssigneeSelect value={job.annotator} options={withRole('annotator')} disabled={lockReason(job) !== null}
          disabledReason={lockReason(job) ?? undefined} blockedIds={job.qc1_reviewer ? [job.qc1_reviewer.id] : []}
          onChange={(id) => assign(job, 'annotator', id)} />
      ),
    },
    {
      title: 'QC1', width: 160,
      render: (_, job) => (
        <AssigneeSelect value={job.qc1_reviewer} options={withRole('qc1')} disabled={lockReason(job) !== null}
          disabledReason={lockReason(job) ?? undefined} blockedIds={job.annotator ? [job.annotator.id] : []}
          onChange={(id) => assign(job, 'qc1_reviewer', id)} />
      ),
    },
    { title: 'QC2', width: 160, render: (_, job) => qc2Cell(job) },
    {
      title: 'Deadline', dataIndex: 'deadline', sorter: true,
      sortOrder: filters.ordering === 'deadline' ? 'ascend' : filters.ordering === '-deadline' ? 'descend' : null,
      render: (d: string | null) => formatDateTime(d),
    },
    { title: 'Object', dataIndex: 'object_count', align: 'right' },
    {
      title: 'Rework', dataIndex: 'rework_round', sorter: true, align: 'right',
      sortOrder: filters.ordering === 'rework_round' ? 'ascend' : filters.ordering === '-rework_round' ? 'descend' : null,
      render: (r: number, job) => `${r}/${job.max_rework_rounds}`,
    },
    {
      title: '', width: 48,
      render: (_, job) =>
        job.cvat_url && (
          <Tooltip title="Mở trong CVAT">
            <Button type="text" size="small" icon={<ExportOutlined />} href={job.cvat_url} target="_blank" rel="noreferrer" />
          </Tooltip>
        ),
    },
  ]

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Jobs</h1>
          <p>Toàn bộ job trong organization. Bấm tên job để xem chi tiết và thao tác.</p>
        </div>
        <Button icon={<ReloadOutlined />} onClick={reload}>Tải lại</Button>
      </div>

      <Card>
        <Tabs activeKey={filters.stage ?? ''} onChange={(k) => update({ stage: k as Stage | '' })} items={TABS} />
        <Space wrap style={{ marginBottom: 16 }}>
          <Input.Search
            allowClear
            placeholder="Tên job / ID / CVAT job ID"
            style={{ width: 240 }}
            value={searchDraft}
            onChange={(e) => {
              const val = e.target.value
              setSearchDraft(val)
              if (val === '' && filters.search) {
                update({ search: undefined })
              }
            }}
            onSearch={(v) => update({ search: v.trim() || undefined })}
          />
          <Select
            allowClear placeholder="Project" style={{ width: 200 }} value={filters.dataset}
            options={datasets?.map((d) => ({ value: d.id, label: d.name }))}
            onChange={(v) => update({ dataset: v, batch: undefined })}
          />
          <Select
            allowClear placeholder="Task" style={{ width: 200 }} value={filters.batch}
            options={batches?.map((b) => ({ value: b.id, label: b.name }))}
            onChange={(v) => update({ batch: v })}
          />
          <Select
            allowClear placeholder="Trạng thái" style={{ width: 160 }} value={(filters.status || undefined) as JobStatus | undefined}
            options={Object.entries(JOB_STATUS_LABELS).map(([value, label]) => ({ value, label }))}
            onChange={(v?: JobStatus) => update({ status: v })}
          />
          <Checkbox checked={filters.escalated} onChange={(e) => update({ escalated: e.target.checked })}>Escalated</Checkbox>
          <Checkbox checked={filters.overdue} onChange={(e) => update({ overdue: e.target.checked })}>Quá hạn</Checkbox>
          <Checkbox checked={filters.due_soon} onChange={(e) => update({ due_soon: e.target.checked })}>Sắp hạn</Checkbox>
          <Checkbox checked={filters.unassigned} onChange={(e) => update({ unassigned: e.target.checked })}>Chưa giao</Checkbox>
          {filters.assignee != null && (
            <Tag
              closable
              color="blue"
              onClose={(e) => {
                e.preventDefault()
                update({ assignee: undefined })
              }}
            >
              Người phụ trách: {assigneeMember?.user.full_name ?? `#${filters.assignee}`}
            </Tag>
          )}
        </Space>

        {can('manage_jobs') && selected.length > 0 && (
          <Space style={{ marginBottom: 12 }}>
            <span>Đã chọn {selected.length} job</span>
            <Button onClick={() => setBulk('assign')}>Giao lại</Button>
            <Button onClick={() => setBulk('deadline')}>Đặt deadline</Button>
            <Button type="link" onClick={() => setSelected([])}>Bỏ chọn</Button>
          </Space>
        )}

        {error != null ? (
          <StateView kind="error" description={getErrorMessage(error)} action={{ label: 'Thử lại', onClick: retry }} />
        ) : (
          <Table<Job>
            rowKey="id"
            size="middle"
            loading={isLoading}
            columns={columns}
            dataSource={data?.results}
            scroll={{ x: 1100 }}
            rowSelection={can('manage_jobs') ? { selectedRowKeys: selected, onChange: (keys) => setSelected(keys as number[]) } : undefined}
            pagination={{
              current: filters.page, pageSize: filters.page_size, total: data?.count, showSizeChanger: true,
              showTotal: (total) => `${total} job`,
            }}
            onChange={(pagination, _f, sorter) => {
              const s = Array.isArray(sorter) ? sorter[0] : sorter
              const field = s?.field as string | undefined
              setPager({
                spKey,
                page: pagination.current ?? 1,
                page_size: pagination.pageSize ?? 50,
                ordering: s?.order && field ? `${s.order === 'descend' ? '-' : ''}${field}` : undefined,
              })
            }}
          />
        )}
      </Card>

      <JobDetailDrawer jobId={openJob} onClose={() => setOpenJob(null)} onChanged={reload} />
      <AssignModal
        open={bulk === 'assign'}
        projectId={projectId}
        title={`Giao lại ${selected.length} job`}
        confirmLoading={pending}
        onCancel={() => setBulk(null)}
        onSubmit={(values) => doBulk(() => bulkAssign(projectId, selected, values))}
      />
      <DeadlineModal
        open={bulk === 'deadline'}
        title={`Đặt deadline cho ${selected.length} job`}
        confirmLoading={pending}
        onCancel={() => setBulk(null)}
        onSubmit={(deadline, note) => doBulk(() => bulkDeadline(projectId, selected, deadline, note))}
      />
    </div>
  )
}
