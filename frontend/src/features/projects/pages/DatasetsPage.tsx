import { AlertTriangle, ChevronDown, ChevronRight, Edit05, LinkExternal01, Lock01, LockUnlocked01, SearchLg } from '@untitledui/icons'
import { Fragment, useState } from 'react'
import { Link } from 'react-router'
import { Tabs } from '@/components/application/tabs/tabs'
import { Button } from '@/components/base/buttons/button'
import { Input } from '@/components/base/input/input'
import { ProgressBarBase } from '@/components/base/progress-indicators/progress-indicators'
import { TextArea } from '@/components/base/textarea/textarea'
import { getErrorMessage } from '../../../shared/api/errors'
import FormDialog from '../../../shared/components/ui/FormDialog'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { cvatProjectUrl } from '../../../shared/utils/cvat'
import { formatDateTime } from '../../../shared/utils/format'
import { getCvatStatus, getDatasetLabels, listDatasets, setDatasetLock, updateDataset } from '../api'
import CvatSyncButton from '../components/CvatSyncButton'
import DataStatusBadge from '../components/DataStatusBadge'
import { useProject } from '../projectContext'
import type { Dataset } from '../types'

const TABS = [
  { id: '', label: 'Tất cả' },
  { id: 'active', label: 'Đang xử lý' },
  { id: 'locked', label: 'Đã khoá' },
  { id: 'delivered', label: 'Đã bàn giao' },
]

/**
 * Projects — các CVAT project trong organization (model Dataset).
 * Project (bộ nhãn) và task tạo trên CVAT → PM bấm "Đồng bộ CVAT" để kéo về.
 * Trên VanoHub chỉ khoá / mở khoá; deadline và team phụ trách đặt ở trang Tasks.
 */
