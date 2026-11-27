import { Edit05, LinkExternal01, Lock01, LockUnlocked01, SearchLg } from '@untitledui/icons'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { Table } from '@/components/application/table/table'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { Dropdown } from '@/components/base/dropdown/dropdown'
import { Input } from '@/components/base/input/input'
import { ProgressBarBase } from '@/components/base/progress-indicators/progress-indicators'
import { Select } from '@/components/base/select/select'
import { getErrorMessage } from '../../../shared/api/errors'
import EmptyRow from '../../../shared/components/ui/EmptyRow'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import { listTeams } from '../../teams/api'
import { getCvatStatus, listBatches, listDatasets, setBatchLock } from '../api'
import { TaskEditDialog } from '../components/BatchDialogs'
import CvatSyncButton from '../components/CvatSyncButton'
import DataStatusBadge from '../components/DataStatusBadge'
import { useProject } from '../projectContext'
import type { Batch } from '../types'

const ALL = 0

/**
 * Tasks — các CVAT task của organization (model Batch). Task đến từ đồng bộ CVAT.
 * PM đặt deadline (job nhận theo) và team phụ trách (mỗi team một task); bàn giao theo task.
 */
export default function BatchesPage() {
  const { project: org, projectId, can } = useProject()
  const [searchParams, setSearchParams] = useSearchParams()
  const dataset = Number(searchParams.get('dataset')) || ALL
  const [search, setSearch] = useState('')
  const [version, setVersion] = useState(0)
  const [editing, setEditing] = useState<Batch | null>(null)
  const { run } = useAction()
  const { data, error, isLoading, retry } = useRequest(`batches:${projectId}:${dataset}:${version}`, () =>
    listBatches(projectId, { dataset: dataset === ALL ? undefined : dataset }),
  )
  const { data: datasets } = useRequest(`datasets:${projectId}:all`, () => listDatasets(projectId))
  const { data: teams } = useRequest(`teams:${projectId}`, () => listTeams(projectId))
  const { data: cvat } = useRequest('cvat-status', getCvatStatus)
  const reload = () => setVersion((v) => v + 1)
  const canManage = can('manage_data')
  const cvatBase = cvat?.url?.replace(/\/$/, '') ?? ''

  const keyword = search.trim().toLowerCase()
  const rows = (data ?? []).filter((b) => !keyword || [b.name, b.dataset_name, b.team_name ?? ''].some((s) => s.toLowerCase().includes(keyword)))

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Tasks</h1>
          <p className="mt-1 text-sm text-tertiary">
            Task trên CVAT của organization {org.name}. Đặt deadline và team phụ trách cho từng task; bàn giao theo task.
          </p>
        </div>
        {canManage && org.cvat_org_id != null && <CvatSyncButton projectId={projectId} onDone={reload} />}
      </header>

      <SectionCard bodyClassName="p-0">
        <div className="flex flex-wrap items-center gap-3 border-b border-secondary p-4">
          <Select className="w-64" size="sm" aria-label="Lọc theo project"
            items={[{ id: ALL, label: 'Tất cả project' }, ...(datasets ?? []).map((d) => ({ id: d.id, label: d.name }))]}
            selectedKey={dataset}
            onSelectionChange={(k) => {
              const next = Number(k)
              const params = new URLSearchParams(searchParams)
              if (next === ALL) params.delete('dataset')
              else params.set('dataset', String(next))
              setSearchParams(params, { replace: true })
            }}>
            {(item) => <Select.Item id={item.id} label={item.label} />}
          </Select>
          <Input className="min-w-48 flex-1" size="sm" icon={SearchLg} aria-label="Tìm task" placeholder="Tìm task, project hoặc team" value={search} onChange={setSearch} />
        </div>
        {error != null ? (
          <PageState kind="error" description={getErrorMessage(error)} onRetry={retry} />
        ) : (
          <Table aria-label="Danh sách task" size="sm">
            <Table.Header>
              <Table.Head id="name" label="Task" isRowHeader />
              <Table.Head id="jobs" label="Job" />
              <Table.Head id="progress" label="Tiến độ" tooltip="Job đã duyệt hoặc đã bàn giao / tổng số job." />
              <Table.Head id="qc2" label="Chờ QC2" />
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
                return (
                  <Table.Row id={b.id}>
                    <Table.Cell>
                      <Link to={`../jobs?batch=${b.id}`} relative="path" className="font-medium text-primary hover:underline">{b.name}</Link>
                      <div className="text-xs text-tertiary">
                        {b.dataset_name}
                        {b.cvat_task_id && cvatBase && (
                          <a href={`${cvatBase}/tasks/${b.cvat_task_id}`} target="_blank" rel="noreferrer"
                            className="ml-1.5 inline-flex items-center gap-0.5 text-brand-secondary hover:underline">
                            CVAT #{b.cvat_task_id} <LinkExternal01 className="size-3" />
                          </a>
                        )}
                      </div>
                    </Table.Cell>
                    <Table.Cell className="tabular-nums">{b.job_count}</Table.Cell>
                    <Table.Cell>
                      <div className="flex w-36 items-center gap-3">
                        <ProgressBarBase value={percent} />
                        <span className="w-12 text-right text-xs text-tertiary tabular-nums">{b.done_count}/{b.job_count}</span>
                      </div>
                    </Table.Cell>
                    <Table.Cell className="tabular-nums">{b.pending_qc2_count}</Table.Cell>
                    <Table.Cell>{b.escalated_count ? <Badge type="pill-color" size="sm" color="error">{b.escalated_count}</Badge> : <span className="text-quaternary">0</span>}</Table.Cell>
                    <Table.Cell className="whitespace-nowrap">{formatDateTime(b.deadline)}</Table.Cell>
                    <Table.Cell>{b.team_name ?? <span className="text-quaternary">Chưa giao</span>}</Table.Cell>
                    <Table.Cell><DataStatusBadge status={b.status} /></Table.Cell>
                    <Table.Cell className="text-right">
                      {canManage && b.status !== 'delivered' && (
                        <div className="flex items-center justify-end gap-1">
                          {editable && (
                            <Button size="sm" color="link-color" iconLeading={Edit05} onPress={() => setEditing(b)}>Deadline / team</Button>
                          )}
                          <Dropdown.Root>
                            <Dropdown.DotsButton />
                            <Dropdown.Popover className="w-44">
                              <Dropdown.Menu aria-label={`Thao tác ${b.name}`}>
                                <Dropdown.Item icon={b.status === 'active' ? Lock01 : LockUnlocked01}
                                  label={b.status === 'active' ? 'Khoá task' : 'Mở khoá task'}
                                  onAction={async () => (await run(() => setBatchLock(projectId, b.id, b.status === 'active'), 'Đã cập nhật')) && reload()} />
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
        <TaskEditDialog projectId={projectId} teams={teams ?? []} task={editing}
          onClose={() => setEditing(null)} onDone={() => { setEditing(null); reload() }} />
      )}
    </div>
  )
}
