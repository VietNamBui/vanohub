import { ArrowRight, Plus, SearchLg } from '@untitledui/icons'
import dayjs from 'dayjs'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { Tabs } from '@/components/application/tabs/tabs'
import { Badge, BadgeWithDot } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { Input } from '@/components/base/input/input'
import { ProgressBarBase } from '@/components/base/progress-indicators/progress-indicators'
import { getErrorMessage } from '../../../shared/api/errors'
import PageState from '../../../shared/components/ui/PageState'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatNumber } from '../../../shared/utils/format'
import { useProject } from '../../projects/projectContext'
import { claimAnnotatorJob, getAnnotatorDashboard, listAnnotatorJobs } from '../api'
import AnnotatorBreadcrumb from '../components/AnnotatorBreadcrumb'
import AnnotatorJobDrawer from '../components/AnnotatorJobDrawer'
import { formatDeadlineCountdown, JOB_STATUS_LABELS } from '../constants'
import type { AnnotatorJobTab } from '../types'

const TABS: { id: AnnotatorJobTab; label: string }[] = [
  { id: 'active', label: 'Đang giữ' },
  { id: 'rework', label: 'Cần sửa' },
  { id: 'submitted', label: 'Đã nộp' },
  { id: 'done', label: 'Hoàn tất' },
  { id: 'all', label: 'Tất cả' },
]

