import { Edit05, InfoCircle, PackageCheck } from '@untitledui/icons'
import { useState } from 'react'
import { Table } from '@/components/application/table/table'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { Input } from '@/components/base/input/input'
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
import { computeDeliveryDh07Summary, validateDeliveryUpdateInput } from '../projectHelpers'
import { useProject } from '../projectContext'
import type { Delivery, DeliveryCandidate, DueState } from '../types'

const HTTP_URL_RE = /^https?:\/\//i

function DueStateBadge({ state }: { state: DueState }) {
  if (state === 'overdue') return <Badge type="pill-color" size="sm" color="error">Quá hạn</Badge>
  if (state === 'soon') return <Badge type="pill-color" size="sm" color="warning">Sắp hạn</Badge>
  if (state === 'normal') return <Badge type="pill-color" size="sm" color="gray">Còn hạn</Badge>
  return <span className="text-xs text-quaternary">Chưa đặt hạn</span>
}

/** Bàn giao task cho khách hàng khi mọi job đã ở trạng thái Đã duyệt, không có job khoá và không còn mẫu QC2 chờ kiểm. */
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
  const dh07 = computeDeliveryDh07Summary(historyRows, candidateRows)

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-5 p-4 md:p-6">
      <header>
        <h1 className="text-display-xs font-semibold text-primary">Delivery</h1>
        <p className="mt-1 text-sm text-tertiary">Bàn giao task cho khách hàng khi đủ điều kiện.</p>
      </header>

      <div className="flex items-start gap-3 rounded-xl bg-brand-primary_alt p-4 ring-1 ring-brand ring-inset">
        <InfoCircle className="mt-0.5 size-5 shrink-0 text-fg-brand-primary" />
        <p className="text-sm text-secondary">
          Quy tắc hiện hành: chỉ bàn giao khi Project và Task đang hoạt động, mọi job trong task đã ở trạng thái Đã duyệt, không còn job bị khoá và không còn mẫu QC2 chờ kiểm.
        </p>
      </div>

      {dh07.dueCount > 0 && (
        <div className="flex flex-wrap items-center gap-3 rounded-xl bg-primary px-4 py-3 text-sm text-secondary ring-1 ring-secondary">
          <span className="font-semibold text-primary">Tỷ lệ bàn giao đúng hạn (DH07):</span>
          <Badge type="pill-color" size="sm" color={dh07.rate != null && dh07.rate >= 90 ? 'success' : 'warning'}>
            {dh07.rate != null ? `${dh07.rate}%` : '—'}
          </Badge>
          <span className="text-xs text-tertiary tabular-nums">
            Đúng hạn: {dh07.onTimeCount}/{dh07.dueCount} · Trễ hạn: {dh07.lateCount} · Quá hạn chưa giao: {dh07.overdueUndeliveredCount}
          </span>
        </div>
      )}

      <SectionCard title="Task chờ bàn giao" bodyClassName="p-0">
        {candidates.error != null ? (
          <PageState kind="error" description={getErrorMessage(candidates.error)} onRetry={candidates.retry} />
        ) : (
          <Table aria-label="Task chờ bàn giao" size="sm">
            <Table.Header>
              <Table.Head id="task" label="Task" isRowHeader />
              <Table.Head id="deadline" label="Deadline" />
              <Table.Head id="approved" label="Đã duyệt" />
              <Table.Head id="samples" label="Mẫu QC2 chờ kiểm" />
              <Table.Head id="ready" label="Điều kiện" />
              <Table.Head id="actions" />
            </Table.Header>
            <Table.Body
              items={candidateRows}
              renderEmptyState={() => <EmptyRow text={candidates.isLoading ? 'Đang tải…' : 'Không có task nào đang chờ'} />}
            >
              {(c) => {
                const percent = c.job_count ? Math.round((c.approved_count * 100) / c.job_count) : 0
                const pendingSamples = c.pending_qc2_samples ?? c.open_audits
                const blockReason =
                  c.status !== 'active' || c.dataset_status !== 'active'
                    ? 'Project/Task đang khoá'
                    : c.locked_jobs > 0
                      ? `${c.locked_jobs} job đang khoá`
                      : null
                return (
                  <Table.Row id={c.id}>
                    <Table.Cell className="font-medium text-primary">
                      {c.dataset_name ? `${c.dataset_name} / ${c.batch_name}` : c.batch_name}
                    </Table.Cell>
                    <Table.Cell>
                      <div className="flex flex-col items-start gap-1">
                        <span className="text-xs whitespace-nowrap text-secondary tabular-nums">
                          {formatDateTime(c.deadline)}
                        </span>
                        <DueStateBadge state={c.due_state} />
                      </div>
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
                      <div className="flex flex-col items-start gap-1">
                        {pendingSamples > 0 ? (
                          <Badge type="pill-color" size="sm" color="warning">{pendingSamples}</Badge>
                        ) : (
                          <span className="text-quaternary">0</span>
                        )}
                        {c.in_progress_audits > 0 && (
                          <span className="text-xs text-tertiary">{c.in_progress_audits} đợt đang mở</span>
                        )}
                      </div>
                    </Table.Cell>
                    <Table.Cell>
                      <div className="flex flex-col items-start gap-1">
                        {c.ready ? (
                          <Badge type="pill-color" size="sm" color="success">Đủ điều kiện</Badge>
                        ) : (
                          <Badge type="pill-color" size="sm" color="gray">Chưa đủ</Badge>
                        )}
                        {blockReason && <span className="text-xs text-tertiary">{blockReason}</span>}
                      </div>
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
              <Table.Head id="deadline" label="Deadline" />
              <Table.Head id="on_time" label="Đúng hạn" />
              <Table.Head id="recipient" label="Người nhận" />
              <Table.Head id="output" label="Đường dẫn đầu ra" />
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
                  <Table.Cell className="whitespace-nowrap tabular-nums">{formatDateTime(d.deadline)}</Table.Cell>
                  <Table.Cell>
                    {d.is_on_time === true ? (
                      <Badge type="pill-color" size="sm" color="success">Đúng hạn</Badge>
                    ) : d.is_on_time === false ? (
                      <Badge type="pill-color" size="sm" color="error">Trễ hạn</Badge>
                    ) : (
                      <span className="text-quaternary">—</span>
                    )}
                  </Table.Cell>
                  <Table.Cell className="max-w-44 truncate text-secondary" title={d.recipient || undefined}>
                    {d.recipient || <span className="text-quaternary">—</span>}
                  </Table.Cell>
                  <Table.Cell className="max-w-52 truncate" title={d.output_path || undefined}>
                    {d.output_path ? (
                      HTTP_URL_RE.test(d.output_path) ? (
                        <a
                          href={d.output_path}
                          target="_blank"
                          rel="noreferrer"
                          className="text-brand-secondary hover:underline"
                        >
                          {d.output_path}
                        </a>
                      ) : (
                        <span className="font-mono text-xs text-secondary">{d.output_path}</span>
                      )
                    ) : (
                      <span className="text-quaternary">—</span>
                    )}
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
                  <Table.Cell className="max-w-44 truncate" title={d.note || undefined}>
                    {d.note || <span className="text-quaternary">—</span>}
                  </Table.Cell>
                  <Table.Cell className="max-w-48 truncate" title={d.client_feedback || undefined}>
                    {d.client_feedback || <span className="text-quaternary">—</span>}
                  </Table.Cell>
                  <Table.Cell className="text-right">
                    <Button size="xs" color="link-color" iconLeading={Edit05} onPress={() => setFeedbackFor(d)}>
                      Cập nhật
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
          key={delivering.batch}
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
          key={feedbackFor.id}
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
  const [recipient, setRecipient] = useState('')
  const [outputPath, setOutputPath] = useState('')
  const [note, setNote] = useState('')
  const [showErrors, setShowErrors] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const { run, pending } = useAction()
  const taskLabel = candidate.dataset_name ? `${candidate.dataset_name} / ${candidate.batch_name}` : candidate.batch_name

  const recipientTrimmed = recipient.trim()
  const outputPathTrimmed = outputPath.trim()

  async function submit() {
    setShowErrors(true)
    setSubmitError(null)
    if (!recipientTrimmed || !outputPathTrimmed) return

    const created = await run(
      () =>
        createDelivery(projectId, {
          batch: candidate.batch,
          recipient: recipientTrimmed,
          output_path: outputPathTrimmed,
          note: note.trim(),
        }).catch((err: unknown) => {
          setSubmitError(getErrorMessage(err))
          throw err
        }),
      'Đã bàn giao',
    )
    if (created) onDone()
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
      <Input
        label="Người nhận / Khách hàng"
        size="sm"
        isRequired
        value={recipient}
        onChange={setRecipient}
        isInvalid={showErrors && !recipientTrimmed}
        hint={showErrors && !recipientTrimmed ? 'Vui lòng nhập người nhận bàn giao.' : undefined}
        placeholder="Tên khách hàng hoặc đơn vị nhận"
      />
      <Input
        label="Đường dẫn đầu ra / Link bàn giao"
        size="sm"
        isRequired
        value={outputPath}
        onChange={setOutputPath}
        isInvalid={showErrors && !outputPathTrimmed}
        hint={showErrors && !outputPathTrimmed ? 'Vui lòng nhập đường dẫn đầu ra.' : undefined}
        placeholder="VD: s3://bucket/path hoặc https://..."
      />
      <TextArea
        label="Ghi chú"
        rows={3}
        value={note}
        onChange={setNote}
        placeholder="Ghi chú đợt bàn giao (tuỳ chọn)…"
      />
      {submitError && <p className="text-sm text-error-primary">{submitError}</p>}
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
  const [recipient, setRecipient] = useState(delivery.recipient ?? '')
  const [outputPath, setOutputPath] = useState(delivery.output_path ?? '')
  const [clientFeedback, setClientFeedback] = useState(delivery.client_feedback ?? '')
  const [note, setNote] = useState(delivery.note ?? '')
  const [showErrors, setShowErrors] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const { run, pending } = useAction()
  const taskLabel = delivery.dataset_name ? `${delivery.dataset_name} / ${delivery.batch_name}` : delivery.batch_name

  const validation = validateDeliveryUpdateInput({
    recipient,
    output_path: outputPath,
    note,
    client_feedback: clientFeedback,
  })

  async function submit() {
    setShowErrors(true)
    setSubmitError(null)
    if (!validation.valid || !validation.payload) return
    const payload = validation.payload
    const updated = await run(
      () =>
        updateDelivery(projectId, delivery.id, payload).catch((err: unknown) => {
          setSubmitError(getErrorMessage(err))
          throw err
        }),
      'Đã cập nhật thông tin bàn giao',
    )
    if (updated) onDone()
  }

  return (
    <FormDialog
      isOpen
      title="Cập nhật thông tin bàn giao"
      description={taskLabel}
      submitLabel="Lưu thay đổi"
      onClose={onClose}
      onSubmit={submit}
      pending={pending}
    >
      <Input
        label="Người nhận / Khách hàng"
        size="sm"
        isRequired
        value={recipient}
        onChange={setRecipient}
        isInvalid={showErrors && Boolean(validation.recipientError)}
        hint={showErrors ? (validation.recipientError ?? undefined) : undefined}
        placeholder="Tên khách hàng hoặc đơn vị nhận"
      />
      <Input
        label="Đường dẫn đầu ra / Link bàn giao"
        size="sm"
        isRequired
        value={outputPath}
        onChange={setOutputPath}
        isInvalid={showErrors && Boolean(validation.outputPathError)}
        hint={showErrors ? (validation.outputPathError ?? undefined) : undefined}
        placeholder="VD: s3://bucket/path hoặc https://..."
      />
      <TextArea
        label="Phản hồi khách hàng"
        rows={4}
        value={clientFeedback}
        onChange={setClientFeedback}
        placeholder="Ghi nhận phản hồi từ khách hàng…"
      />
      <TextArea label="Ghi chú" rows={2} value={note} onChange={setNote} placeholder="Ghi chú nội bộ…" />
      {submitError && <p className="text-sm text-error-primary">{submitError}</p>}
    </FormDialog>
  )
}
