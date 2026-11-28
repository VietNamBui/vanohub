import { AlertTriangle, CheckCircle, Edit05, LinkExternal01, Lock01, LockUnlocked01, SearchLg } from '@untitledui/icons'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { Table } from '@/components/application/table/table'
import { Tabs } from '@/components/application/tabs/tabs'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { Dropdown } from '@/components/base/dropdown/dropdown'
import { Input } from '@/components/base/input/input'
import { ProgressBarBase } from '@/components/base/progress-indicators/progress-indicators'
import { Select } from '@/components/base/select/select'
import { TextArea } from '@/components/base/textarea/textarea'
import { getErrorMessage } from '../../../shared/api/errors'
import EmptyRow from '../../../shared/components/ui/EmptyRow'
import FormDialog from '../../../shared/components/ui/FormDialog'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { cvatTaskUrl } from '../../../shared/utils/cvat'
import { formatDateTime } from '../../../shared/utils/format'
import { listTeams } from '../../teams/api'
import { confirmBatchQc2, getCvatStatus, listBatches, listDatasets, setBatchLock } from '../api'
import { TaskEditDialog } from '../components/BatchDialogs'
import CvatSyncButton from '../components/CvatSyncButton'
import DataStatusBadge from '../components/DataStatusBadge'
import { useProject } from '../projectContext'
import type { Batch } from '../types'

const ALL = 0
const STATUS_TABS = [
  { id: '', label: 'Tất cả' },
  { id: 'active', label: 'Đang xử lý' },
  { id: 'locked', label: 'Đã khoá' },
  { id: 'delivered', label: 'Đã bàn giao' },
]

/**
 * Tasks — các CVAT task của organization (model Batch). Task đến từ đồng bộ CVAT.
 * PM đặt deadline (job nhận theo) và team phụ trách (mỗi team một task); xác nhận chuyển QC2 và bàn giao theo task.
 */
