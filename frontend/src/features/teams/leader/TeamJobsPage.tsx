import { Calendar, SearchLg, UserRight01 } from '@untitledui/icons'
import { useState } from 'react'
import type { Selection } from 'react-aria-components'
import { Table } from '@/components/application/table/table'
import { Tabs } from '@/components/application/tabs/tabs'
import { Button } from '@/components/base/buttons/button'
import { Input } from '@/components/base/input/input'
import { getErrorMessage } from '../../../shared/api/errors'
import EmptyRow from '../../../shared/components/ui/EmptyRow'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import JobStatusBadge from '../../jobs/components/JobStatusBadge'
import { useProject } from '../../projects/projectContext'
import { listLeaderJobs, listLeaderTeams } from './api'
import LeaderJobDetail from './LeaderJobDetail'
import LeaderJobDialogs, { type LeaderDialogState } from './LeaderJobDialogs'
import NoTeamNotice from './NoTeamNotice'
import TeamPicker from './TeamPicker'
import type { LeaderJobTab } from './types'

const TABS: { id: LeaderJobTab; label: string }[] = [
  { id: 'all', label: 'Tất cả' },
  { id: 'doing', label: 'Đang làm' },
  { id: 'qc', label: 'Chờ QC' },
  { id: 'escalated', label: 'Escalated' },
]

