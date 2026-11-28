import { InfoCircle, SearchLg } from '@untitledui/icons'
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { Table } from '@/components/application/table/table'
import { Tabs } from '@/components/application/tabs/tabs'
import { Badge, BadgeWithButton } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { Input } from '@/components/base/input/input'
import { getErrorMessage } from '../../../shared/api/errors'
import EmptyRow from '../../../shared/components/ui/EmptyRow'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime, formatNumber } from '../../../shared/utils/format'
import JobStatusBadge from '../../jobs/components/JobStatusBadge'
import { formatDeadlineCountdown } from '../../jobs/constants'
import { isJobEscalationBlocked, isJobEscalationWarnOnly, parsePositiveInt } from '../../jobs/jobHelpers'
import type { Job } from '../../jobs/types'
import { useProject } from '../../projects/projectContext'
import { listQc1Jobs, passQc1Job, startQc1Job } from '../api'
import type { Qc1JobTab, Qc1Scope } from '../types'
import Qc1ReviewPanel from './Qc1ReviewPanel'

const SCOPES: { id: Qc1Scope; label: string }[] = [
  { id: 'mine', label: 'Được giao cho tôi' },
  { id: 'pool', label: 'Pool chưa nhận' },
  { id: 'all', label: 'Tất cả' },
]

const TABS: { id: Qc1JobTab; label: string }[] = [
  { id: 'queue', label: 'Chờ QC1' },
  { id: 'reviewing', label: 'Đang kiểm tra' },
  { id: 'done', label: 'Đã xử lý' },
  { id: 'all', label: 'Tất cả' },
]

