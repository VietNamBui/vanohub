import { Eye, FilterLines, RefreshCw01 } from '@untitledui/icons'
import { useState } from 'react'
import { Link } from 'react-router'
import { Table } from '@/components/application/table/table'
import { Badge } from '@/components/base/badges/badges'
import type { BadgeColors } from '@/components/base/badges/badge-types'
import { Button } from '@/components/base/buttons/button'
import { Select } from '@/components/base/select/select'
import { getErrorMessage } from '../../../shared/api/errors'
import EmptyRow from '../../../shared/components/ui/EmptyRow'
import PageState from '../../../shared/components/ui/PageState'
import ProjectBreadcrumb from '../../../shared/components/ui/ProjectBreadcrumb'
import SectionCard from '../../../shared/components/ui/SectionCard'
import Slideover from '../../../shared/components/ui/Slideover'
import UserName from '../../../shared/components/UserName'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import { listActivity } from '../api'
import MemberSelect from '../components/MemberSelect'
import { useProject } from '../projectContext'
import {
  ACTIVITY_ACTION_LABELS,
  ACTIVITY_ACTION_PREFIX_OPTIONS,
  formatActivityChangeSummary,
} from '../projectHelpers'
import type { ActivityLog } from '../types'

const PAGE_SIZE = 50

function actionBadgeColor(action: string): BadgeColors {
  if (action.includes('reject') || action.includes('lock') || action.includes('remove')) return 'warning'
  if (action.includes('pass') || action.includes('deliver') || action.includes('create')) return 'success'
  if (action.includes('escalation') || action.includes('delete')) return 'error'
  if (action.startsWith('cvat.') || action.startsWith('project.')) return 'brand'
  return 'gray'
}

