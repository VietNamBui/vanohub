import { Edit05, InfoCircle, PackageCheck } from '@untitledui/icons'
import { useState } from 'react'
import { Table } from '@/components/application/table/table'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { ProgressBarBase } from '@/components/base/progress-indicators/progress-indicators'
import { TextArea } from '@/components/base/textarea/textarea'
import { getErrorMessage } from '../../../shared/api/errors'
import EmptyRow from '../../../shared/components/ui/EmptyRow'
import FormDialog from '../../../shared/components/ui/FormDialog'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import { createDelivery, listDeliveries, listDeliveryCandidates, updateDelivery } from '../api'
import { useProject } from '../projectContext'
import type { Delivery, DeliveryCandidate } from '../types'

/** Bàn giao task cho khách hàng khi mọi job đã ở trạng thái Đã duyệt và không còn đợt QC2 mở. */
export default function DeliveryPage() {
  const { projectId } = useProject()
  const [version, setVersion] = useState(0)
  const [delivering, setDelivering] = useState<DeliveryCandidate | null>(null)
  const [feedbackFor, setFeedbackFor] = useState<Delivery | null>(null)
  const candidates = useRequest(`delivery-candidates:${projectId}:${version}`, () => listDeliveryCandidates(projectId))
  const history = useRequest(`deliveries:${projectId}:${version}`, () => listDeliveries(projectId))
  const reload = () => setVersion((v) => v + 1)

  const candidateRows = (candidates.data ?? []).map((c) => ({ ...c, id: c.batch }))
  const historyRows = history.data ?? []

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 md:p-6">
      <header>
        <h1 className="text-display-xs font-semibold text-primary">Delivery</h1>
        <p className="mt-1 text-sm text-tertiary">Bàn giao task cho khách hàng khi đủ điều kiện.</p>
      </header>

      <div className="flex items-start gap-3 rounded-xl bg-brand-primary_alt p-4 ring-1 ring-brand ring-inset">
        <InfoCircle className="mt-0.5 size-5 shrink-0 text-fg-brand-primary" />
        <p className="text-sm text-secondary">
          Quy tắc hiện hành: chỉ bàn giao khi mọi job trong task đã ở trạng thái Đã duyệt và task không còn đợt QC2 đang mở.
        </p>
      </div>

      <SectionCard title="Task chờ bàn giao" bodyClassName="p-0">
        {candidates.error != null ? (
          <PageState kind="error" description={getErrorMessage(candidates.error)} onRetry={candidates.retry} />
        ) : (
          <Table aria-label="Task chờ bàn giao" size="sm">
            <Table.Header>
              <Table.Head id="task" label="Task" isRowHeader />
              <Table.Head id="approved" label="Đã duyệt" />
              <Table.Head id="audits" label="Đợt QC2 đang mở" />
              <Table.Head id="ready" label="Điều kiện" />
              <Table.Head id="actions" />
            </Table.Header>
            <Table.Body
              items={candidateRows}
              renderEmptyState={() => <EmptyRow text={candidates.isLoading ? 'Đang tải…' : 'Không có task nào đang chờ'} />}
            >
              {(c) => {
                const percent = c.job_count ? Math.round((c.approved_count * 100) / c.job_count) : 0
                return (
                  <Table.Row id={c.id}>
                    <Table.Cell className="font-medium text-primary">
                      {c.dataset_name ? `${c.dataset_name} / ${c.batch_name}` : c.batch_name}
                    </Table.Cell>
                    <Table.Cell>
                      <div className="flex w-44 items-center gap-3">
                        <ProgressBarBase value={percent} />
                        <span className="w-14 text-right text-xs text-tertiary tabular-nums">
                          {c.approved_count}/{c.job_count}
                        </span>
                      </div>
                    </Table.Cell>
                    <Table.Cell className="tabular-nums">
                      {c.open_audits > 0 ? (
                        <Badge type="pill-color" size="sm" color="warning">{c.open_audits}</Badge>
                      ) : (
                        <span className="text-quaternary">0</span>
                      )}
                    </Table.Cell>
                    <Table.Cell>
                      {c.ready ? (
                        <Badge type="pill-color" size="sm" color="success">Đủ điều kiện</Badge>
                      ) : (
                        <Badge type="pill-color" size="sm" color="gray">Chưa đủ</Badge>
                      )}
                    </Table.Cell>
                    <Table.Cell className="text-right">
                      <Button
                        size="xs"
                        color="primary"
                        iconLeading={PackageCheck}
                        isDisabled={!c.ready}
                        onPress={() => setDelivering(c)}
                      >
                        Tạo delivery
                      </Button>
                    </Table.Cell>
                  </Table.Row>
                )
              }}
            </Table.Body>
          </Table>
        )}
      </SectionCard>

      <SectionCard title="Lịch sử bàn giao" bodyClassName="p-0">
        {history.error != null ? (
          <PageState kind="error" description={getErrorMessage(history.error)} onRetry={history.retry} />
        ) : (
          <Table aria-label="Lịch sử bàn giao" size="sm">
            <Table.Header>
              <Table.Head id="task" label="Task" isRowHeader />
              <Table.Head id="jobs" label="Số job" />
              <Table.Head id="by" label="Người bàn giao" />
              <Table.Head id="at" label="Thời gian" />
              <Table.Head id="note" label="Ghi chú" />
              <Table.Head id="feedback" label="Phản hồi khách hàng" />
              <Table.Head id="actions" />
            </Table.Header>
            <Table.Body
              items={historyRows}
              renderEmptyState={() => <EmptyRow text={history.isLoading ? 'Đang tải…' : 'Chưa bàn giao lần nào'} />}
            >
              {(d) => (
                <Table.Row id={d.id}>
                  <Table.Cell className="font-medium text-primary">
                    {d.dataset_name ? `${d.dataset_name} / ${d.batch_name}` : d.batch_name}
                  </Table.Cell>
                  <Table.Cell className="tabular-nums">{d.job_count}</Table.Cell>
                  <Table.Cell>
                    {d.delivered_by ? (
                      <span title={d.delivered_by.username} className="text-secondary">{d.delivered_by.full_name}</span>
                    ) : (
                      <span className="text-quaternary">—</span>
                    )}
                  </Table.Cell>
                  <Table.Cell className="whitespace-nowrap">{formatDateTime(d.delivered_at)}</Table.Cell>
                  <Table.Cell className="max-w-48 truncate" title={d.note || undefined}>
                    {d.note || <span className="text-quaternary">—</span>}
                  </Table.Cell>
                  <Table.Cell className="max-w-52 truncate" title={d.client_feedback || undefined}>
                    {d.client_feedback || <span className="text-quaternary">—</span>}
                  </Table.Cell>
                  <Table.Cell className="text-right">
                    <Button size="xs" color="link-color" iconLeading={Edit05} onPress={() => setFeedbackFor(d)}>
                      Ghi phản hồi
                    </Button>
                  </Table.Cell>
                </Table.Row>
              )}
            </Table.Body>
          </Table>
        )}
      </SectionCard>

      {delivering && (
        <DeliverDialog
          projectId={projectId}
          candidate={delivering}
          onClose={() => setDelivering(null)}
          onDone={() => {
            setDelivering(null)
            reload()
          }}
        />
      )}

      {feedbackFor && (
        <FeedbackDialog
          projectId={projectId}
          delivery={feedbackFor}
          onClose={() => setFeedbackFor(null)}
          onDone={() => {
            setFeedbackFor(null)
            reload()
          }}
        />
      )}
    </div>
  )
}

