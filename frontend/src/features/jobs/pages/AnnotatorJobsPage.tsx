import { ArrowRight, Plus, SearchLg } from '@untitledui/icons'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { Tabs } from '@/components/application/tabs/tabs'
import { Badge, BadgeWithButton, BadgeWithDot } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { Input } from '@/components/base/input/input'
import { ProgressBarBase } from '@/components/base/progress-indicators/progress-indicators'
import { getErrorMessage } from '../../../shared/api/errors'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatNumber, formatShortDateTime } from '../../../shared/utils/format'
import { useProject } from '../../projects/projectContext'
import { claimAnnotatorJob, getAnnotatorDashboard, listAnnotatorJobs } from '../api'
import AnnotatorBreadcrumb from '../components/AnnotatorBreadcrumb'
import AnnotatorJobDrawer from '../components/AnnotatorJobDrawer'
import JobStatusBadge from '../components/JobStatusBadge'
import { formatDeadlineCountdown } from '../constants'
import type { AnnotatorJobTab } from '../types'

const TABS: { id: AnnotatorJobTab; label: string }[] = [
  { id: 'active', label: 'Đang giữ' },
  { id: 'rework', label: 'Cần sửa' },
  { id: 'submitted', label: 'Đã nộp' },
  { id: 'done', label: 'Hoàn tất' },
  { id: 'all', label: 'Tất cả' },
]