export default function BatchesPage() {
  const { project: org, projectId, can } = useProject()
  const [searchParams, setSearchParams] = useSearchParams()
  const dataset = Number(searchParams.get('dataset')) || ALL
  const status = searchParams.get('status') ?? ''
  const [search, setSearch] = useState('')
  const [version, setVersion] = useState(0)
  const [editing, setEditing] = useState<Batch | null>(null)
  const [confirmingQc2, setConfirmingQc2] = useState<Batch | null>(null)
  const [locking, setLocking] = useState<Batch | null>(null)
  const { data, error, isLoading, retry } = useRequest(`batches:${projectId}:${dataset}:${status}:${version}`, () =>
    listBatches(projectId, { dataset: dataset === ALL ? undefined : dataset, status: status || undefined }),
  )
  const { data: datasets } = useRequest(`datasets:${projectId}:all`, () => listDatasets(projectId))
  const { data: teams } = useRequest(`teams:${projectId}`, () => listTeams(projectId))
  const { data: cvat, retry: retryCvat } = useRequest('cvat-status', getCvatStatus)
  const reload = () => setVersion((v) => v + 1)
  const canManage = can('manage_data')
  const linked = org.cvat_org_id != null
  const cvatBase = cvat?.url?.replace(/\/$/, '') ?? ''
  const cvatDisconnected = cvat?.connected === false

  const keyword = search.trim().toLowerCase()
  const rows = (data ?? []).filter((b) => !keyword || [b.name, b.dataset_name, b.team_name ?? ''].some((s) => s.toLowerCase().includes(keyword)))

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Tasks</h1>
          <p className="mt-1 text-sm text-tertiary">
            Task trên CVAT của organization {org.name}. Đặt deadline, team phụ trách và xác nhận chuyển QC2 cho từng task.
          </p>
        </div>
        {canManage && linked && <CvatSyncButton projectId={projectId} onDone={reload} disabled={cvatDisconnected} />}
      </header>

      {linked && cvatDisconnected && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-warning-primary px-4 py-3 text-sm text-warning-primary ring-1 ring-utility-yellow-200 ring-inset"
        >
          <div className="flex items-start gap-2.5">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-fg-warning-primary" aria-hidden="true" />
            <span>{cvat?.detail || 'Không kết nối được tới máy chủ CVAT.'}</span>
          </div>
          <Button size="xs" color="secondary" onPress={retryCvat}>
            Kiểm tra lại
          </Button>
        </div>
      )}

      <SectionCard bodyClassName="p-0">
        <div className="flex flex-wrap items-center gap-3 border-b border-secondary p-4">
          <Tabs
            selectedKey={status}
            onSelectionChange={(k) => {
              const next = String(k)
              const params = new URLSearchParams(searchParams)
              if (!next) params.delete('status')
              else params.set('status', next)
              setSearchParams(params, { replace: true })
            }}
            className="w-auto"
          >
            <Tabs.List type="button-gray" size="sm" aria-label="Lọc theo trạng thái">
              {STATUS_TABS.map((t) => (
                <Tabs.Item key={t.id} id={t.id} label={t.label} />
              ))}
            </Tabs.List>
          </Tabs>
          <Select
            className="w-64"
            size="sm"
            aria-label="Lọc theo project"
            items={[{ id: ALL, label: 'Tất cả project' }, ...(datasets ?? []).map((d) => ({ id: d.id, label: d.name }))]}
            selectedKey={dataset}
            onSelectionChange={(k) => {
              const next = Number(k)
              const params = new URLSearchParams(searchParams)
              if (next === ALL) params.delete('dataset')
              else params.set('dataset', String(next))
              setSearchParams(params, { replace: true })
            }}
          >
            {(item) => <Select.Item id={item.id} label={item.label} />}
          </Select>
          <Input
            className="min-w-48 flex-1"
            size="sm"
            icon={SearchLg}
            aria-label="Tìm task"
            placeholder="Tìm task, project hoặc team"
            value={search}
            onChange={setSearch}
          />
        </div>
        {error != null ? (
          <PageState kind="error" description={getErrorMessage(error)} onRetry={retry} />
        ) : (
          <Table aria-label="Danh sách task" size="sm">
            <Table.Header>
              <Table.Head id="name" label="Task" isRowHeader />
              <Table.Head id="jobs" label="Job" />
              <Table.Head id="progress" label="Tiến độ" tooltip="Job đã duyệt hoặc đã bàn giao / tổng số job." />
              <Table.Head id="qc2" label="QC1 / QC2" tooltip="Trạng thái đạt QC1, xác nhận chuyển QC2 và số job đang chờ QC2." />
              <Table.Head id="escalated" label="Escalated" />
              <Table.Head id="deadline" label="Deadline" />
              <Table.Head id="team" label="Team phụ trách" />
              <Table.Head id="status" label="Trạng thái" />
              <Table.Head id="actions" />
            </Table.Header>
            <Table.Body items={rows} renderEmptyState={() => <EmptyRow text={isLoading ? 'Đang tải…' : 'Chưa có task — bấm "Đồng bộ CVAT".'} />}>
              {(b) => {
                const percent = b.job_count ? Math.round((b.done_count * 100) / b.job_count) : 0
                const editable = canManage && b.status === 'active'
                const qc1PassedCount = b.qc1_passed_count ?? 0
                const taskHref = b.cvat_task_id ? cvatTaskUrl(cvatBase, b.cvat_task_id, org.cvat_org_slug) : ''
                const hasSyncError = b.last_sync_status === 'error' || Boolean(b.last_sync_error)
                return (
                  <Table.Row id={b.id}>
                    <Table.Cell>
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Link to={`../jobs?batch=${b.id}`} relative="path" className="font-medium text-primary hover:underline">
                          {b.name}
                        </Link>
                        {b.source_missing && (
                          <Badge type="pill-color" size="sm" color="warning">
                            Thiếu nguồn CVAT
                          </Badge>
                        )}
                        {hasSyncError && (
                          <Badge type="pill-color" size="sm" color="error">
                            Lỗi đồng bộ
                          </Badge>
                        )}
                      </div>
                      <div className="text-xs text-tertiary">
                        {b.dataset_name}
                        {b.cvat_task_id && taskHref && (
                          <a
                            href={taskHref}
                            target="_blank"
                            rel="noreferrer"
                            className="ml-1.5 inline-flex items-center gap-0.5 text-brand-secondary hover:underline"
                          >
                            CVAT #{b.cvat_task_id} <LinkExternal01 className="size-3" />
                          </a>
                        )}
                        {b.cvat_task_id && !taskHref && (
                          <span className="ml-1.5 text-quaternary">CVAT #{b.cvat_task_id}</span>
                        )}
                        {b.last_synced_at && !hasSyncError && (
                          <span className="ml-2 text-quaternary">· Đồng bộ {formatDateTime(b.last_synced_at)}</span>
                        )}
                      </div>
                      {hasSyncError && b.last_sync_error && (
                        <p className="mt-1 max-w-md text-xs text-error-primary">{b.last_sync_error}</p>
                      )}
                    </Table.Cell>
                    <Table.Cell className="tabular-nums">{b.job_count}</Table.Cell>
                    <Table.Cell>
                      <div className="flex w-36 items-center gap-3">
                        <ProgressBarBase value={percent} />
                        <span className="w-12 text-right text-xs text-tertiary tabular-nums">{b.done_count}/{b.job_count}</span>
                      </div>
                    </Table.Cell>
                    <Table.Cell>
                      <div className="flex flex-col items-start gap-1">
                        <span className="text-xs text-tertiary tabular-nums">
                          Chờ QC2: <span className="font-medium text-secondary">{b.pending_qc2_count}</span>
                        </span>
                        {b.qc2_confirmed_at ? (
                          <span title={`Xác nhận lúc ${formatDateTime(b.qc2_confirmed_at)}`}>
                            <Badge type="pill-color" size="sm" color="success">
                              Đã xác nhận QC2
                            </Badge>
                          </span>
                        ) : qc1PassedCount > 0 ? (
                          <Badge type="pill-color" size="sm" color={b.ready_for_qc2_confirm ? 'brand' : 'gray'}>
                            Đạt QC1: {qc1PassedCount}/{b.job_count}
                          </Badge>
                        ) : null}
                      </div>
                    </Table.Cell>
                    <Table.Cell>
                      {b.escalated_count ? (
                        <Badge type="pill-color" size="sm" color="error">{b.escalated_count}</Badge>
                      ) : (
                        <span className="text-quaternary">0</span>
                      )}
                    </Table.Cell>
                    <Table.Cell className="whitespace-nowrap">{formatDateTime(b.deadline)}</Table.Cell>
                    <Table.Cell>{b.team_name ?? <span className="text-quaternary">Chưa giao</span>}</Table.Cell>
                    <Table.Cell><DataStatusBadge status={b.status} /></Table.Cell>
                    <Table.Cell className="text-right">
                      {canManage && b.status !== 'delivered' && (
                        <div className="flex items-center justify-end gap-1.5">
                          {b.ready_for_qc2_confirm && (
                            <Button
                              size="xs"
                              color="primary"
                              iconLeading={CheckCircle}
                              onPress={() => setConfirmingQc2(b)}
                            >
                              Xác nhận QC2
                            </Button>
                          )}
                          {editable && (
                            <Button size="sm" color="link-color" iconLeading={Edit05} onPress={() => setEditing(b)}>
                              Deadline / team
                            </Button>
                          )}
                          <Dropdown.Root>
                            <Dropdown.DotsButton />
                            <Dropdown.Popover className="w-44">
                              <Dropdown.Menu aria-label={`Thao tác ${b.name}`}>
                                <Dropdown.Item
                                  icon={b.status === 'active' ? Lock01 : LockUnlocked01}
                                  label={b.status === 'active' ? 'Khoá task' : 'Mở khoá task'}
                                  onAction={() => setLocking(b)}
                                />
                              </Dropdown.Menu>
                            </Dropdown.Popover>
                          </Dropdown.Root>
                        </div>
                      )}
                    </Table.Cell>
                  </Table.Row>
                )
              }}
            </Table.Body>
          </Table>
        )}
      </SectionCard>

      {editing && (
        <TaskEditDialog
          key={editing.id}
          projectId={projectId}
          teams={teams ?? []}
          task={editing}
          onClose={() => setEditing(null)}
          onDone={() => {
            setEditing(null)
            reload()
          }}
        />
      )}

      {confirmingQc2 && (
        <ConfirmQc2Dialog
          key={confirmingQc2.id}
          projectId={projectId}
          task={confirmingQc2}
          onClose={() => setConfirmingQc2(null)}
          onDone={() => {
            setConfirmingQc2(null)
            reload()
          }}
        />
      )}

      {locking && (
        <BatchLockDialog
          key={`${locking.id}:${locking.status}`}
          projectId={projectId}
          task={locking}
          onClose={() => setLocking(null)}
          onDone={() => {
            setLocking(null)
            reload()
          }}
        />
      )}
    </div>
  )
}

