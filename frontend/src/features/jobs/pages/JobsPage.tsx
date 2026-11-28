import { LinkExternal01, RefreshCw01, SearchLg, XClose } from '@untitledui/icons'
import { useMemo, useState } from 'react'
import type { Selection, SortDescriptor } from 'react-aria-components'
import { useSearchParams } from 'react-router'
import { Table } from '@/components/application/table/table'
import { Tabs } from '@/components/application/tabs/tabs'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { Checkbox } from '@/components/base/checkbox/checkbox'
import { Input } from '@/components/base/input/input'
import { Select, type SelectItemType } from '@/components/base/select/select'
import { TextArea } from '@/components/base/textarea/textarea'
import { Tooltip, TooltipTrigger } from '@/components/base/tooltip/tooltip'
import { getErrorMessage } from '../../../shared/api/errors'
import StateView from '../../../shared/components/StateView'
import EmptyRow from '../../../shared/components/ui/EmptyRow'
import FormDialog from '../../../shared/components/ui/FormDialog'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useToast } from '../../../shared/hooks/toastContext'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import { listBatches, listDatasets, listMembers } from '../../projects/api'
import { useProject } from '../../projects/projectContext'
import { assignSampleAuditor } from '../../quality/api'
import { assignJob, bulkAssign, bulkDeadline, bulkMoveBatch, listJobs } from '../api'
import AssigneeSelect from '../components/AssigneeSelect'
import AssignModal from '../components/AssignModal'
import DeadlineModal from '../components/DeadlineModal'
import JobDetailDrawer from '../components/JobDetailDrawer'
import JobStatusTag from '../components/JobStatusTag'
import { JOB_STATUS_LABELS } from '../constants'
import {
  getBulkAssignBlockReason,
  getBulkDeadlineBlockReason,
  getBulkMoveBatchBlockReason,
  getJobLockReason,
  getQc2AssignBlockReason,
  nextJobSortOrdering,
  parseJobUrlFilters,
  serializeJobUrlFilters,
} from '../jobHelpers'
import type { Job, JobFilters, Stage } from '../types'

const ALL_KEY = '__all__'
const ALL_STAGE_TAB = 'all'

const TABS: { id: string; label: string }[] = [
  { id: ALL_STAGE_TAB, label: 'Tất cả' },
  { id: 'annotation', label: 'Annotation' },
  { id: 'qc1', label: 'QC1' },
  { id: 'qc2', label: 'QC2' },
  { id: 'done', label: 'Hoàn tất' },
]

const PAGE_SIZE_OPTIONS: SelectItemType[] = [
  { id: '20', label: '20 / trang' },
  { id: '50', label: '50 / trang' },
  { id: '100', label: '100 / trang' },
]