/** TL-02 Danh sách job của team: lọc, giao lại / đặt deadline (lẻ hoặc hàng loạt), xem chi tiết. */
export default function TeamJobsPage() {
  const { projectId } = useProject()
  const [tab, setTab] = useState<LeaderJobTab>('all')
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [team, setTeam] = useState<number | null>(null)
  const [page, setPage] = useState(1)
  const [version, setVersion] = useState(0)
  const [selected, setSelected] = useState<Selection>(new Set())
  const [openJob, setOpenJob] = useState<number | null>(null)
  const [dialog, setDialog] = useState<LeaderDialogState>(null)

  const teams = useRequest(`leader-teams:${projectId}:${version}`, () => listLeaderTeams(projectId))
  const jobs = useRequest(`leader-jobs:${projectId}:${tab}:${query}:${team ?? ''}:${page}:${version}`, () =>
    listLeaderJobs(projectId, { tab, search: query || undefined, team: team ?? undefined, page }),
  )
  const members = (teams.data ?? []).filter((t) => team == null || t.id === team).flatMap((t) => t.members)
  const rows = jobs.data?.results ?? []
  const selectedIds = selected === 'all' ? rows.map((j) => j.id) : [...selected].map(Number)
  const reset = (fn: () => void) => { fn(); setPage(1); setSelected(new Set()) }

  if (teams.data && teams.data.length === 0) {
    return <div className="mx-auto max-w-6xl p-4 md:p-6"><NoTeamNotice /></div>
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Danh sách job</h1>
          <p className="mt-1 text-sm text-tertiary">Job thuộc batch được giao cho team, hoặc đang do thành viên team làm.</p>
        </div>
        {teams.data && <TeamPicker teams={teams.data} value={team} onChange={(t) => reset(() => setTeam(t))} />}
      </header>

      {jobs.error != null ? (
        <SectionCard><PageState kind="error" description={getErrorMessage(jobs.error)} onRetry={jobs.retry} /></SectionCard>
      ) : (
        <div className="grid items-start gap-5 xl:grid-cols-5">
          <SectionCard className="xl:col-span-3" bodyClassName="p-0">
            <div className="flex flex-wrap items-center gap-3 border-b border-secondary p-4">
              <Tabs selectedKey={tab} onSelectionChange={(k) => reset(() => setTab(k as LeaderJobTab))} className="w-auto">
                <Tabs.List type="button-gray" size="sm" aria-label="Lọc job">
                  {TABS.map((t) => <Tabs.Item key={t.id} id={t.id} label={t.label} />)}
                </Tabs.List>
              </Tabs>
              <form className="min-w-48 flex-1" onSubmit={(e) => { e.preventDefault(); reset(() => setQuery(search.trim())) }}>
                <Input size="sm" icon={SearchLg} aria-label="Tìm kiếm" placeholder="Tìm job, batch, người làm… (Enter)" value={search} onChange={setSearch} />
              </form>
            </div>

            {selectedIds.length > 0 && (
              <div className="flex flex-wrap items-center gap-3 border-b border-secondary bg-brand-primary_alt px-4 py-2.5">
                <span className="text-sm font-medium text-secondary">Đã chọn {selectedIds.length} job</span>
                <Button size="xs" iconLeading={UserRight01} onPress={() => setDialog({ type: 'assign', jobIds: selectedIds, label: `${selectedIds.length} job đã chọn` })}>Giao lại</Button>
                <Button size="xs" color="secondary" iconLeading={Calendar} onPress={() => setDialog({ type: 'deadline', jobIds: selectedIds, label: `${selectedIds.length} job đã chọn` })}>Đặt deadline</Button>
                <Button size="xs" color="link-gray" onPress={() => setSelected(new Set())}>Bỏ chọn</Button>
              </div>
            )}

            <Table
              aria-label="Bảng job của team"
              size="sm"
              selectionMode="multiple"
              selectionBehavior="toggle"
              selectedKeys={selected}
              onSelectionChange={setSelected}
              onRowAction={(key) => setOpenJob(Number(key))}
            >
              <Table.Header>
                <Table.Head id="job" label="Job" isRowHeader />
                <Table.Head id="annotator" label="Người làm" />
                <Table.Head id="qc1" label="QC1" />
                <Table.Head id="status" label="Trạng thái" />
                <Table.Head id="deadline" label="Deadline" />
                <Table.Head id="rework" label="Rework" />
              </Table.Header>
              <Table.Body items={rows} renderEmptyState={() => <EmptyRow text={jobs.isLoading ? 'Đang tải…' : 'Không có job nào'} />}>
                {(job) => (
                  <Table.Row id={job.id} className={openJob === job.id ? 'cursor-pointer bg-secondary' : 'cursor-pointer'}>
                    <Table.Cell>
                      <div className="font-medium text-primary">{job.name}</div>
                      <div className="text-xs text-tertiary">{job.dataset_name} / {job.batch_name}</div>
                    </Table.Cell>
                    <Table.Cell>{job.annotator?.full_name ?? <span className="text-quaternary">Chưa giao</span>}</Table.Cell>
                    <Table.Cell>{job.qc1_reviewer?.full_name ?? '—'}</Table.Cell>
                    <Table.Cell><JobStatusBadge status={job.status} escalated={job.is_escalated} overdue={job.is_overdue} locked={job.is_locked} /></Table.Cell>
                    <Table.Cell className="whitespace-nowrap">{formatDateTime(job.deadline)}</Table.Cell>
                    <Table.Cell className="tabular-nums">{job.rework_round}/{job.max_rework_rounds}</Table.Cell>
                  </Table.Row>
                )}
              </Table.Body>
            </Table>

            {jobs.data && jobs.data.count > rows.length && (
              <div className="flex items-center justify-between border-t border-secondary px-4 py-3 text-sm text-tertiary">
                <span>Trang {page} · {jobs.data.count} job</span>
                <div className="flex gap-2">
                  <Button size="xs" color="secondary" isDisabled={!jobs.data.previous} onPress={() => setPage((p) => p - 1)}>Trước</Button>
                  <Button size="xs" color="secondary" isDisabled={!jobs.data.next} onPress={() => setPage((p) => p + 1)}>Sau</Button>
                </div>
              </div>
            )}
          </SectionCard>

          <div className="xl:sticky xl:top-20 xl:col-span-2">
            {openJob ? (
              <LeaderJobDetail key={openJob} projectId={projectId} jobId={openJob} version={version} openDialog={setDialog} />
            ) : (
              <SectionCard><PageState kind="empty" title="Chọn một job" description="Bấm vào một dòng để xem thông tin, dòng thời gian và lỗi đã ghi." /></SectionCard>
            )}
          </div>
        </div>
      )}

      <LeaderJobDialogs
        state={dialog}
        projectId={projectId}
        members={members}
        onClose={() => setDialog(null)}
        onDone={() => { setDialog(null); setSelected(new Set()); setVersion((v) => v + 1) }}
      />
    </div>
  )
}
