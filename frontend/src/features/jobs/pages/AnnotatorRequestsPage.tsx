import { ArrowRight } from '@untitledui/icons'
import { useState } from 'react'
import { Link } from 'react-router'
import { Tabs } from '@/components/application/tabs/tabs'
import { Badge, BadgeWithDot } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { TextArea } from '@/components/base/textarea/textarea'
import { getErrorMessage } from '../../../shared/api/errors'
import FormDialog from '../../../shared/components/ui/FormDialog'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { useProject } from '../../projects/projectContext'
import { listAnnotatorRequests, resolveAnnotatorRequest } from '../api'
import AnnotatorBreadcrumb from '../components/AnnotatorBreadcrumb'
import type { AnnotatorRequest, AnnotatorRequestStatus } from '../types'

type ReqFilter = 'all' | 'pending' | 'error_dispute' | 'data_issue' | 'resolved'

const STATUS_BADGE_COLOR: Record<AnnotatorRequestStatus, 'warning' | 'success' | 'error' | 'gray'> = {
  pending_pm: 'warning',
  resolved: 'success',
  rejected: 'error',
}

/** Trang theo dõi phản hồi lỗi & báo dữ liệu bị chặn; Project Manager có thể xử lý / từ chối trực tiếp. */
export default function AnnotatorRequestsPage() {
  const { projectId, can } = useProject()
  const isManager = can('manage_jobs')
  const isAnnotator = can('annotate_jobs')
  const isManagerOnly = isManager && !isAnnotator
  const canViewJobs = can('view_jobs')

  const [filter, setFilter] = useState<ReqFilter>('all')
  const [version, setVersion] = useState(0)
  const [resolving, setResolving] = useState<{ item: AnnotatorRequest; status: 'resolved' | 'rejected' } | null>(null)
  const [resolutionNote, setResolutionNote] = useState('')
  const { run, pending } = useAction()

  const req = useRequest(`annotator-requests:${projectId}:${version}`, () => listAnnotatorRequests(projectId))
  const allItems = req.data ?? []
  const openCount = allItems.filter((r) => r.status === 'pending_pm').length
  const reload = () => setVersion((v) => v + 1)

  const visible = allItems.filter((item) => {
    if (filter === 'pending') return item.status === 'pending_pm'
    if (filter === 'error_dispute') return item.request_type === 'error_dispute'
    if (filter === 'data_issue') return item.request_type === 'data_issue'
    if (filter === 'resolved') return item.status === 'resolved' || item.status === 'rejected'
    return true
  })

  function openResolveDialog(item: AnnotatorRequest, status: 'resolved' | 'rejected') {
    setResolutionNote('')
    setResolving({ item, status })
  }

  async function submitResolve() {
    if (!resolving) return
    const ok = await run(
      () =>
        resolveAnnotatorRequest(projectId, resolving.item.id, {
          status: resolving.status,
          resolution_note: resolutionNote.trim(),
        }),
      resolving.status === 'resolved' ? 'Đã xác nhận xử lý yêu cầu' : 'Đã từ chối yêu cầu',
    )
    if (ok) {
      setResolving(null)
      setResolutionNote('')
      reload()
    }
  }

  const pageTitle = isManagerOnly ? 'Yêu cầu từ Annotator' : 'Yêu cầu của tôi'
  const pageDescription = isManagerOnly
    ? 'Xem xét và xử lý phản hồi lỗi, báo cáo dữ liệu từ Annotator.'
    : 'Theo dõi phản hồi lỗi và báo cáo dữ liệu của bạn.'

  const breadcrumbItems = isAnnotator
    ? [
        { label: 'Job của tôi', to: `/projects/${projectId}/annotator/jobs` },
        { label: pageTitle },
      ]
    : [{ label: pageTitle }]

  const jobLinkFor = (item: AnnotatorRequest) => {
    if (isAnnotator) return `/projects/${projectId}/annotator/jobs/${item.job}`
    if (canViewJobs) return `/projects/${projectId}/jobs?search=${encodeURIComponent(item.job_name)}`
    return null
  }

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 md:p-6">
      <AnnotatorBreadcrumb projectId={projectId} items={breadcrumbItems} />

      <header>
        <h1 className="text-display-xs font-semibold text-primary">{pageTitle}</h1>
        <p className="mt-1 text-sm text-tertiary">{pageDescription}</p>
      </header>

      <SectionCard
        title="Theo dõi xử lý"
        description={`${openCount} yêu cầu đang mở`}
        actions={
          <Tabs selectedKey={filter} onSelectionChange={(k) => setFilter(k as ReqFilter)} className="w-auto">
            <Tabs.List type="button-gray" size="sm" aria-label="Lọc yêu cầu">
              <Tabs.Item id="all" label="Tất cả" />
              <Tabs.Item id="pending" label="Đang chờ" />
              <Tabs.Item id="error_dispute" label="Phản hồi lỗi" />
              <Tabs.Item id="data_issue" label="Dữ liệu bị chặn" />
              <Tabs.Item id="resolved" label="Đã giải quyết" />
            </Tabs.List>
          </Tabs>
        }
        bodyClassName="p-0"
      >
        {req.error != null ? (
          <PageState kind="error" description={getErrorMessage(req.error)} onRetry={req.retry} />
        ) : req.isLoading ? (
          <PageState kind="loading" />
        ) : visible.length === 0 ? (
          <PageState
            kind="empty"
            title="Chưa có yêu cầu nào"
            description={
              isManagerOnly
                ? 'Chưa có phản hồi lỗi hay báo cáo vấn đề dữ liệu nào từ Annotator.'
                : 'Bạn có thể gửi "Phản hồi lỗi" từ trang Cần sửa hoặc "Báo vấn đề dữ liệu" trong trang Chi tiết Job.'
            }
          />
        ) : (
          <ul className="divide-y divide-secondary">
            {visible.map((item) => {
              const isResolved = item.status === 'resolved' || item.status === 'rejected'
              const notePrefix = isResolved ? 'Kết luận' : 'Tiến độ'
              const noteBody = isResolved
                ? item.resolution_note || item.progress_note || item.reason
                : item.progress_note || item.reason
              const jobHref = jobLinkFor(item)
              return (
                <li key={item.id} className="flex flex-col justify-between gap-4 px-5 py-4 sm:flex-row sm:items-start">
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge
                        size="sm"
                        type="pill-color"
                        color={item.request_type === 'error_dispute' ? 'blue' : 'gray'}
                      >
                        {item.request_type_label}
                      </Badge>
                      <span className="text-sm font-semibold text-primary">{item.job_name}</span>
                    </div>
                    <p className="text-sm text-secondary">{item.title}</p>
                    {noteBody && (
                      <p className="text-sm text-tertiary">
                        <span className="font-medium text-secondary">{notePrefix}</span> · {noteBody}
                      </p>
                    )}
                    <p className="text-xs text-quaternary">
                      {isManager && item.created_by ? `Người gửi · ${item.created_by.full_name} · ` : ''}
                      Người xử lý ·{' '}
                      {item.handler ? `${item.handler.full_name} (${item.handler_role})` : item.handler_role}
                    </p>
                  </div>

                  <div className="flex shrink-0 flex-row flex-wrap items-center justify-between gap-3 sm:flex-col sm:items-end">
                    <BadgeWithDot size="sm" type="pill-color" color={STATUS_BADGE_COLOR[item.status] ?? 'gray'}>
                      {item.status_label}
                    </BadgeWithDot>
                    <div className="flex flex-wrap items-center gap-2">
                      {isManager && item.status === 'pending_pm' && (
                        <>
                          <Button
                            size="sm"
                            color="primary"
                            isDisabled={pending}
                            onPress={() => openResolveDialog(item, 'resolved')}
                          >
                            Xử lý
                          </Button>
                          <Button
                            size="sm"
                            color="secondary-destructive"
                            isDisabled={pending}
                            onPress={() => openResolveDialog(item, 'rejected')}
                          >
                            Từ chối
                          </Button>
                        </>
                      )}
                      {jobHref && (
                        <Link
                          to={jobHref}
                          className="inline-flex items-center gap-1.5 text-sm font-semibold text-brand-secondary transition hover:text-brand-secondary_hover"
                        >
                          Mở job
                          <ArrowRight className="size-4" />
                        </Link>
                      )}
                    </div>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </SectionCard>

      <FormDialog
        isOpen={resolving !== null}
        destructive={resolving?.status === 'rejected'}
        title={resolving?.status === 'resolved' ? 'Xác nhận xử lý yêu cầu' : 'Từ chối yêu cầu'}
        description={
          resolving
            ? `${resolving.item.request_type_label} · ${resolving.item.job_name} — ${resolving.item.title}`
            : undefined
        }
        submitLabel={resolving?.status === 'resolved' ? 'Xác nhận xử lý' : 'Từ chối yêu cầu'}
        onClose={() => setResolving(null)}
        onSubmit={submitResolve}
        pending={pending}
      >
        <TextArea
          label="Ghi chú kết luận"
          placeholder={
            resolving?.status === 'resolved'
              ? 'Ghi rõ phương án đã xử lý hoặc kết luận cho Annotator…'
              : 'Ghi rõ lý do từ chối yêu cầu để Annotator nắm thông tin…'
          }
          rows={3}
          value={resolutionNote}
          onChange={setResolutionNote}
        />
      </FormDialog>
    </div>
  )
}