/** Danh sách job dùng chung trong organization, lọc theo stage / project / task / cờ. */
export default function JobsPage() {
  const { projectId, project, can } = useProject()
  const [searchParams, setSearchParams] = useSearchParams()
  const spKey = searchParams.toString()
  const urlFilters = useMemo(() => parseJobUrlFilters(searchParams), [searchParams])
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
  const [bulk, setBulk] = useState<'assign' | 'deadline' | 'move_batch' | null>(null)
  const { run, pending } = useAction()
  const toast = useToast()

  const key = `jobs:${projectId}:${JSON.stringify(filters)}:${version}`
  const { data, error, isLoading, retry } = useRequest(key, () => listJobs(projectId, filters))
  const { data: datasets } = useRequest(`datasets:${projectId}`, () => listDatasets(projectId))
  // Task (model Batch) thuộc một Project (model Dataset) → lọc task theo project đang chọn.
  const { data: batches } = useRequest(`batches:${projectId}:${filters.dataset ?? ''}`, () =>
    listBatches(projectId, { dataset: filters.dataset }),
  )

  const { data: members } = useRequest(`members:${projectId}:all`, () => listMembers(projectId))
  const withRole = (role: string) => members?.filter((m) => m.roles.some((r) => r === role)) ?? []
  const canManage = can('manage_jobs')

  /** Lý do không sửa được người phụ trách (khớp ensure_editable ở backend), null = sửa được. */
  const lockReason = (job: Job) => getJobLockReason(canManage, job)

  /** Giao cho người chưa liên kết CVAT: vẫn giao, nhưng nhắc rằng CVAT sẽ đồng bộ sau. */
  function warnIfUnlinked(userId: number | null) {
    const member = members?.find((m) => m.user.id === userId)
    if (member && !member.cvat_linked) {
      toast.warning(
        `${member.user.full_name} chưa liên kết CVAT — job đã giao trên VanoHub, sẽ đồng bộ sang CVAT khi họ liên kết.`,
        6,
      )
    }
  }

  async function assign(job: Job, field: 'annotator' | 'qc1_reviewer', userId: number | null) {
    const label = field === 'annotator' ? 'annotator' : 'người QC1'
    const ok = await run(
      () => assignJob(projectId, job.id, { [field]: userId }),
      userId ? `Đã đổi ${label} cho ${job.name}` : `Đã bỏ ${label} của ${job.name}`,
    )
    if (ok) {
      warnIfUnlinked(userId)
      reload()
    }
  }

  async function assignQc2(job: Job, userId: number | null) {
    if (!job.qc2 || userId === null) return
    const ok = await run(
      () => assignSampleAuditor(projectId, job.qc2!.sample_id, userId),
      `Đã đổi người QC2 cho ${job.name}`,
    )
    if (ok) {
      warnIfUnlinked(userId)
      reload()
    }
  }

  function qc2Cell(job: Job) {
    const qc2 = job.qc2
    if (!qc2) {
      return (
        <Tooltip title="Job chưa được lấy mẫu trong đợt audit QC2 đang mở">
          <TooltipTrigger className="cursor-default text-sm text-tertiary">
            <span>—</span>
          </TooltipTrigger>
        </Tooltip>
      )
    }
    const reason = getQc2AssignBlockReason(can('manage_audits'), job, project.escalation_policy)
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
    const params = serializeJobUrlFilters({ ...urlFilters, ...patch })
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

  const jobs = useMemo(() => data?.results ?? [], [data])
  const selectedJobs = useMemo(() => {
    const selectedSet = new Set(selected)
    return jobs.filter((j) => selectedSet.has(j.id))
  }, [jobs, selected])
  const bulkAssignReason = getBulkAssignBlockReason(canManage, selectedJobs)
  const bulkDeadlineReason = getBulkDeadlineBlockReason(canManage, selectedJobs)
  const bulkMoveBatchReason = getBulkMoveBatchBlockReason(canManage, selectedJobs)
  const datasetItems: SelectItemType[] = [
    { id: ALL_KEY, label: 'Tất cả project' },
    ...(datasets ?? []).map((d) => ({ id: String(d.id), label: d.name })),
  ]
  const batchItems: SelectItemType[] = [
    { id: ALL_KEY, label: 'Tất cả task' },
    ...(batches ?? []).map((b) => ({ id: String(b.id), label: b.name })),
  ]
  const statusItems: SelectItemType[] = [
    { id: ALL_KEY, label: 'Tất cả trạng thái' },
    ...Object.entries(JOB_STATUS_LABELS).map(([value, label]) => ({ id: value, label })),
  ]

  const sortDescriptor: SortDescriptor | undefined = filters.ordering
    ? {
        column: filters.ordering.startsWith('-') ? filters.ordering.slice(1) : filters.ordering,
        direction: filters.ordering.startsWith('-') ? 'descending' : 'ascending',
      }
    : undefined

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Jobs</h1>
          <p className="mt-1 text-sm text-tertiary">
            Toàn bộ job trong organization. Bấm tên job để xem chi tiết và thao tác.
          </p>
        </div>
        <Button size="sm" color="secondary" iconLeading={RefreshCw01} isLoading={isLoading} onPress={reload}>
          Tải lại
        </Button>
      </header>

      <SectionCard bodyClassName="p-0">
        <div className="border-b border-secondary px-4 pt-3">
          <Tabs
            selectedKey={filters.stage || ALL_STAGE_TAB}
            onSelectionChange={(k) => update({ stage: k === ALL_STAGE_TAB ? '' : (k as Stage) })}
          >
            <Tabs.List type="underline" size="sm" aria-label="Giai đoạn job" className="gap-6">
              {TABS.map((t) => (
                <Tabs.Item key={t.id} id={t.id} label={t.label} />
              ))}
            </Tabs.List>
          </Tabs>
        </div>

        <div className="flex flex-wrap items-center gap-3 border-b border-secondary p-4">
          <form
            className="relative w-60"
            onSubmit={(e) => {
              e.preventDefault()
              update({ search: searchDraft.trim() || undefined })
            }}
          >
            <Input
              size="sm"
              icon={SearchLg}
              inputClassName={searchDraft ? 'pr-8' : undefined}
              aria-label="Tìm kiếm job"
              placeholder="Tên job / ID / CVAT job ID"
              value={searchDraft}
              onChange={(val) => {
                setSearchDraft(val)
                if (val === '' && filters.search) {
                  update({ search: undefined })
                }
              }}
            />
            {searchDraft && (
              <button
                type="button"
                aria-label="Xoá tìm kiếm"
                onClick={() => {
                  setSearchDraft('')
                  if (filters.search) update({ search: undefined })
                }}
                className="absolute top-1/2 right-2 -translate-y-1/2 cursor-pointer rounded p-0.5 text-fg-quaternary transition hover:bg-primary_hover hover:text-fg-secondary"
              >
                <XClose className="size-3.5" aria-hidden="true" />
              </button>
            )}
          </form>

          <Select
            className="w-48"
            size="sm"
            aria-label="Lọc theo project"
            placeholder="Project"
            items={datasetItems}
            selectedKey={filters.dataset != null ? String(filters.dataset) : ALL_KEY}
            onSelectionChange={(v) => {
              const nextDataset = v === ALL_KEY || v == null ? undefined : Number(v)
              update({ dataset: nextDataset, batch: undefined })
            }}
          >
            {(item) => <Select.Item id={item.id} label={item.label} />}
          </Select>

          <Select
            className="w-48"
            size="sm"
            aria-label="Lọc theo task"
            placeholder="Task"
            items={batchItems}
            selectedKey={filters.batch != null ? String(filters.batch) : ALL_KEY}
            onSelectionChange={(v) => {
              const nextBatch = v === ALL_KEY || v == null ? undefined : Number(v)
              update({ batch: nextBatch })
            }}
          >
            {(item) => <Select.Item id={item.id} label={item.label} />}
          </Select>

          <Select
            className="w-44"
            size="sm"
            aria-label="Lọc theo trạng thái"
            placeholder="Trạng thái"
            items={statusItems}
            selectedKey={filters.status || ALL_KEY}
            onSelectionChange={(v) => {
              const nextStatus = v === ALL_KEY || v == null ? undefined : String(v)
              update({ status: nextStatus })
            }}
          >
            {(item) => <Select.Item id={item.id} label={item.label} />}
          </Select>

          <div className="flex flex-wrap items-center gap-4">
            <Checkbox
              size="sm"
              isSelected={Boolean(filters.escalated)}
              onChange={(checked) => update({ escalated: checked })}
              label="Escalated"
            />
            <Checkbox
              size="sm"
              isSelected={Boolean(filters.overdue)}
              onChange={(checked) => update({ overdue: checked })}
              label="Quá hạn"
            />
            <Checkbox
              size="sm"
              isSelected={Boolean(filters.due_soon)}
              onChange={(checked) => update({ due_soon: checked })}
              label="Sắp hạn"
            />
            <Checkbox
              size="sm"
              isSelected={Boolean(filters.unassigned)}
              onChange={(checked) => update({ unassigned: checked })}
              label="Chưa giao"
            />
            <Checkbox
              size="sm"
              isSelected={Boolean(filters.locked)}
              onChange={(checked) => update({ locked: checked })}
              label="Đã khoá"
            />
          </div>

          {filters.assignee != null && (
            <Badge type="pill-color" size="sm" color="blue" className="gap-1 pr-1">
              <span>Người phụ trách: {assigneeMember?.user.full_name ?? `#${filters.assignee}`}</span>
              <Button
                size="xs"
                color="tertiary"
                iconLeading={<XClose className="size-3" aria-hidden="true" />}
                aria-label="Bỏ lọc người phụ trách"
                className="rounded-full p-0.5! text-utility-blue-500 hover:bg-utility-blue-100 hover:text-utility-blue-700"
                onPress={() => update({ assignee: undefined })}
              />
            </Badge>
          )}
          {filters.issue != null && (
            <Badge type="pill-color" size="sm" color="purple" className="gap-1 pr-1">
              <span>Issue #{filters.issue}</span>
              <Button
                size="xs"
                color="tertiary"
                iconLeading={<XClose className="size-3" aria-hidden="true" />}
                aria-label="Bỏ lọc issue"
                className="rounded-full p-0.5! text-utility-purple-500 hover:bg-utility-purple-100 hover:text-utility-purple-700"
                onPress={() => update({ issue: undefined })}
              />
            </Badge>
          )}
        </div>

        {canManage && selected.length > 0 && (
          <div className="flex flex-wrap items-center gap-3 border-b border-secondary bg-brand-primary_alt px-4 py-2.5 text-sm">
            <span className="font-medium text-primary">Đã chọn {selected.length} job</span>
            <Button
              size="xs"
              color="secondary"
              isDisabled={bulkAssignReason !== null}
              onPress={() => setBulk('assign')}
            >
              Giao lại
            </Button>
            <Button
              size="xs"
              color="secondary"
              isDisabled={bulkDeadlineReason !== null}
              onPress={() => setBulk('deadline')}
            >
              Đặt deadline
            </Button>
            <Button
              size="xs"
              color="secondary"
              isDisabled={bulkMoveBatchReason !== null}
              onPress={() => setBulk('move_batch')}
            >
              Chuyển task
            </Button>
            <Button size="xs" color="link-gray" onPress={() => setSelected([])}>
              Bỏ chọn
            </Button>
            {(bulkAssignReason ?? bulkDeadlineReason ?? bulkMoveBatchReason) && (
              <span className="text-xs text-tertiary">
                {[...new Set([bulkAssignReason, bulkDeadlineReason, bulkMoveBatchReason].filter(Boolean))].join(' · ')}
              </span>
            )}
          </div>
        )}

        {error != null ? (
          <StateView kind="error" description={getErrorMessage(error)} action={{ label: 'Thử lại', onClick: retry }} />
        ) : (
          <>
            <Table
              aria-label="Danh sách job"
              size="sm"
              className="min-w-275"
              selectionMode={canManage ? 'multiple' : 'none'}
              selectionBehavior="toggle"
              selectedKeys={canManage ? new Set(selected) : undefined}
              onSelectionChange={(keys: Selection) => {
                if (!canManage) return
                if (keys === 'all') {
                  setSelected(jobs.map((j) => j.id))
                } else {
                  setSelected(Array.from(keys, (k) => Number(k)))
                }
              }}
              sortDescriptor={sortDescriptor}
              onSortChange={(descriptor) => {
                const nextOrdering = nextJobSortOrdering(filters.ordering, descriptor)
                setPager((p) => ({ ...p, spKey, page: 1, ordering: nextOrdering }))
                setSelected([])
              }}
            >
              <Table.Header>
                <Table.Head id="name" label="Job" isRowHeader />
                <Table.Head id="project_task" label="Project / Task" />
                <Table.Head id="status" label="Trạng thái" />
                <Table.Head id="annotator" label="Annotator" className="min-w-44" />
                <Table.Head id="qc1" label="QC1" className="min-w-44" />
                <Table.Head id="qc2" label="QC2" className="min-w-44" />
                <Table.Head id="deadline" label="Deadline" allowsSorting />
                <Table.Head id="object_count" label="Object" className="[&>div]:justify-end" />
                <Table.Head id="rework_round" label="Rework" allowsSorting className="[&>div]:justify-end" />
                <Table.Head id="cvat" className="w-12" />
              </Table.Header>
              <Table.Body
                items={jobs}
                renderEmptyState={() => <EmptyRow text={isLoading ? 'Đang tải…' : 'Không có job phù hợp'} />}
              >
                {(job) => (
                  <Table.Row id={job.id}>
                    <Table.Cell>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          setOpenJob(job.id)
                        }}
                        className="cursor-pointer text-left font-medium text-brand-secondary hover:underline"
                      >
                        {job.name}
                      </button>
                    </Table.Cell>
                    <Table.Cell className="text-secondary">{`${job.dataset_name} / ${job.batch_name}`}</Table.Cell>
                    <Table.Cell>
                      <JobStatusTag
                        status={job.status}
                        escalated={job.is_escalated}
                        locked={job.is_locked}
                        overdue={job.is_overdue}
                        sourceMissing={job.source_missing}
                      />
                    </Table.Cell>
                    <Table.Cell>
                      <AssigneeSelect
                        value={job.annotator}
                        options={withRole('annotator')}
                        disabled={lockReason(job) !== null}
                        disabledReason={lockReason(job) ?? undefined}
                        blockedIds={job.qc1_reviewer ? [job.qc1_reviewer.id] : []}
                        onChange={(id) => assign(job, 'annotator', id)}
                      />
                    </Table.Cell>
                    <Table.Cell>
                      <AssigneeSelect
                        value={job.qc1_reviewer}
                        options={withRole('qc1')}
                        disabled={lockReason(job) !== null}
                        disabledReason={lockReason(job) ?? undefined}
                        blockedIds={job.annotator ? [job.annotator.id] : []}
                        onChange={(id) => assign(job, 'qc1_reviewer', id)}
                      />
                    </Table.Cell>
                    <Table.Cell>{qc2Cell(job)}</Table.Cell>
                    <Table.Cell className="whitespace-nowrap tabular-nums">{formatDateTime(job.deadline)}</Table.Cell>
                    <Table.Cell className="text-right tabular-nums">{job.object_count}</Table.Cell>
                    <Table.Cell className="text-right tabular-nums">{`${job.rework_round}/${job.max_rework_rounds}`}</Table.Cell>
                    <Table.Cell className="text-right">
                      {job.cvat_url && (
                        <div className="inline-flex" onClick={(e) => e.stopPropagation()}>
                          <Tooltip title="Mở trong CVAT">
                            <Button
                              size="xs"
                              color="tertiary"
                              iconLeading={LinkExternal01}
                              href={job.cvat_url}
                              target="_blank"
                              rel="noreferrer"
                              aria-label={`Mở ${job.name} trong CVAT`}
                            />
                          </Tooltip>
                        </div>
                      )}
                    </Table.Cell>
                  </Table.Row>
                )}
              </Table.Body>
            </Table>

            {data && (
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-secondary px-4 py-3 text-sm text-tertiary">
                <div className="flex flex-wrap items-center gap-3">
                  <span className="tabular-nums">{data.count} job</span>
                  <Select
                    size="sm"
                    className="w-32"
                    aria-label="Số dòng mỗi trang"
                    items={PAGE_SIZE_OPTIONS}
                    selectedKey={String(filters.page_size ?? 50)}
                    onSelectionChange={(k) => {
                      if (k == null) return
                      setPager((p) => ({ ...p, spKey, page: 1, page_size: Number(k) }))
                      setSelected([])
                    }}
                  >
                    {(item) => <Select.Item id={item.id} label={item.label} />}
                  </Select>
                </div>
                <div className="flex items-center gap-2">
                  <span className="tabular-nums">Trang {filters.page ?? 1}</span>
                  <Button
                    size="xs"
                    color="secondary"
                    isDisabled={!data.previous}
                    onPress={() => {
                      setPager((p) => ({
                        ...p,
                        spKey,
                        page: Math.max(1, (p.spKey === spKey ? p.page : 1) - 1),
                      }))
                      setSelected([])
                    }}
                  >
                    Trước
                  </Button>
                  <Button
                    size="xs"
                    color="secondary"
                    isDisabled={!data.next}
                    onPress={() => {
                      setPager((p) => ({
                        ...p,
                        spKey,
                        page: (p.spKey === spKey ? p.page : 1) + 1,
                      }))
                      setSelected([])
                    }}
                  >
                    Sau
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </SectionCard>

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
      {bulk === 'move_batch' && (
        <MoveBatchModal
          key={selected.join(',')}
          count={selected.length}
          batches={(batches ?? []).filter((b) => b.status === 'active')}
          confirmLoading={pending}
          onCancel={() => setBulk(null)}
          onSubmit={(batchId, note) => doBulk(() => bulkMoveBatch(projectId, selected, batchId, note))}
        />
      )}
    </div>
  )
}

function MoveBatchModal({
  count,
  batches,
  confirmLoading,
  onCancel,
  onSubmit,
}: {
  count: number
  batches: { id: number; name: string; dataset_name: string }[]
  confirmLoading: boolean
  onCancel: () => void
  onSubmit: (batchId: number, note: string) => void
}) {
  const [targetBatch, setTargetBatch] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [showError, setShowError] = useState(false)

  return (
    <FormDialog
      isOpen
      title={`Chuyển ${count} job sang task khác`}
      description="Chỉ áp dụng cho job chưa gắn CVAT, không bị khoá và không thuộc đợt audit QC2 đang mở."
      submitLabel="Chuyển task"
      onClose={onCancel}
      onSubmit={() => {
        if (!targetBatch) {
          setShowError(true)
          return
        }
        onSubmit(Number(targetBatch), note.trim())
      }}
      pending={confirmLoading}
    >
      <div className="flex flex-col gap-3">
        <Select
          label="Task đích"
          size="sm"
          isRequired
          placeholder="Chọn task đang hoạt động"
          isInvalid={showError && !targetBatch}
          hint={showError && !targetBatch ? 'Vui lòng chọn task đích' : undefined}
          items={batches.map((b) => ({ id: String(b.id), label: b.name, supportingText: b.dataset_name }))}
          selectedKey={targetBatch}
          onSelectionChange={(k) => {
            setTargetBatch(k == null ? null : String(k))
            if (showError) setShowError(false)
          }}
        >
          {(item) => <Select.Item id={item.id} label={item.label} supportingText={item.supportingText} />}
        </Select>
        <TextArea
          label="Ghi chú (tuỳ chọn)"
          rows={2}
          value={note}
          onChange={setNote}
          placeholder="Lý do chuyển task…"
        />
      </div>
    </FormDialog>
  )
}