function BatchLockDialog({
  projectId,
  task,
  onClose,
  onDone,
}: {
  projectId: number
  task: Batch
  onClose: () => void
  onDone: () => void
}) {
  const [note, setNote] = useState('')
  const { run, pending } = useAction()
  const willLock = task.status === 'active'

  async function submit() {
    if (
      await run(
        () => setBatchLock(projectId, task.id, willLock, note.trim() || undefined),
        willLock ? `Đã khoá task ${task.name}` : `Đã mở khoá task ${task.name}`,
      )
    ) {
      onDone()
    }
  }

  return (
    <FormDialog
      isOpen
      title={willLock ? `Khoá task ${task.name}` : `Mở khoá task ${task.name}`}
      description={
        willLock
          ? 'Khi khoá task, mọi thay đổi trên task và các job bên trong sẽ bị tạm dừng.'
          : 'Mở khoá task để tiếp tục gán nhãn, kiểm duyệt và cập nhật deadline.'
      }
      submitLabel={willLock ? 'Khoá task' : 'Mở khoá task'}
      onClose={onClose}
      onSubmit={submit}
      pending={pending}
    >
      <TextArea
        label="Ghi chú / lý do (tuỳ chọn)"
        rows={3}
        value={note}
        onChange={setNote}
        placeholder={willLock ? 'Lý do tạm khoá task…' : 'Ghi chú khi mở khoá task…'}
      />
    </FormDialog>
  )
}

function ConfirmQc2Dialog({
  projectId,
  task,
  onClose,
  onDone,
}: {
  projectId: number
  task: Batch
  onClose: () => void
  onDone: () => void
}) {
  const [note, setNote] = useState('')
  const { run, pending } = useAction()
  const count = task.qc1_passed_count ?? task.job_count

  async function submit() {
    if (
      await run(
        () => confirmBatchQc2(projectId, task.id, note.trim()),
        `Đã xác nhận chuyển ${task.name} sang QC2`,
      )
    ) {
      onDone()
    }
  }

  return (
    <FormDialog
      isOpen
      title={`Xác nhận QC2 cho ${task.name}`}
      description={`${task.dataset_name} · ${count} job đạt QC1 sẽ chuyển sang trạng thái Chờ QC2 để kiểm tra.`}
      submitLabel="Xác nhận QC2"
      onClose={onClose}
      onSubmit={submit}
      pending={pending}
    >
      <TextArea
        label="Ghi chú (tuỳ chọn)"
        rows={3}
        value={note}
        onChange={setNote}
        placeholder="Ghi chú cho đội ngũ QC2…"
      />
    </FormDialog>
  )
}
