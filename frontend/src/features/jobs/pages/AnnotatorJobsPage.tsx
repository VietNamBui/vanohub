import { InfoCircle, SearchLg } from '@untitledui/icons'
import { useState } from 'react'
import { Table } from '@/components/application/table/table'
import { Tabs } from '@/components/application/tabs/tabs'
import { Button } from '@/components/base/buttons/button'
import { Input } from '@/components/base/input/input'
import { getErrorMessage } from '../../../shared/api/errors'
import EmptyRow from '../../../shared/components/ui/EmptyRow'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import { useProject } from '../../projects/projectContext'
import { listAnnotatorJobs, startAnnotatorJob, submitAnnotatorJob } from '../api'
import AnnotatorJobPanel from '../components/AnnotatorJobPanel'
import JobStatusBadge from '../components/JobStatusBadge'
import type { AnnotatorJobTab, Job } from '../types'

const TABS: { id: AnnotatorJobTab; label: string }[] = [
  { id: 'todo', label: 'Cần làm' },
  { id: 'rework', label: 'Rework' },
  { id: 'submitted', label: 'Đã nộp' },
  { id: 'done', label: 'Hoàn tất' },
  { id: 'all', label: 'Tất cả' },
]

/** Danh sách job được giao cho Annotator: bắt đầu làm, mở CVAT, nộp bài sang QC1 và xử lý Rework. */
export default function AnnotatorJobsPage() {
  const { projectId } = useProject()
  const [tab, setTab] = useState<AnnotatorJobTab>('todo')
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [version, setVersion] = useState(0)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const { run } = useAction()

  const jobs = useRequest(`annotator-jobs:${projectId}:${tab}:${query}:${page}:${version}`, () =>
    listAnnotatorJobs(projectId, { tab, search: query || undefined, page }),
  )
  const rows = jobs.data?.results ?? []
  const selected = rows.find((j) => j.id === selectedId) ?? rows[0]
  const reload = () => setVersion((v) => v + 1)
  const reset = (fn: () => void) => {
    fn()
    setPage(1)
    setSelectedId(null)
  }

  async function quickStart(job: Job) {
    if (await run(() => startAnnotatorJob(projectId, job.id), `Đã bắt đầu ${job.name}`)) reload()
  }

  async function quickSubmit(job: Job) {
    if (await run(() => submitAnnotatorJob(projectId, job.id), `Đã nộp ${job.name} sang QC1`)) reload()
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-5 p-4 md:p-6">
      <header>
        <h1 className="text-display-xs font-semibold text-primary">Job của tôi</h1>
        <p className="mt-1 text-sm text-tertiary">Bắt đầu làm, mở CVAT để gán nhãn, sau đó nộp bài sang hàng chờ QC1.</p>
      </header>

      <div className="flex items-start gap-3 rounded-xl bg-brand-primary_alt p-4 ring-1 ring-brand ring-inset">
        <InfoCircle className="mt-0.5 size-5 shrink-0 text-fg-brand-primary" />
        <p className="text-sm text-secondary">
          <span className="font-semibold">Quy trình:</span> Bắt đầu làm → gán nhãn trên CVAT → Nộp bài sang QC1.
          Nếu bị trả Rework, mở chi tiết job để xem danh sách lỗi cần sửa trước khi nộp lại.
        </p>
      </div>

      {jobs.error != null ? (
        <SectionCard><PageState kind="error" description={getErrorMessage(jobs.error)} onRetry={jobs.retry} /></SectionCard>
      ) : (
        <div className="grid items-start gap-5 xl:grid-cols-5">
          <SectionCard className="xl:col-span-3" bodyClassName="p-0">
            <div className="flex flex-wrap items-center gap-3 border-b border-secondary p-4">
              <Tabs selectedKey={tab} onSelectionChange={(k) => reset(() => setTab(k as AnnotatorJobTab))} className="w-auto">
                <Tabs.List type="button-gray" size="sm" aria-label="Lọc trạng thái">
                  {TABS.map((t) => <Tabs.Item key={t.id} id={t.id} label={t.label} />)}
                </Tabs.List>
              </Tabs>
              <form className="min-w-48 flex-1" onSubmit={(e) => { e.preventDefault(); reset(() => setQuery(search.trim())) }}>
                <Input size="sm" icon={SearchLg} aria-label="Tìm kiếm" placeholder="Tìm job, batch… (Enter)" value={search} onChange={setSearch} />
              </form>
            </div>

            <Table
              aria-label="Bảng job của annotator"
              size="sm"
              selectionMode="single"
              selectionBehavior="replace"
              selectedKeys={selected ? [selected.id] : []}
              onSelectionChange={(keys) => keys !== 'all' && keys.size && setSelectedId(Number([...keys][0]))}
            >
              <Table.Header>
                <Table.Head id="job" label="Job" isRowHeader />
                <Table.Head id="status" label="Trạng thái" />
                <Table.Head id="deadline" label="Deadline" />
                <Table.Head id="rework" label="Rework" />
                <Table.Head id="actions" label="Thao tác" />
              </Table.Header>
              <Table.Body items={rows} renderEmptyState={() => (
                <EmptyRow text={jobs.isLoading ? 'Đang tải…' : 'Không có job nào trong mục này'} />
              )}>
                {(job) => {
                  const blocked = job.is_locked || job.is_escalated
                  return (
                    <Table.Row id={job.id} className="cursor-pointer">
                      <Table.Cell>
                        <div className="font-medium text-primary">{job.name}</div>
                        <div className="text-xs text-tertiary">{job.dataset_name} / {job.batch_name}</div>
                      </Table.Cell>
                      <Table.Cell>
                        <JobStatusBadge status={job.status} escalated={job.is_escalated} overdue={job.is_overdue} locked={job.is_locked} />
                      </Table.Cell>
                      <Table.Cell className="whitespace-nowrap">{formatDateTime(job.deadline)}</Table.Cell>
                      <Table.Cell className="tabular-nums">{job.rework_round}/{job.max_rework_rounds}</Table.Cell>
                      <Table.Cell>
                        {!blocked && (job.status === 'pending_annotation' || job.status === 'rework') ? (
                          <Button size="xs" color="secondary" onPress={() => quickStart(job)}>
                            {job.status === 'rework' ? 'Sửa Rework' : 'Bắt đầu'}
                          </Button>
                        ) : !blocked && job.status === 'annotating' ? (
                          <Button size="xs" color="primary" onPress={() => quickSubmit(job)}>Nộp QC1</Button>
                        ) : (
                          <span className="text-quaternary">—</span>
                        )}
                      </Table.Cell>
                    </Table.Row>
                  )
                }}
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
            {selected ? (
              <AnnotatorJobPanel key={selected.id} projectId={projectId} jobId={selected.id} version={version} onDone={reload} />
            ) : (
              <SectionCard><PageState kind="empty" title="Chọn một job" description="Chọn job trong bảng để mở CVAT, xem lỗi và nộp bài." /></SectionCard>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