/** Hàng chờ & kiểm tra Level 1 QC: ưu tiên theo hạn (DB06), nhận từ pool hoặc danh sách giao, duyệt Đạt QC1 hoặc Reject. */
export default function Qc1WorkPage() {
  const { projectId, project } = useProject()
  const [searchParams, setSearchParams] = useSearchParams()
  const overdueOnly = searchParams.get('overdue') === '1'
  const dueSoonOnly = searchParams.get('due_soon') === '1'
  const deepLinkedJobId = parsePositiveInt(searchParams.get('job')) ?? null
  const [scope, setScope] = useState<Qc1Scope>('all')
  const [tab, setTab] = useState<Qc1JobTab>(overdueOnly || dueSoonOnly || deepLinkedJobId != null ? 'all' : 'queue')
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [version, setVersion] = useState(0)
  const [selectedId, setSelectedId] = useState<number | null>(deepLinkedJobId)
  const { run, pending } = useAction()

  const jobs = useRequest(
    `qc1-jobs:${projectId}:${scope}:${tab}:${query}:${overdueOnly ? 1 : 0}:${dueSoonOnly ? 1 : 0}:${page}:${version}`,
    () =>
      listQc1Jobs(projectId, {
        scope,
        tab,
        search: query || undefined,
        overdue: overdueOnly || undefined,
        due_soon: dueSoonOnly || undefined,
        page,
      }),
  )
  const rows = jobs.data?.results ?? []
  const selected = rows.find((j) => j.id === selectedId) ?? rows[0]
  const activePanelJobId = selected?.id ?? (selectedId != null && selectedId === deepLinkedJobId ? selectedId : null)
  const reload = () => setVersion((v) => v + 1)
  const reset = (fn: () => void) => {
    fn()
    setPage(1)
    setSelectedId(null)
  }

  function toggleParam(key: 'overdue' | 'due_soon') {
    const next = new URLSearchParams(searchParams)
    if (next.get(key) === '1') {
      next.delete(key)
    } else {
      next.set(key, '1')
      if (key === 'overdue') next.delete('due_soon')
      if (key === 'due_soon') next.delete('overdue')
    }
    setSearchParams(next, { replace: true })
    setPage(1)
    setSelectedId(null)
  }

  async function quickStart(job: Job) {
    if (await run(() => startQc1Job(projectId, job.id), `Đã nhận kiểm tra ${job.name}`)) reload()
  }

  async function quickPass(job: Job) {
    const updated = await run(() => passQc1Job(projectId, job.id), `Đã duyệt đạt QC1 cho ${job.name}`)
    if (updated) reload()
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Job kiểm tra QC1</h1>
          <p className="mt-1 text-sm text-tertiary">
            Hàng chờ sắp theo ưu tiên hạn (quá hạn → sắp hạn → rework). Mở job trên CVAT để kiểm tra, duyệt Đạt QC1 hoặc Reject kèm lỗi có cấu trúc.
          </p>
        </div>
        <Tabs selectedKey={scope} onSelectionChange={(k) => reset(() => setScope(k as Qc1Scope))} className="w-auto">
          <Tabs.List type="button-border" size="sm" aria-label="Phạm vi">
            {SCOPES.map((s) => (
              <Tabs.Item key={s.id} id={s.id} label={s.label} />
            ))}
          </Tabs.List>
        </Tabs>
      </header>

      <div className="flex items-start gap-3 rounded-xl bg-brand-primary_alt p-4 ring-1 ring-brand ring-inset">
        <InfoCircle className="mt-0.5 size-5 shrink-0 text-fg-brand-primary" />
        <p className="text-sm text-secondary">
          <span className="font-semibold">Luật bốn mắt:</span> hệ thống tự ẩn các job do chính bạn annotate hoặc đã audit QC2.
          Reject bắt buộc ghi ít nhất 1 lỗi; vượt quá số vòng rework tối đa job sẽ tự chuyển sang Escalated.
        </p>
      </div>

      {jobs.error != null ? (
        <SectionCard>
          <PageState kind="error" description={getErrorMessage(jobs.error)} onRetry={jobs.retry} />
        </SectionCard>
      ) : (
        <div className="grid items-start gap-5 xl:grid-cols-5">
          <SectionCard className="xl:col-span-3" bodyClassName="p-0">
            <div className="flex flex-wrap items-center gap-3 border-b border-secondary p-4">
              <Tabs selectedKey={tab} onSelectionChange={(k) => reset(() => setTab(k as Qc1JobTab))} className="w-auto">
                <Tabs.List type="button-gray" size="sm" aria-label="Trạng thái">
                  {TABS.map((t) => (
                    <Tabs.Item key={t.id} id={t.id} label={t.label} />
                  ))}
                </Tabs.List>
              </Tabs>
              <form
                className="flex min-w-48 flex-1 items-center gap-2"
                onSubmit={(e) => {
                  e.preventDefault()
                  reset(() => setQuery(search.trim()))
                }}
              >
                <Input
                  name="qc1_search"
                  size="sm"
                  icon={SearchLg}
                  aria-label="Tìm kiếm"
                  placeholder="Tìm job, task, annotator… (Enter)"
                  value={search}
                  onChange={setSearch}
                />
                {(search || query) && (
                  <Button
                    size="sm"
                    color="tertiary"
                    onPress={() =>
                      reset(() => {
                        setSearch('')
                        setQuery('')
                      })
                    }
                  >
                    Xoá
                  </Button>
                )}
              </form>
              <div className="flex flex-wrap items-center gap-1.5">
                {overdueOnly ? (
                  <BadgeWithButton
                    size="sm"
                    type="pill-color"
                    color="error"
                    buttonLabel="Bỏ lọc quá hạn"
                    onButtonClick={() => toggleParam('overdue')}
                  >
                    Quá hạn
                  </BadgeWithButton>
                ) : (
                  <Button size="xs" color="secondary" onPress={() => toggleParam('overdue')}>
                    Quá hạn
                  </Button>
                )}
                {dueSoonOnly ? (
                  <BadgeWithButton
                    size="sm"
                    type="pill-color"
                    color="warning"
                    buttonLabel="Bỏ lọc sắp hạn"
                    onButtonClick={() => toggleParam('due_soon')}
                  >
                    Sắp hạn ≤ 24h
                  </BadgeWithButton>
                ) : (
                  <Button size="xs" color="secondary" onPress={() => toggleParam('due_soon')}>
                    Sắp hạn
                  </Button>
                )}
              </div>
            </div>

            <Table
              aria-label="Bảng job kiểm tra QC1"
              size="sm"
              selectionMode="single"
              selectionBehavior="replace"
              selectedKeys={selected ? [selected.id] : []}
              onSelectionChange={(keys) => keys !== 'all' && keys.size && setSelectedId(Number([...keys][0]))}
            >
              <Table.Header>
                <Table.Head id="job" label="Job" isRowHeader />
                <Table.Head id="annotator" label="Annotator" />
                <Table.Head id="status" label="Trạng thái" />
                <Table.Head id="deadline" label="Deadline" />
                <Table.Head id="actions" label="Thao tác" />
              </Table.Header>
              <Table.Body
                items={rows}
                renderEmptyState={() => (
                  <EmptyRow text={jobs.isLoading ? 'Đang tải…' : 'Không có job nào trong hàng chờ QC1'} />
                )}
              >
                {(job) => {
                  const isEscalatedBlocked = isJobEscalationBlocked(job, project.escalation_policy)
                  const isWarnOnly = isJobEscalationWarnOnly(job, project.escalation_policy)
                  const reviewable =
                    !job.is_locked && !isEscalatedBlocked && (job.status === 'pending_qc1' || job.status === 'qc1_reviewing')
                  const countdown = formatDeadlineCountdown(job.hours_remaining)
                  return (
                    <Table.Row id={job.id} className="cursor-pointer">
                      <Table.Cell>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="font-medium text-primary">{job.name}</span>
                          {job.rework_round > 0 && (
                            <Badge size="sm" type="pill-color" color="warning">
                              vòng {job.rework_round}
                            </Badge>
                          )}
                        </div>
                        <div className="text-xs text-tertiary">
                          {job.dataset_name} / {job.batch_name} · {formatNumber(job.object_count)} obj / {formatNumber(job.frame_count)} frame
                        </div>
                      </Table.Cell>
                      <Table.Cell>{job.annotator?.full_name ?? '—'}</Table.Cell>
                      <Table.Cell>
                        <JobStatusBadge
                          status={job.status}
                          escalated={job.is_escalated}
                          overdue={job.is_overdue}
                          locked={job.is_locked}
                          sourceMissing={job.source_missing}
                        />
                        {isWarnOnly && (
                          <div className="mt-1 text-xs text-warning-primary">Chế độ cảnh báo</div>
                        )}
                      </Table.Cell>
                      <Table.Cell className="whitespace-nowrap">
                        <div>{formatDateTime(job.deadline)}</div>
                        {countdown && (
                          <div className="mt-1">
                            <Badge size="sm" type="pill-color" color={countdown.tone}>
                              {countdown.text}
                            </Badge>
                          </div>
                        )}
                      </Table.Cell>
                      <Table.Cell>
                        {reviewable ? (
                          <div className="flex gap-1.5">
                            {job.status === 'pending_qc1' && (
                              <Button size="xs" color="secondary" isDisabled={pending} onPress={() => quickStart(job)}>
                                Nhận
                              </Button>
                            )}
                            <Button size="xs" color="secondary" isDisabled={pending} onPress={() => quickPass(job)}>
                              Đạt QC1
                            </Button>
                            <Button size="xs" color="secondary-destructive" onPress={() => setSelectedId(job.id)}>
                              Reject
                            </Button>
                          </div>
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
                <span>
                  Trang {page} · {jobs.data.count} job
                </span>
                <div className="flex gap-2">
                  <Button size="xs" color="secondary" isDisabled={!jobs.data.previous} onPress={() => setPage((p) => p - 1)}>
                    Trước
                  </Button>
                  <Button size="xs" color="secondary" isDisabled={!jobs.data.next} onPress={() => setPage((p) => p + 1)}>
                    Sau
                  </Button>
                </div>
              </div>
            )}
          </SectionCard>

          <div className="xl:sticky xl:top-20 xl:col-span-2">
            {activePanelJobId ? (
              <Qc1ReviewPanel key={activePanelJobId} projectId={projectId} jobId={activePanelJobId} version={version} onDone={reload} />
            ) : (
              <SectionCard>
                <PageState
                  kind="empty"
                  title="Chọn một job"
                  description="Chọn job trong bảng để mở CVAT, xem lỗi và ghi kết quả QC1."
                />
              </SectionCard>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
