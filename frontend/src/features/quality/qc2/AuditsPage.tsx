import { AlertCircle } from '@untitledui/icons'
import { useState } from 'react'
import { Table } from '@/components/application/table/table'
import { Tabs } from '@/components/application/tabs/tabs'
import { Badge } from '@/components/base/badges/badges'
import type { BadgeColors } from '@/components/base/badges/badge-types'
import { Button } from '@/components/base/buttons/button'
import { ProgressBarBase } from '@/components/base/progress-indicators/progress-indicators'
import { getErrorMessage } from '../../../shared/api/errors'
import StateView from '../../../shared/components/StateView'
import UserName from '../../../shared/components/UserName'
import EmptyRow from '../../../shared/components/ui/EmptyRow'
import SectionCard from '../../../shared/components/ui/SectionCard'
import Slideover from '../../../shared/components/ui/Slideover'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import MemberSelect from '../../projects/components/MemberSelect'
import { useProject } from '../../projects/projectContext'
import { assignSampleAuditor, listAuditSamples, listAudits } from '../api'
import { RESULT_LABELS } from '../constants'
import type { Audit, AuditSample } from '../types'

type AuditTab = 'in_progress' | 'completed' | 'all'

const AUDIT_TABS: { id: AuditTab; label: string }[] = [
  { id: 'in_progress', label: 'Đang kiểm' },
  { id: 'completed', label: 'Đã chốt' },
  { id: 'all', label: 'Tất cả' },
]

const RESULT_BADGE_COLORS: Record<AuditSample['result'], BadgeColors> = {
  pending: 'gray',
  pass: 'success',
  reject: 'error',
}

const SAMPLE_PAGE_SIZE = 20

/**
 * PM-09 Audit QC2 — theo dõi QC2 theo từng task (chỉ PM).
 * Quy tắc (chốt 2026-11-25): MỌI job qua QC1 đều vào QC2, mỗi job kiểm ngẫu nhiên một tỉ lệ % frame.
 * Đợt QC2 của task tự tạo khi job đầu tiên vào Chờ QC2 và tự chốt khi task bàn giao — PM không tạo tay.
 * PM chỉ phân lại người kiểm khi cần (lượt QC2 tự giao cho người QC2 đang ít việc nhất).
 */
export default function AuditsPage() {
  const { projectId } = useProject()
  const [tab, setTab] = useState<AuditTab>('in_progress')
  const [version, setVersion] = useState(0)
  const [openAudit, setOpenAudit] = useState<Audit | null>(null)
  const status = tab === 'all' ? '' : tab
  const audits = useRequest(`audits:${projectId}:${status}:${version}`, () => listAudits(projectId, { status }))
  const samples = useRequest(`samples:${projectId}:${openAudit?.id}:${version}`, () =>
    openAudit ? listAuditSamples(projectId, { audit: openAudit.id }) : Promise.resolve([] as AuditSample[]),
  )
  const reload = () => setVersion((v) => v + 1)
  const activeAudit = openAudit ? (audits.data?.find((a) => a.id === openAudit.id) ?? openAudit) : null

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 md:p-6">
      <header>
        <h1 className="text-display-xs font-semibold text-primary">Audit QC2 theo task</h1>
        <p className="mt-1 text-sm text-tertiary">
          Mọi job qua QC1 đều được QC2 kiểm một phần frame. Đợt QC2 của task tự tạo khi có job chờ QC2 và tự chốt khi bàn giao task.
        </p>
      </header>

      <SectionCard bodyClassName="p-0">
        <div className="border-b border-secondary p-4">
          <Tabs selectedKey={tab} onSelectionChange={(k) => setTab(k as AuditTab)} className="w-auto">
            <Tabs.List type="button-gray" size="sm" aria-label="Trạng thái đợt QC2">
              {AUDIT_TABS.map((t) => (
                <Tabs.Item key={t.id} id={t.id} label={t.label} />
              ))}
            </Tabs.List>
          </Tabs>
        </div>

        {audits.error != null ? (
          <StateView kind="error" description={getErrorMessage(audits.error)} action={{ label: 'Thử lại', onClick: audits.retry }} />
        ) : (
          <Table aria-label="Bảng audit QC2 theo task" size="sm">
            <Table.Header>
              <Table.Head id="task" label="Task" isRowHeader />
              <Table.Head id="project" label="Project" />
              <Table.Head id="sample_count" label="Lượt QC2" />
              <Table.Head id="result" label="Kết quả" />
              <Table.Head id="status" label="Trạng thái" />
              <Table.Head id="created_at" label="Bắt đầu" />
            </Table.Header>
            <Table.Body
              items={audits.data ?? []}
              renderEmptyState={() => <EmptyRow text={audits.isLoading ? 'Đang tải…' : 'Chưa có job nào tới bước QC2'} />}
            >
              {(a) => {
                const percent = a.sample_count ? Math.round(((a.passed + a.rejected) * 100) / a.sample_count) : 0
                return (
                  <Table.Row id={a.id}>
                    <Table.Cell>
                      <button
                        type="button"
                        onClick={() => setOpenAudit(a)}
                        className="cursor-pointer rounded text-left font-medium text-brand-secondary outline-focus-ring hover:underline focus-visible:outline-2 focus-visible:outline-offset-2"
                      >
                        {a.batch_name}
                      </button>
                    </Table.Cell>
                    <Table.Cell className="text-secondary">{a.dataset_name}</Table.Cell>
                    <Table.Cell className="tabular-nums">{a.sample_count}</Table.Cell>
                    <Table.Cell>
                      <div className="flex w-56 flex-col gap-1.5">
                        <div className="flex items-center gap-2.5">
                          <ProgressBarBase value={percent} />
                          <span className="w-9 shrink-0 text-right text-xs font-medium text-secondary tabular-nums">{percent}%</span>
                        </div>
                        <span className="text-xs text-tertiary tabular-nums">
                          Pass {a.passed} · Reject {a.rejected} · Chờ {a.pending}
                        </span>
                      </div>
                    </Table.Cell>
                    <Table.Cell>
                      <Badge type="pill-color" size="sm" color={a.status === 'completed' ? 'success' : 'brand'}>
                        {a.status === 'completed' ? 'Đã chốt' : 'Đang kiểm'}
                      </Badge>
                    </Table.Cell>
                    <Table.Cell className="whitespace-nowrap tabular-nums">{formatDateTime(a.created_at)}</Table.Cell>
                  </Table.Row>
                )
              }}
            </Table.Body>
          </Table>
        )}
      </SectionCard>

      <Slideover
        isOpen={openAudit !== null}
        onClose={() => setOpenAudit(null)}
        maxWidthClass="max-w-215"
        title={openAudit ? `QC2 · ${openAudit.dataset_name} / ${openAudit.batch_name}` : ''}
      >
        {activeAudit && (
          <AuditSamplesBody
            key={activeAudit.id}
            projectId={projectId}
            audit={activeAudit}
            samples={samples.data ?? []}
            isLoading={samples.isLoading}
            error={samples.error}
            onRetry={samples.retry}
            onReload={reload}
          />
        )}
      </Slideover>
    </div>
  )
}