/** Nhật ký hoạt động cấp organization (PM — chỉ đọc, lọc theo người thực hiện, nhóm hành động, khoảng ngày). */
export default function ActivityLogPage() {
  const { project, projectId } = useProject()
  const [actor, setActor] = useState<number | null>(null)
  const [action, setAction] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [page, setPage] = useState(1)
  const [version, setVersion] = useState(0)
  const [selectedLog, setSelectedLog] = useState<ActivityLog | null>(null)

  const dateRangeInvalid = Boolean(dateFrom && dateTo && dateFrom > dateTo)
  const requestKey = dateRangeInvalid
    ? `activity:${projectId}:invalid:${dateFrom}:${dateTo}`
    : `activity:${projectId}:p${page}:a${actor ?? ''}:act${action}:f${dateFrom}:t${dateTo}:v${version}`

  const { data, error, isLoading, retry } = useRequest(requestKey, () =>
    dateRangeInvalid
      ? Promise.resolve({ count: 0, next: null, previous: null, results: [] })
      : listActivity(projectId, {
          page,
          page_size: PAGE_SIZE,
          actor: actor ?? undefined,
          action: action || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
        }),
  )

  const rows = data?.results ?? []
  const totalCount = data?.count ?? 0
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE))
  const hasActiveFilters = actor != null || action !== '' || dateFrom !== '' || dateTo !== ''

  function clearFilters() {
    setActor(null)
    setAction('')
    setDateFrom('')
    setDateTo('')
    setPage(1)
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-5 p-4 md:p-6">
      <ProjectBreadcrumb projectId={projectId} items={[{ label: 'Nhật ký hoạt động' }]} />

      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Nhật ký hoạt động</h1>
          <p className="mt-1 text-sm text-tertiary">
            Lịch sử bất biến mọi thao tác vận hành và cấu hình trong organization{' '}
            <span className="font-medium text-secondary">{project.name}</span>.
          </p>
        </div>
        <Button size="sm" color="secondary" iconLeading={RefreshCw01} onPress={() => setVersion((v) => v + 1)}>
          Làm mới
        </Button>
      </header>

      <SectionCard bodyClassName="p-0">
        <div className="grid grid-cols-1 gap-3 border-b border-secondary p-4 sm:grid-cols-2 lg:grid-cols-5 lg:items-end">
          <MemberSelect
            projectId={projectId}
            label="Người thực hiện"
            placeholder="Tất cả thành viên"
            size="sm"
            value={actor}
            onChange={(next) => {
              setActor(next)
              setPage(1)
            }}
          />

          <Select
            label="Hành động"
            size="sm"
            items={ACTIVITY_ACTION_PREFIX_OPTIONS}
            selectedKey={action}
            onSelectionChange={(k) => {
              setAction(String(k ?? ''))
              setPage(1)
            }}
          >
            {(item) => <Select.Item id={item.id} label={item.label} />}
          </Select>

          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-secondary">Từ ngày</span>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => {
                setDateFrom(e.target.value)
                setPage(1)
              }}
              className="rounded-lg bg-primary px-3 py-2 text-sm text-primary shadow-xs ring-1 ring-primary outline-none ring-inset focus:ring-2 focus:ring-brand"
            />
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-secondary">Đến ngày</span>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => {
                setDateTo(e.target.value)
                setPage(1)
              }}
              className="rounded-lg bg-primary px-3 py-2 text-sm text-primary shadow-xs ring-1 ring-primary outline-none ring-inset focus:ring-2 focus:ring-brand"
            />
          </label>

          <div className="flex items-center gap-2">
            {hasActiveFilters && (
              <Button size="sm" color="secondary" iconLeading={FilterLines} onPress={clearFilters}>
                Xoá bộ lọc
              </Button>
            )}
          </div>
        </div>

        {dateRangeInvalid ? (
          <div className="p-5">
            <div role="alert" className="rounded-xl bg-error-primary px-4 py-3 text-sm text-error-primary ring-1 ring-error_subtle ring-inset">
              Mốc &ldquo;Đến ngày&rdquo; phải lớn hơn hoặc bằng &ldquo;Từ ngày&rdquo;.
            </div>
          </div>
        ) : error != null ? (
          <PageState kind="error" description={getErrorMessage(error)} onRetry={retry} />
        ) : (
          <>
            <Table aria-label="Nhật ký hoạt động" size="sm">
              <Table.Header>
                <Table.Head id="time" label="Thời gian" isRowHeader />
                <Table.Head id="actor" label="Người thực hiện" />
                <Table.Head id="action" label="Hành động" />
                <Table.Head id="target" label="Đối tượng" />
                <Table.Head id="detail" label="Chi tiết & ghi chú" />
                <Table.Head id="inspect" />
              </Table.Header>
              <Table.Body
                items={rows}
                renderEmptyState={() => (
                  <EmptyRow text={isLoading ? 'Đang tải nhật ký…' : 'Không có bản ghi nhật ký phù hợp'} />
                )}
              >
                {(log) => {
                  const summary = formatActivityChangeSummary(log)
                  const hasInspectableDetail = Boolean(log.before || log.after || log.note)
                  return (
                    <Table.Row id={log.id}>
                      <Table.Cell className="whitespace-nowrap tabular-nums">
                        {formatDateTime(log.created_at)}
                      </Table.Cell>
                      <Table.Cell>
                        {log.actor ? (
                          <UserName user={log.actor} />
                        ) : (
                          <Badge type="pill-color" size="sm" color="gray">
                            Hệ thống
                          </Badge>
                        )}
                      </Table.Cell>
                      <Table.Cell>
                        <div className="flex flex-col items-start gap-0.5">
                          <Badge type="pill-color" size="sm" color={actionBadgeColor(log.action)}>
                            {ACTIVITY_ACTION_LABELS[log.action] ?? log.action}
                          </Badge>
                          <span className="font-mono text-xs text-quaternary">{log.action}</span>
                        </div>
                      </Table.Cell>
                      <Table.Cell>
                        <div className="flex flex-col">
                          {log.job && log.target_label ? (
                            <Link
                              to={`../jobs?search=${encodeURIComponent(log.target_label)}`}
                              relative="path"
                              className="font-medium text-brand-secondary hover:underline"
                            >
                              {log.target_label}
                            </Link>
                          ) : (
                            <span className="font-medium text-primary">
                              {log.target_label || `${log.target_type}${log.target_id ? ` #${log.target_id}` : ''}`}
                            </span>
                          )}
                          <span className="text-xs text-quaternary">
                            {log.target_type}
                            {log.target_id != null ? ` #${log.target_id}` : ''}
                          </span>
                        </div>
                      </Table.Cell>
                      <Table.Cell className="max-w-md">
                        <div className="flex flex-col gap-0.5 text-xs text-secondary">
                          {summary && (
                            <span className="line-clamp-2" title={summary}>
                              {summary}
                            </span>
                          )}
                          {log.note && (
                            <span className="line-clamp-2 text-tertiary" title={log.note}>
                              Ghi chú: {log.note}
                            </span>
                          )}
                          {!summary && !log.note && <span className="text-quaternary">—</span>}
                        </div>
                      </Table.Cell>
                      <Table.Cell className="text-right">
                        {hasInspectableDetail && (
                          <Button
                            size="xs"
                            color="link-gray"
                            iconLeading={Eye}
                            onPress={() => setSelectedLog(log)}
                          >
                            Chi tiết
                          </Button>
                        )}
                      </Table.Cell>
                    </Table.Row>
                  )
                }}
              </Table.Body>
            </Table>

            {totalCount > PAGE_SIZE && (
              <div className="flex items-center justify-between border-t border-secondary px-5 py-3 text-sm text-tertiary">
                <span>
                  Trang {page} / {totalPages} · {totalCount} bản ghi
                </span>
                <div className="flex gap-2">
                  <Button
                    size="xs"
                    color="secondary"
                    isDisabled={page <= 1 || isLoading}
                    onPress={() => setPage((p) => Math.max(1, p - 1))}
                  >
                    Trước
                  </Button>
                  <Button
                    size="xs"
                    color="secondary"
                    isDisabled={!data?.next || isLoading}
                    onPress={() => setPage((p) => p + 1)}
                  >
                    Sau
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </SectionCard>

      <Slideover
        isOpen={selectedLog !== null}
        onClose={() => setSelectedLog(null)}
        title={selectedLog ? ACTIVITY_ACTION_LABELS[selectedLog.action] ?? selectedLog.action : 'Chi tiết nhật ký'}
        extra={
          selectedLog && (
            <Badge type="pill-color" size="sm" color={actionBadgeColor(selectedLog.action)}>
              {selectedLog.action}
            </Badge>
          )
        }
      >
        {selectedLog && (
          <div className="flex flex-col gap-5 text-sm">
            <dl className="grid grid-cols-1 gap-3 rounded-xl border border-secondary bg-secondary_subtle p-4 sm:grid-cols-2">
              <div>
                <dt className="text-xs font-medium text-tertiary">Thời gian</dt>
                <dd className="mt-0.5 font-medium text-primary tabular-nums">{formatDateTime(selectedLog.created_at)}</dd>
              </div>
              <div>
                <dt className="text-xs font-medium text-tertiary">Người thực hiện</dt>
                <dd className="mt-0.5 text-primary">
                  {selectedLog.actor ? <UserName user={selectedLog.actor} /> : 'Hệ thống'}
                </dd>
              </div>
              <div>
                <dt className="text-xs font-medium text-tertiary">Đối tượng</dt>
                <dd className="mt-0.5 text-primary">
                  {selectedLog.target_label || `${selectedLog.target_type} #${selectedLog.target_id ?? '—'}`}
                </dd>
              </div>
              <div>
                <dt className="text-xs font-medium text-tertiary">Phân loại đối tượng</dt>
                <dd className="mt-0.5 font-mono text-xs text-secondary">
                  {selectedLog.target_type}
                  {selectedLog.target_id != null ? ` (#${selectedLog.target_id})` : ''}
                </dd>
              </div>
            </dl>

            {selectedLog.note && (
              <div>
                <h3 className="mb-1.5 text-xs font-semibold tracking-wide text-tertiary uppercase">Ghi chú</h3>
                <p className="rounded-xl bg-secondary p-3 text-sm whitespace-pre-wrap text-secondary">
                  {selectedLog.note}
                </p>
              </div>
            )}

            {selectedLog.before && (
              <div>
                <h3 className="mb-1.5 text-xs font-semibold tracking-wide text-tertiary uppercase">Giá trị trước</h3>
                <pre className="overflow-x-auto rounded-xl bg-secondary p-3 font-mono text-xs text-secondary">
                  {JSON.stringify(selectedLog.before, null, 2)}
                </pre>
              </div>
            )}

            {selectedLog.after && (
              <div>
                <h3 className="mb-1.5 text-xs font-semibold tracking-wide text-tertiary uppercase">Giá trị sau</h3>
                <pre className="overflow-x-auto rounded-xl bg-secondary p-3 font-mono text-xs text-secondary">
                  {JSON.stringify(selectedLog.after, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </Slideover>
    </div>
  )
}