function DeliverDialog({
  projectId,
  candidate,
  onClose,
  onDone,
}: {
  projectId: number
  candidate: DeliveryCandidate
  onClose: () => void
  onDone: () => void
}) {
  const [note, setNote] = useState('')
  const { run, pending } = useAction()
  const taskLabel = candidate.dataset_name ? `${candidate.dataset_name} / ${candidate.batch_name}` : candidate.batch_name

  async function submit() {
    if (await run(() => createDelivery(projectId, { batch: candidate.batch, note: note.trim() }), 'Đã bàn giao')) {
      onDone()
    }
  }

  return (
    <FormDialog
      isOpen
      title={`Bàn giao ${candidate.batch_name}`}
      description={`${taskLabel} · ${candidate.job_count} job sẽ chuyển sang trạng thái Đã bàn giao và task bị khoá.`}
      submitLabel="Bàn giao"
      onClose={onClose}
      onSubmit={submit}
      pending={pending}
    >
      <TextArea label="Ghi chú" rows={3} value={note} onChange={setNote} placeholder="Ghi chú đợt bàn giao (tuỳ chọn)…" />
    </FormDialog>
  )
}

function FeedbackDialog({
  projectId,
  delivery,
  onClose,
  onDone,
}: {
  projectId: number
  delivery: Delivery
  onClose: () => void
  onDone: () => void
}) {
  const [clientFeedback, setClientFeedback] = useState(delivery.client_feedback ?? '')
  const [note, setNote] = useState(delivery.note ?? '')
  const { run, pending } = useAction()
  const taskLabel = delivery.dataset_name ? `${delivery.dataset_name} / ${delivery.batch_name}` : delivery.batch_name

  async function submit() {
    if (
      await run(
        () => updateDelivery(projectId, delivery.id, { client_feedback: clientFeedback.trim(), note: note.trim() }),
        'Đã lưu phản hồi',
      )
    ) {
      onDone()
    }
  }

  return (
    <FormDialog
      isOpen
      title="Phản hồi khách hàng"
      description={taskLabel}
      submitLabel="Lưu"
      onClose={onClose}
      onSubmit={submit}
      pending={pending}
    >
      <TextArea
        label="Phản hồi khách hàng"
        rows={4}
        value={clientFeedback}
        onChange={setClientFeedback}
        placeholder="Ghi nhận phản hồi từ khách hàng…"
      />
      <TextArea label="Ghi chú" rows={2} value={note} onChange={setNote} placeholder="Ghi chú nội bộ…" />
    </FormDialog>
  )
}