/** Trang "Job của tôi": hàng đợi ưu tiên DB06, nhận job mới (GV02), tiến độ TD03 và drawer xem nhanh. */
export default function AnnotatorJobsPage() {
  const { projectId, project } = useProject()
  const navigate = useNavigate()
  const [tab, setTab] = useState<AnnotatorJobTab>('active')
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [version, setVersion] = useState(0)
  const [drawerJobId, setDrawerJobId] = useState<number | null>(null)
  const { run, pending } = useAction()

  const jobs = useRequest(`annotator-jobs:${projectId}:${tab}:${query}:${page}:${version}`, () =>
    listAnnotatorJobs(projectId, { tab, search: query || undefined, page }),
  )
  const dash = useRequest(`annotator-wip:${projectId}:${version}`, () => getAnnotatorDashboard(projectId, 'week'))

  const rows = jobs.data?.results ?? []
  const activeCount = dash.data?.meta?.active_jobs_count ?? rows.filter((j) => ['pending_annotation', 'annotating', 'rework'].includes(j.status)).length
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
    <div className="mx-auto flex max-w-[1160px] flex-col gap-6 px-6 py-7">
      <AnnotatorBreadcrumb projectId={projectId} items={[{ label: 'Job của tôi' }]} />

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-[30px] leading-tight font-bold text-[#101828]">Job của tôi</h1>
          <p className="mt-1 text-base text-[#475467]">
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

      <section className="overflow-hidden rounded-xl border border-[#EAECF0] bg-white">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#EAECF0] px-6 py-5">
          <div>
            <h2 className="text-lg font-bold text-[#101828]">Hàng đợi của tôi</h2>
            <p className="mt-0.5 text-sm text-[#475467]">Quá hạn → sắp hạn → còn lại · DB06</p>
          </div>
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
                placeholder="Tìm mã job, batch…"
                value={search}
                onChange={setSearch}
              />
            </form>
          </div>
        </div>

        {jobs.error != null ? (
          <div className="p-6">
            <PageState kind="error" description={getErrorMessage(jobs.error)} onRetry={jobs.retry} />
          </div>
        ) : jobs.isLoading ? (
          <div className="p-6">
            <PageState kind="loading" />
          </div>
        ) : rows.length === 0 ? (
          <div className="p-8">
            <PageState
              kind="empty"
              title="Chưa có job nào trong mục này"
              description='Bạn có thể đổi bộ lọc hoặc bấm "Nhận job mới" để nhận việc từ hàng chờ dự án.'
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-left">
              <thead className="border-b border-[#EAECF0] bg-[#F9FAFB] text-xs font-medium text-[#475467]">
                <tr>
                  <th className="px-6 py-3">Job</th>
                  <th className="px-4 py-3">Trạng thái</th>
                  <th className="px-4 py-3">Tiến độ · TD03</th>
                  <th className="px-4 py-3">Hạn · DH02/DH04</th>
                  <th className="px-4 py-3">Vòng sửa · RW01</th>
                  <th className="px-6 py-3 text-right">Thao tác</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#EAECF0]">
                {rows.map((job) => {
                  const target = job.target_object_count || job.object_count
                  const pct = job.progress_percent ?? 0
                  const countdown = formatDeadlineCountdown(job.hours_remaining)
                  const isRework = job.status === 'rework'
                  const statusColor =
                    isRework
                      ? 'warning'
                      : job.status === 'annotating'
                        ? 'blue'
                        : job.status === 'approved' || job.status === 'delivered'
                          ? 'success'
                          : 'gray'

                  return (
                    <tr
                      key={job.id}
                      onClick={() => setDrawerJobId(job.id)}
                      className="cursor-pointer transition hover:bg-[#F9FAFB]"
                    >
                      <td className="px-6 py-4">
                        <div className="text-sm font-bold text-[#101828]">{job.name}</div>
                        <div className="mt-0.5 text-xs text-[#475467]">{job.batch_name}</div>
                      </td>
                      <td className="px-4 py-4">
                        <div className="flex flex-wrap gap-1.5">
                          <BadgeWithDot size="sm" type="pill-color" color={statusColor}>
                            {isRework ? 'Cần sửa' : job.status === 'annotating' ? 'Đang làm' : JOB_STATUS_LABELS[job.status]}
                          </BadgeWithDot>
                          {job.is_escalated && (
                            <Badge size="sm" type="pill-color" color="error">
                              Cảnh báo vòng {job.rework_round}
                            </Badge>
                          )}
                        </div>
                      </td>
                      <td className="w-60 px-4 py-4">
                        <div className="mb-1.5 text-xs text-[#344054] tabular-nums">
                          {pct}% · {formatNumber(job.object_count)}/{formatNumber(target)} object-frame
                        </div>
                        <ProgressBarBase value={pct} className="bg-[#EAECF0]" progressClassName="bg-[#7F56D9]" />
                      </td>
                      <td className="px-4 py-4">
                        <div className="text-xs font-medium text-[#344054]">
                          {job.deadline ? dayjs(job.deadline).format('DD/MM HH:mm') : 'Chưa đặt'}
                        </div>
                        {countdown && (
                          <div className="mt-1">
                            <Badge size="sm" type="pill-color" color={countdown.tone}>
                              {countdown.text}
                            </Badge>
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-4">
                        <BadgeWithDot size="sm" type="pill-color" color={job.rework_round > 0 ? 'warning' : 'gray'}>
                          {job.rework_round}/{job.max_rework_rounds}
                        </BadgeWithDot>
                      </td>
                      <td className="px-6 py-4 text-right" onClick={(e) => e.stopPropagation()}>
                        <button
                          type="button"
                          onClick={() => navigate(`/projects/${projectId}/annotator/jobs/${job.id}`)}
                          className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-[#E9D7FE] bg-[#F9F5FF] px-3.5 py-2 text-sm font-semibold text-[#6941C6] transition hover:bg-[#F4EBFF]"
                        >
                          Tiếp tục làm
                          <ArrowRight className="size-4" />
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {jobs.data && jobs.data.count > rows.length && (
          <div className="flex items-center justify-between border-t border-[#EAECF0] px-6 py-3.5 text-sm text-[#475467]">
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
      </section>

      <AnnotatorJobDrawer projectId={projectId} jobId={drawerJobId} onClose={() => setDrawerJobId(null)} />
    </div>
  )
}