function AuditSamplesBody({
  projectId,
  audit,
  samples,
  isLoading,
  error,
  onRetry,
  onReload,
}: {
  projectId: number
  audit: Audit
  samples: AuditSample[]
  isLoading: boolean
  error: unknown
  onRetry: () => void
  onReload: () => void
}) {
  const { run, pending } = useAction()
  const [page, setPage] = useState(1)

  const totalPages = Math.max(1, Math.ceil(samples.length / SAMPLE_PAGE_SIZE))
  const safePage = Math.min(page, totalPages)
  const pagedSamples = samples.slice((safePage - 1) * SAMPLE_PAGE_SIZE, safePage * SAMPLE_PAGE_SIZE)

  return (
    <div className="flex flex-col gap-4">
      {error != null && (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-xl bg-error-primary p-3.5 ring-1 ring-error_subtle ring-inset">
          <div className="flex items-start gap-3">
            <AlertCircle className="mt-0.5 size-5 shrink-0 text-fg-error-primary" aria-hidden="true" />
            <p className="text-sm font-medium text-error-primary">{getErrorMessage(error)}</p>
          </div>
          <Button size="xs" color="secondary" onPress={onRetry}>
            Thử lại
          </Button>
        </div>
      )}

      <SectionCard bodyClassName="p-0">
        <Table aria-label="Danh sách lượt kiểm QC2" size="sm">
          <Table.Header>
            <Table.Head id="job" label="Job" isRowHeader />
            <Table.Head id="frames" label="Frame kiểm" />
            <Table.Head id="annotator" label="Annotator" />
            <Table.Head id="auditor" label="Người kiểm" />
            <Table.Head id="result" label="Kết quả" />
            <Table.Head id="errors" label="Lỗi" />
          </Table.Header>
          <Table.Body
            items={pagedSamples}
            renderEmptyState={() => <EmptyRow text={isLoading ? 'Đang tải…' : 'Chưa có lượt audit QC2'} />}
          >
            {(s) => (
              <Table.Row id={s.id}>
                <Table.Cell>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-medium text-primary">{s.job.name}</span>
                    {s.rework_round > 0 && (
                      <Badge type="pill-color" size="sm" color="gray">
                        vòng {s.rework_round}
                      </Badge>
                    )}
                  </div>
                </Table.Cell>
                <Table.Cell className="whitespace-nowrap tabular-nums">
                  {s.frames.length}/{s.job.frame_count}
                </Table.Cell>
                <Table.Cell>
                  <UserName user={s.job.annotator} />
                </Table.Cell>
                <Table.Cell>
                  {s.result === 'pending' && audit.status === 'in_progress' ? (
                    <MemberSelect
                      projectId={projectId}
                      role="qc2"
                      size="sm"
                      className="w-48"
                      popoverClassName="w-72"
                      value={s.auditor?.id}
                      allowClear={false}
                      placeholder="Chưa phân"
                      disabled={pending}
                      onChange={async (v) => {
                        if (v != null && (await run(() => assignSampleAuditor(projectId, s.id, v), 'Đã phân người kiểm'))) {
                          onReload()
                        }
                      }}
                    />
                  ) : (
                    <UserName user={s.auditor} />
                  )}
                </Table.Cell>
                <Table.Cell>
                  <Badge type="pill-color" size="sm" color={RESULT_BADGE_COLORS[s.result]}>
                    {RESULT_LABELS[s.result]}
                  </Badge>
                </Table.Cell>
                <Table.Cell className="tabular-nums">
                  {s.errors.length || <span className="text-quaternary">—</span>}
                </Table.Cell>
              </Table.Row>
            )}
          </Table.Body>
        </Table>

        {samples.length > SAMPLE_PAGE_SIZE && (
          <div className="flex items-center justify-between border-t border-secondary px-5 py-3 text-sm text-tertiary">
            <span className="tabular-nums">
              Trang {safePage} / {totalPages} · {samples.length} lượt
            </span>
            <div className="flex gap-2">
              <Button size="xs" color="secondary" isDisabled={safePage <= 1} onPress={() => setPage((p) => p - 1)}>
                Trước
              </Button>
              <Button size="xs" color="secondary" isDisabled={safePage >= totalPages} onPress={() => setPage((p) => p + 1)}>
                Sau
              </Button>
            </div>
          </div>
        )}
      </SectionCard>
    </div>
  )
}