export default function DatasetsPage() {
  const { project: org, projectId, can } = useProject()
  const [status, setStatus] = useState('')
  const [search, setSearch] = useState('')
  const [version, setVersion] = useState(0)
  const [open, setOpen] = useState<number | null>(null)
  const [editing, setEditing] = useState<Dataset | null>(null)
  const { run } = useAction()
  const { data, error, isLoading, retry } = useRequest(`datasets:${projectId}:${status}:${version}`, () =>
    listDatasets(projectId, { status }),
  )
  const { data: cvat, retry: retryCvat } = useRequest('cvat-status', getCvatStatus)
  const reload = () => setVersion((v) => v + 1)
  const canManage = can('manage_data')
  const linked = org.cvat_org_id != null
  const cvatBase = cvat?.url?.replace(/\/$/, '') ?? ''
  const cvatDisconnected = cvat?.connected === false

  const keyword = search.trim().toLowerCase()
  const rows = (data ?? []).filter((d) => !keyword || d.name.toLowerCase().includes(keyword))

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Projects</h1>
          <p className="mt-1 text-sm text-tertiary">
            Các project trong organization <span className="font-medium text-secondary">{org.name}</span> trên CVAT.
            Tạo project và task trên CVAT; bấm Đồng bộ để cập nhật.
          </p>
        </div>
        {canManage && linked && <CvatSyncButton projectId={projectId} onDone={reload} disabled={cvatDisconnected} />}
      </header>

      {!linked && (
        <div className="rounded-xl bg-secondary p-4 text-sm text-tertiary">
          Organization này chưa gắn với CVAT organization (dữ liệu demo / tạo tay) — không đồng bộ được từ CVAT.
        </div>
      )}

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
          <Tabs selectedKey={status} onSelectionChange={(k) => setStatus(String(k))} className="w-auto">
            <Tabs.List type="button-gray" size="sm" aria-label="Lọc theo trạng thái">
              {TABS.map((t) => <Tabs.Item key={t.id} id={t.id} label={t.label} />)}
            </Tabs.List>
          </Tabs>
          <Input className="min-w-48 flex-1" size="sm" icon={SearchLg} aria-label="Tìm project" placeholder="Tìm project" value={search} onChange={setSearch} />
        </div>
        {error != null ? (
          <PageState kind="error" description={getErrorMessage(error)} onRetry={retry} />
        ) : isLoading && !data ? (
          <PageState kind="loading" />
        ) : rows.length === 0 ? (
          <PageState kind="empty" title="Chưa có project" description={linked ? 'Bấm "Đồng bộ CVAT" để kéo project từ CVAT về.' : undefined} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-secondary text-xs font-semibold text-quaternary">
                <tr>
                  <th className="w-10" />
                  <th className="px-3 py-2.5 text-left">Project</th>
                  <th className="px-3 py-2.5 text-right">Task</th>
                  <th className="px-3 py-2.5 text-left">Tiến độ job</th>
                  <th className="px-3 py-2.5 text-left">Trạng thái</th>
                  <th className="px-3 py-2.5 text-left">Đồng bộ lần cuối</th>
                  <th className="px-5 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {rows.map((d) => {
                  const percent = d.job_count ? Math.round((d.done_count * 100) / d.job_count) : 0
                  const expanded = open === d.id
                  const projectHref = d.cvat_project_id ? cvatProjectUrl(cvatBase, d.cvat_project_id, org.cvat_org_slug) : ''
                  return (
                    <Fragment key={d.id}>
                      <tr className="border-t border-secondary">
                        <td className="pl-3">
                          <button type="button" aria-label={expanded ? 'Ẩn bộ nhãn' : 'Xem bộ nhãn'} aria-expanded={expanded}
                            onClick={() => setOpen(expanded ? null : d.id)}
                            className="rounded-md p-1 text-fg-quaternary hover:bg-primary_hover">
                            {expanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                          </button>
                        </td>
                        <td className="px-3 py-3">
                          <Link to={`../batches?dataset=${d.id}`} relative="path" className="font-medium text-primary hover:underline">{d.name}</Link>
                          {d.description && (
                            <p className="mt-0.5 max-w-md text-xs text-secondary">{d.description}</p>
                          )}
                          {d.cvat_project_id && (
                            <div className="text-xs text-tertiary">
                              CVAT project #{d.cvat_project_id}
                              {projectHref && (
                                <a href={projectHref} target="_blank" rel="noreferrer"
                                  className="ml-1.5 inline-flex items-center gap-0.5 text-brand-secondary hover:underline">
                                  Mở <LinkExternal01 className="size-3" />
                                </a>
                              )}
                            </div>
                          )}
                        </td>
                        <td className="px-3 py-3 text-right tabular-nums">
                          <Link to={`../batches?dataset=${d.id}`} relative="path" className="hover:underline">{d.task_count}</Link>
                        </td>
                        <td className="px-3 py-3">
                          <div className="flex w-44 items-center gap-3">
                            <ProgressBarBase value={percent} />
                            <span className="w-16 text-right text-xs text-tertiary tabular-nums">{d.done_count}/{d.job_count}</span>
                          </div>
                        </td>
                        <td className="px-3 py-3"><DataStatusBadge status={d.status} /></td>
                        <td className="px-3 py-3 whitespace-nowrap">{formatDateTime(d.last_synced_at)}</td>
                        <td className="px-5 py-3 text-right">
                          {canManage && d.status !== 'delivered' && (
                            <div className="flex items-center justify-end gap-2">
                              {d.status === 'active' && (
                                <Button size="sm" color="link-color" iconLeading={Edit05} onPress={() => setEditing(d)}>
                                  Mô tả
                                </Button>
                              )}
                              <Button size="sm" color="link-gray" iconLeading={d.status === 'active' ? Lock01 : LockUnlocked01}
                                onPress={async () => (await run(() => setDatasetLock(projectId, d.id, d.status === 'active'),
                                  d.status === 'active' ? 'Đã khoá project' : 'Đã mở khoá')) && reload()}>
                                {d.status === 'active' ? 'Khoá' : 'Mở khoá'}
                              </Button>
                            </div>
                          )}
                        </td>
                      </tr>
                      {expanded && (
                        <tr className="bg-secondary">
                          <td />
                          <td colSpan={6} className="px-3 pb-4"><Labels projectId={projectId} datasetId={d.id} /></td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>

      {editing && (
        <DatasetDescriptionDialog
          key={editing.id}
          projectId={projectId}
          dataset={editing}
          onClose={() => setEditing(null)}
          onDone={() => {
            setEditing(null)
            reload()
          }}
        />
      )}
    </div>
  )
}

function DatasetDescriptionDialog({
  projectId,
  dataset,
  onClose,
  onDone,
}: {
  projectId: number
  dataset: Dataset
  onClose: () => void
  onDone: () => void
}) {
  const [description, setDescription] = useState(dataset.description ?? '')
  const { run, pending } = useAction()

  async function submit() {
    if (
      await run(
        () => updateDataset(projectId, dataset.id, { description: description.trim() }),
        `Đã cập nhật mô tả cho ${dataset.name}`,
      )
    ) {
      onDone()
    }
  }

  return (
    <FormDialog
      isOpen
      title={`Cập nhật mô tả — ${dataset.name}`}
      submitLabel="Lưu mô tả"
      onClose={onClose}
      onSubmit={submit}
      pending={pending}
    >
      <TextArea
        label="Mô tả project"
        rows={4}
        value={description}
        onChange={setDescription}
        placeholder="Ghi chú phạm vi dữ liệu, quy chuẩn hoặc lưu ý vận hành cho project này…"
      />
    </FormDialog>
  )
}

/** Bộ nhãn đặt trên CVAT project — chỉ xem. */
function Labels({ projectId, datasetId }: { projectId: number; datasetId: number }) {
  const { data, isLoading } = useRequest(`dataset-labels:${projectId}:${datasetId}`, () => getDatasetLabels(projectId, datasetId))
  return (
    <div>
      <p className="mb-2 text-xs font-semibold text-tertiary">Bộ nhãn (đặt trên CVAT project, chỉ xem)</p>
      {isLoading ? <p className="text-sm text-tertiary">Đang tải…</p>
        : data?.detail ? <p className="text-sm text-warning-primary">Không đọc được nhãn từ CVAT: {data.detail}</p>
          : !data?.labels.length ? <p className="text-sm text-tertiary">Project chưa có nhãn.</p>
            : (
              <ul className="flex flex-wrap gap-2">
                {data.labels.map((l) => (
                  <li key={l.id} className="inline-flex items-center gap-1.5 rounded-md bg-primary px-2 py-1 text-sm text-secondary ring-1 ring-secondary ring-inset">
                    <span aria-hidden className="size-2.5 rounded-full" style={{ backgroundColor: l.color || '#98a2b3' }} />
                    {l.name}
                    {l.type && l.type !== 'any' && <span className="text-xs text-quaternary">{l.type}</span>}
                  </li>
                ))}
              </ul>
            )}
    </div>
  )
}