/** Trang "Job của tôi": hàng đợi ưu tiên theo hạn, nhận job mới, theo dõi tiến độ và drawer xem nhanh. */
export default function AnnotatorJobsPage() {
  const { projectId, project } = useProject()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const dueSoon = searchParams.get('due_soon') === '1'
  const overdue = searchParams.get('overdue') === '1'
  const [tab, setTab] = useState<AnnotatorJobTab>('active')
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [version, setVersion] = useState(0)
  const [drawerJobId, setDrawerJobId] = useState<number | null>(null)
  const { run, pending } = useAction()

  const jobs = useRequest(
    `annotator-jobs:${projectId}:${tab}:${query}:${page}:${dueSoon ? 1 : 0}:${overdue ? 1 : 0}:${version}`,
    () =>
      listAnnotatorJobs(projectId, {
        tab,
        search: query || undefined,
        page,
        due_soon: dueSoon || undefined,
        overdue: overdue || undefined,
      }),
  )

  function clearParam(key: 'due_soon' | 'overdue') {
    const next = new URLSearchParams(searchParams)
    next.delete(key)
    setSearchParams(next, { replace: true })
    setPage(1)
  }

  const dash = useRequest(`annotator-wip:${projectId}:${version}`, () => getAnnotatorDashboard(projectId, 'week'))

  const rows = jobs.data?.results ?? []
  const activeCount =
    dash.data?.meta?.active_jobs_count ??
    rows.filter((j) => ['pending_annotation', 'annotating', 'rework'].includes(j.status)).length
  const wipLimit = dash.data?.meta?.wip_limit ?? 2
  const reload = () => setVersion((v) => v + 1)

  async function handleClaimNewJob() {
    const claimed = await run(() => claimAnnotatorJob(projectId), 'Đã nhận job mới từ hàng chờ')
    if (claimed) {
      setTab('active')
      setPage(1)
      reload()
    }
  }

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 md:p-6">
      <AnnotatorBreadcrumb projectId={projectId} items={[{ label: 'Job của tôi' }]} />

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Job của tôi</h1>
          <p className="mt-1 text-sm text-tertiary">
            {project.name} · Đang giữ {activeCount}/{wipLimit} job
          </p>
        </div>

        <Button
          color="primary"
          size="md"
          iconLeading={Plus}
          isLoading={pending}
          onPress={handleClaimNewJob}
        >
          Nhận job mới
        </Button>
      </header>

      <SectionCard
        title="Hàng đợi của tôi"
        description="Ưu tiên: quá hạn → sắp hạn → còn lại"
        actions={
          <div className="flex flex-wrap items-center gap-3">
            <Tabs
              selectedKey={tab}
              onSelectionChange={(k) => {
                setTab(k as AnnotatorJobTab)
                setPage(1)
              }}
              className="w-auto"
            >
              <Tabs.List type="button-gray" size="sm" aria-label="Lọc hàng đợi">
                {TABS.map((t) => (
                  <Tabs.Item key={t.id} id={t.id} label={t.label} />
                ))}
              </Tabs.List>
            </Tabs>
            <form
              className="w-56"
              onSubmit={(e) => {
                e.preventDefault()
                setQuery(search.trim())
                setPage(1)
              }}
            >
              <Input
                size="sm"
                icon={SearchLg}
                aria-label="Tìm job"
                placeholder="Tìm mã job, task…"
                value={search}
                onChange={setSearch}
              />
            </form>
            {dueSoon && (
              <BadgeWithButton
                size="sm"
                type="pill-color"
                color="warning"
                buttonLabel="Bỏ lọc sắp / quá hạn"
                onButtonClick={() => clearParam('due_soon')}
              >
                Sắp / quá hạn
              </BadgeWithButton>
            )}
            {overdue && (
              <BadgeWithButton
                size="sm"
                type="pill-color"
                color="error"
                buttonLabel="Bỏ lọc quá hạn"
                onButtonClick={() => clearParam('overdue')}
              >
                Quá hạn
              </BadgeWithButton>
            )}
          </div>
        }
        bodyClassName="p-0"
      >
        {jobs.error != null ? (
          <PageState kind="error" description={getErrorMessage(jobs.error)} onRetry={jobs.retry} />
        ) : jobs.isLoading ? (
          <PageState kind="loading" />
        ) : rows.length === 0 ? (
          <PageState
            kind="empty"
            title="Chưa có job nào trong mục này"
            description='Bạn có thể đổi bộ lọc hoặc bấm "Nhận job mới" để nhận việc từ hàng chờ.'
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-left text-sm">
              <thead className="bg-secondary text-xs font-semibold text-quaternary">
                <tr>
                  <th className="px-5 py-3">Job</th>
                  <th className="px-4 py-3">Trạng thái</th>
                  <th className="px-4 py-3">Tiến độ</th>
                  <th className="px-4 py-3">Hạn</th>
                  <th className="px-4 py-3">Vòng sửa</th>
                  <th className="px-5 py-3 text-right">Thao tác</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-secondary">
                {rows.map((job) => {
                  const target = job.target_object_count || job.object_count
                  const pct = job.progress_percent ?? 0
                  const countdown = formatDeadlineCountdown(job.hours_remaining)

                  return (
                    <tr
                      key={job.id}
                      onClick={() => setDrawerJobId(job.id)}
                      className="cursor-pointer transition hover:bg-primary_hover"
                    >
                      <td className="px-5 py-3.5">
                        <div className="font-semibold text-primary">{job.name}</div>
                        <div className="mt-0.5 text-xs text-tertiary">{job.batch_name}</div>
                      </td>
                      <td className="px-4 py-3.5">
                        <JobStatusBadge
                          status={job.status}
                          escalated={job.is_escalated}
                          overdue={job.is_overdue}
                          locked={job.is_locked}
                        />
                      </td>
                      <td className="w-60 px-4 py-3.5">
                        <div className="mb-1.5 text-xs text-secondary tabular-nums">
                          {pct}% · {formatNumber(job.object_count)}/{formatNumber(target)} object-frame
                        </div>
                        <ProgressBarBase value={pct} />
                      </td>
                      <td className="px-4 py-3.5">
                        <div className="text-xs font-medium text-secondary">
                          {job.deadline ? formatShortDateTime(job.deadline) : 'Chưa đặt'}
                        </div>
                        {countdown && (
                          <div className="mt-1">
                            <Badge size="sm" type="pill-color" color={countdown.tone}>
                              {countdown.text}
                            </Badge>
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3.5">
                        <BadgeWithDot size="sm" type="pill-color" color={job.rework_round > 0 ? 'warning' : 'gray'}>
                          {job.rework_round}/{job.max_rework_rounds}
                        </BadgeWithDot>
                      </td>
                      <td className="px-5 py-3.5 text-right" onClick={(e) => e.stopPropagation()}>
                        <Button
                          size="sm"
                          color="secondary"
                          iconTrailing={ArrowRight}
                          onPress={() => navigate(`/projects/${projectId}/annotator/jobs/${job.id}`)}
                        >
                          Tiếp tục làm
                        </Button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {jobs.data && jobs.data.count > rows.length && (
          <div className="flex items-center justify-between border-t border-secondary px-5 py-3.5 text-sm text-tertiary">
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

      <AnnotatorJobDrawer projectId={projectId} jobId={drawerJobId} onClose={() => setDrawerJobId(null)} />
    </div>
  )
}
