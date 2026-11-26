import { ArrowRight } from '@untitledui/icons'
import { useState } from 'react'
import { Link } from 'react-router'
import { Tabs } from '@/components/application/tabs/tabs'
import { BadgeWithDot } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { TextArea } from '@/components/base/textarea/textarea'
import { getErrorMessage } from '../../../shared/api/errors'
import FormDialog from '../../../shared/components/ui/FormDialog'
import PageState from '../../../shared/components/ui/PageState'
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

/** Trang "Yêu cầu của tôi / Yêu cầu xử lý" (/projects/:projectId/annotator/requests) — theo dõi & xử lý phản hồi lỗi, báo dữ liệu bị chặn (TD13). */
export default function AnnotatorRequestsPage() {
  const { projectId, can } = useProject()
  const canResolve = can('manage_jobs')
  const { run, pending } = useAction()
  const [filter, setFilter] = useState<ReqFilter>('all')
  const [version, setVersion] = useState(0)
  const [resolveTarget, setResolveTarget] = useState<{ item: AnnotatorRequest; status: 'resolved' | 'rejected' } | null>(null)
  const [resolutionNote, setResolutionNote] = useState('')

  const req = useRequest(`annotator-requests:${projectId}:${version}`, () => listAnnotatorRequests(projectId))
  const allItems = req.data ?? []
  const openCount = allItems.filter((r) => r.status === 'pending_pm').length

  const visible = allItems.filter((item) => {
    if (filter === 'pending') return item.status === 'pending_pm'
    if (filter === 'error_dispute') return item.request_type === 'error_dispute'
    if (filter === 'data_issue') return item.request_type === 'data_issue'
    if (filter === 'resolved') return item.status === 'resolved' || item.status === 'rejected'
    return true
  })

  async function handleResolve() {
    if (!resolveTarget) return
    const ok = await run(
      () =>
        resolveAnnotatorRequest(projectId, resolveTarget.item.id, {
          status: resolveTarget.status,
          resolution_note: resolutionNote.trim(),
        }),
      resolveTarget.status === 'resolved' ? 'Đã giải quyết yêu cầu' : 'Đã từ chối yêu cầu',
    )
    if (ok) {
      setResolveTarget(null)
      setResolutionNote('')
      setVersion((v) => v + 1)
    }
  }

  return (
    <div className="mx-auto flex max-w-[1160px] flex-col gap-6 px-6 py-7">
      <AnnotatorBreadcrumb
        projectId={projectId}
        items={[
          can('annotate_jobs')
            ? { label: 'Job của tôi', to: `/projects/${projectId}/annotator/jobs` }
            : { label: 'Jobs', to: `/projects/${projectId}/jobs` },
          { label: canResolve ? 'Yêu cầu xử lý' : 'Yêu cầu của tôi' },
        ]}
      />

      <header>
        <h1 className="text-[30px] leading-tight font-bold text-[#101828]">
          {canResolve ? 'Yêu cầu cần xử lý' : 'Yêu cầu của tôi'}
        </h1>
        <p className="mt-1 text-base text-[#475467]">
          {canResolve
            ? 'Tiếp nhận, phản hồi và kết luận các yêu cầu phản hồi lỗi hoặc báo dữ liệu bị chặn.'
            : 'Theo dõi phản hồi lỗi và báo cáo dữ liệu của bạn.'}
        </p>
      </header>

      <section className="overflow-hidden rounded-xl border border-[#EAECF0] bg-white">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#EAECF0] px-6 py-5">
          <div>
            <h2 className="text-lg font-bold text-[#101828]">Theo dõi xử lý</h2>
            <p className="mt-0.5 text-sm text-[#475467]">{openCount} yêu cầu đang mở · TD13</p>
          </div>
          <Tabs selectedKey={filter} onSelectionChange={(k) => setFilter(k as ReqFilter)} className="w-auto">
            <Tabs.List type="button-gray" size="sm" aria-label="Lọc yêu cầu">
              <Tabs.Item id="all" label="Tất cả" />
              <Tabs.Item id="pending" label="Đang chờ" />
              <Tabs.Item id="error_dispute" label="Phản hồi lỗi" />
              <Tabs.Item id="data_issue" label="Dữ liệu bị chặn" />
              <Tabs.Item id="resolved" label="Đã giải quyết" />
            </Tabs.List>
          </Tabs>
        </div>

        {req.error != null ? (
          <div className="p-6">
            <PageState kind="error" description={getErrorMessage(req.error)} onRetry={req.retry} />
          </div>
        ) : req.isLoading ? (
          <div className="p-6">
            <PageState kind="loading" />
          </div>
        ) : visible.length === 0 ? (
          <div className="p-8">
            <PageState
              kind="empty"
              title="Chưa có yêu cầu nào"
              description='Bạn có thể gửi "Phản hồi lỗi" từ trang Cần sửa hoặc "Báo vấn đề dữ liệu" trong trang Chi tiết Job.'
            />
          </div>
        ) : (
          <ul className="divide-y divide-[#EAECF0]">
            {visible.map((item) => {
              const isResolved = item.status === 'resolved' || item.status === 'rejected'
              const notePrefix = isResolved ? 'Kết luận' : 'Tiến độ'
              const noteBody = isResolved
                ? item.resolution_note || item.progress_note || item.reason
                : item.progress_note || item.reason
              return (
                <li key={item.id} className="flex flex-col justify-between gap-4 px-6 py-5 sm:flex-row sm:items-start">
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <div className="text-[15px] font-bold text-[#101828]">
                      {item.request_type_label} · {item.job_name}
                    </div>
                    <p className="text-sm text-[#475467]">{item.title}</p>
                    {noteBody && (
                      <p className="text-sm text-[#344054]">
                        <span className="font-medium">{notePrefix}</span> · {noteBody}
                      </p>
                    )}
                    <p className="text-xs text-[#667085]">
                      {canResolve ? `Người gửi · ${item.created_by.full_name} · ` : ''}
                      Người xử lý ·{' '}
                      {item.handler ? `${item.handler.full_name} (${item.handler_role})` : item.handler_role}
                    </p>
                  </div>

                  <div className="flex shrink-0 flex-row items-center justify-between gap-3 sm:flex-col sm:items-end">
                    <BadgeWithDot size="sm" type="pill-color" color={STATUS_BADGE_COLOR[item.status]}>
                      {item.status_label}
                    </BadgeWithDot>
                    <div className="flex flex-wrap items-center gap-2">
                      {canResolve && item.status === 'pending_pm' && (
                        <>
                          <Button
                            size="sm"
                            color="primary"
                            onPress={() => {
                              setResolutionNote('')
                              setResolveTarget({ item, status: 'resolved' })
                            }}
                          >
                            Giải quyết
                          </Button>
                          <Button
                            size="sm"
                            color="secondary-destructive"
                            onPress={() => {
                              setResolutionNote('')
                              setResolveTarget({ item, status: 'rejected' })
                            }}
                          >
                            Từ chối
                          </Button>
                        </>
                      )}
                      <Link
                        to={
                          can('annotate_jobs')
                            ? `/projects/${projectId}/annotator/jobs/${item.job}`
                            : `/projects/${projectId}/jobs?search=${encodeURIComponent(item.job_name)}`
                        }
                        className="inline-flex items-center gap-1.5 text-sm font-semibold text-[#6941C6] hover:text-[#53389E]"
                      >
                        Mở job
                        <ArrowRight className="size-4" />
                      </Link>
                    </div>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <FormDialog
        isOpen={resolveTarget !== null}
        onClose={() => setResolveTarget(null)}
        title={resolveTarget?.status === 'resolved' ? 'Xác nhận giải quyết yêu cầu' : 'Xác nhận từ chối yêu cầu'}
        description={resolveTarget ? `${resolveTarget.item.request_type_label} · ${resolveTarget.item.job_name}` : undefined}
        submitLabel={resolveTarget?.status === 'resolved' ? 'Giải quyết' : 'Từ chối'}
        onSubmit={handleResolve}
        pending={pending}
      >
        <TextArea
          label="Ghi chú kết luận"
          placeholder="Nhập kết luận hoặc hướng xử lý gửi tới annotator…"
          rows={3}
          value={resolutionNote}
          onChange={setResolutionNote}
        />
      </FormDialog>
    </div>
  )
}
