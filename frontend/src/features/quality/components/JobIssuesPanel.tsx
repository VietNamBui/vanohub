import { AlertTriangle, Check, Plus, RefreshCw01 } from '@untitledui/icons'
import { useState } from 'react'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { Checkbox } from '@/components/base/checkbox/checkbox'
import { Input } from '@/components/base/input/input'
import { Select } from '@/components/base/select/select'
import { TextArea } from '@/components/base/textarea/textarea'
import { getErrorMessage } from '../../../shared/api/errors'
import FormDialog from '../../../shared/components/ui/FormDialog'
import PageState from '../../../shared/components/ui/PageState'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import type { JobStatus } from '../../jobs/types'
import {
  addressJobIssue,
  disputeJobIssue,
  importJobIssues,
  listJobIssues,
  reopenJobIssue,
  resolveJobIssue,
  ruleJobIssue,
} from '../api'
import {
  JOB_ISSUE_AUTHOR_STAGE_LABELS,
  JOB_ISSUE_STATUS_BADGE_COLORS,
  JOB_ISSUE_STATUS_LABELS,
  PRIMARY_CATEGORY_LABELS,
  SEVERITY_BADGE_COLORS,
  SEVERITY_LABELS,
  TAMPER_REASON_LABELS,
} from '../constants'
import {
  formatIssueFrameLabel,
  formatIssueObjectLabel,
  formatRulingAttributes,
  getAnnotatorAddressBlockReason,
  getAnnotatorDisputeBlockReason,
  getSelectForRejectBlockReason,
  isAcceptanceBlockingIssue,
  isSubmitBlockingIssue,
  parseRulingAttributes,
} from '../issueHelpers'
import type { JobIssue, JobIssueRuleDecision } from '../types'

interface Props {
  projectId: number
  jobId: number
  jobStatus: JobStatus
  cvatJobId: number | null
  isLocked?: boolean
  isEscalatedBlocked?: boolean
  mode: 'annotator' | 'qc1' | 'qc2' | 'pm'
  canManageJobs?: boolean
  sampleFrames?: number[]
  selectedIssueIds?: number[]
  onSelectForReject?: (issue: JobIssue) => void
  onChanged?: () => void
}

const RULE_DECISIONS: { id: JobIssueRuleDecision; label: string }[] = [
  { id: 'ruling', label: 'Phán quyết quy chuẩn (mở lại để sửa)' },
  { id: 'not_an_issue', label: 'Không phải lỗi (huỷ chặn)' },
  { id: 'resolved', label: 'Xác nhận đã xử lý' },
]

/** Bảng quản lý CVAT JobIssue theo vai trò (Annotator / QC1 / QC2 / PM). */
export default function JobIssuesPanel({
  projectId,
  jobId,
  jobStatus,
  cvatJobId,
  isLocked = false,
  isEscalatedBlocked = false,
  mode,
  canManageJobs = false,
  sampleFrames,
  selectedIssueIds,
  onSelectForReject,
  onChanged,
}: Props) {
  const [version, setVersion] = useState(0)
  const [disputing, setDisputing] = useState<JobIssue | null>(null)
  const [ruling, setRuling] = useState<JobIssue | null>(null)
  const { run, pending } = useAction()

  const req = useRequest(`job-issues:${projectId}:${jobId}:${version}`, () =>
    listJobIssues(projectId, { job: jobId, page_size: 100 }),
  )
  const issues = req.data?.results ?? []
  const reload = () => {
    setVersion((v) => v + 1)
    onChanged?.()
  }

  const canImport = cvatJobId != null && !isLocked && jobStatus !== 'delivered'
  const canRule = (mode === 'pm' || canManageJobs) && !isLocked && jobStatus !== 'delivered'

  async function handleImport() {
    const res = await run(
      () => importJobIssues(projectId, jobId),
      'Đã đồng bộ issue từ CVAT',
    )
    if (res) reload()
  }

  async function handleAddress(issue: JobIssue) {
    if (await run(() => addressJobIssue(projectId, issue.id), `Đã đánh dấu sửa Issue #${issue.cvat_issue_id}`)) {
      reload()
    }
  }

  async function handleResolve(issue: JobIssue) {
    if (await run(() => resolveJobIssue(projectId, issue.id), `Đã xác nhận xử lý Issue #${issue.cvat_issue_id}`)) {
      reload()
    }
  }

  async function handleReopen(issue: JobIssue) {
    if (await run(() => reopenJobIssue(projectId, issue.id), `Đã mở lại Issue #${issue.cvat_issue_id}`)) {
      reload()
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-primary">CVAT Issues ({issues.length})</h3>
          <p className="text-xs text-tertiary">
            Đồng bộ một chiều từ CVAT · trạng thái xử lý và phán quyết lưu trên VanoHub.
          </p>
        </div>
        {canImport && (
          <Button
            size="xs"
            color="secondary"
            iconLeading={RefreshCw01}
            isLoading={pending}
            onPress={handleImport}
          >
            Đồng bộ issue CVAT
          </Button>
        )}
      </div>

      {req.error != null ? (
        <PageState kind="error" description={getErrorMessage(req.error)} onRetry={req.retry} />
      ) : req.isLoading && !req.data ? (
        <p className="text-xs text-tertiary">Đang tải danh sách issue…</p>
      ) : issues.length === 0 ? (
        <div className="rounded-xl border border-secondary bg-secondary_subtle px-4 py-3 text-xs text-tertiary">
          Chưa có CVAT issue nào cho job này.{canImport ? ' Bấm "Đồng bộ issue CVAT" để tải mới.' : ''}
        </div>
      ) : (
        <ul className="flex flex-col gap-2.5">
          {issues.map((issue) => {
            const objectLabel = formatIssueObjectLabel(issue)
            const submitBlocks = isSubmitBlockingIssue(issue)
            const acceptBlocks = isAcceptanceBlockingIssue(issue)
            const addressBlock =
              mode === 'annotator'
                ? getAnnotatorAddressBlockReason(issue, jobStatus, isLocked, isEscalatedBlocked)
                : null
            const disputeBlock =
              mode === 'annotator' ? getAnnotatorDisputeBlockReason(issue, jobStatus, isLocked) : null
            const rejectBlock =
              (mode === 'qc1' || mode === 'qc2') && onSelectForReject
                ? getSelectForRejectBlockReason(issue, mode, sampleFrames, selectedIssueIds)
                : null
            const canQcResolve =
              (mode === 'qc1' || mode === 'qc2') &&
              !isLocked &&
              issue.authority_status === 'valid' &&
              (issue.status === 'addressed' || issue.status === 'open' || issue.status === 'reopened')
            const canQcReopen =
              (mode === 'qc1' || mode === 'qc2') &&
              !isLocked &&
              issue.authority_status === 'valid' &&
              (issue.status === 'addressed' || issue.status === 'resolved')

            return (
              <li
                key={issue.id}
                className="flex flex-col gap-2 rounded-xl border border-secondary bg-primary p-3 text-sm"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-semibold text-primary tabular-nums">#{issue.cvat_issue_id}</span>
                    <Badge type="pill-color" size="sm" color={JOB_ISSUE_STATUS_BADGE_COLORS[issue.status]}>
                      {JOB_ISSUE_STATUS_LABELS[issue.status]}
                    </Badge>
                    <Badge type="color" size="sm" color={SEVERITY_BADGE_COLORS[issue.severity]}>
                      {SEVERITY_LABELS[issue.severity]}
                    </Badge>
                    {issue.defect_code && (
                      <Badge type="color" size="sm" color="purple">
                        {issue.defect_code}
                      </Badge>
                    )}
                    {issue.primary_category && (
                      <Badge type="color" size="sm" color="gray">
                        {PRIMARY_CATEGORY_LABELS[issue.primary_category] ?? issue.primary_category}
                      </Badge>
                    )}
                    {issue.author_stage && (
                      <Badge type="color" size="sm" color="blue">
                        {JOB_ISSUE_AUTHOR_STAGE_LABELS[issue.author_stage]}
                      </Badge>
                    )}
                    {issue.is_clarification && (
                      <Badge type="pill-color" size="sm" color="warning">
                        Làm rõ
                      </Badge>
                    )}
                    {issue.authority_status !== 'valid' && (
                      <Badge type="pill-color" size="sm" color="error">
                        Tác giả không hợp lệ
                      </Badge>
                    )}
                    {issue.source_missing && (
                      <Badge type="pill-color" size="sm" color="warning">
                        Thiếu nguồn CVAT
                      </Badge>
                    )}
                    {issue.tampered && (
                      <Badge type="pill-color" size="sm" color="error">
                        <AlertTriangle className="mr-1 size-3" />
                        {TAMPER_REASON_LABELS[issue.tamper_reason] ?? 'Bị sửa trên CVAT'}
                      </Badge>
                    )}
                    {issue.cvat_reopen_drift && (
                      <Badge type="pill-color" size="sm" color="orange">
                        Lệch trạng thái CVAT
                      </Badge>
                    )}
                    {submitBlocks && (
                      <Badge type="pill-color" size="sm" color="error">
                        Chặn nộp
                      </Badge>
                    )}
                    {!submitBlocks && acceptBlocks && (
                      <Badge type="pill-color" size="sm" color="warning">
                        Chặn duyệt
                      </Badge>
                    )}
                  </div>
                  <span className="text-xs text-tertiary tabular-nums">
                    {formatIssueFrameLabel(issue)}
                    {objectLabel ? ` · ${objectLabel}` : ''}
                  </span>
                </div>

                {issue.message && <p className="text-xs text-secondary">{issue.message}</p>}

                {(issue.ruling_label || issue.ruling_note) && (
                  <div className="rounded-lg bg-secondary px-3 py-2 text-xs text-secondary">
                    <span className="font-semibold text-primary">Phán quyết PM:</span>{' '}
                    {issue.ruling_label && <span className="font-medium">[{issue.ruling_label}] </span>}
                    {issue.ruling_note || 'Đã phán quyết'}
                  </div>
                )}

                <div className="flex flex-wrap items-center gap-2 pt-1">
                  {mode === 'annotator' && (
                    <>
                      <span title={addressBlock ?? undefined}>
                        <Button
                          size="xs"
                          color="primary"
                          iconLeading={Check}
                          isDisabled={pending || addressBlock !== null}
                          onPress={() => handleAddress(issue)}
                        >
                          Đã sửa
                        </Button>
                      </span>
                      <span title={disputeBlock ?? undefined}>
                        <Button
                          size="xs"
                          color="secondary"
                          isDisabled={pending || disputeBlock !== null}
                          onPress={() => setDisputing(issue)}
                        >
                          Phản hồi
                        </Button>
                      </span>
                    </>
                  )}

                  {(mode === 'qc1' || mode === 'qc2') && (
                    <>
                      {canQcResolve && (
                        <Button
                          size="xs"
                          color="primary"
                          iconLeading={Check}
                          isDisabled={pending}
                          onPress={() => handleResolve(issue)}
                        >
                          Xác nhận đã sửa
                        </Button>
                      )}
                      {canQcReopen && (
                        <Button
                          size="xs"
                          color="secondary"
                          isDisabled={pending}
                          onPress={() => handleReopen(issue)}
                        >
                          Mở lại
                        </Button>
                      )}
                      {onSelectForReject && (
                        <span title={rejectBlock ?? undefined}>
                          <Button
                            size="xs"
                            color="secondary-destructive"
                            iconLeading={Plus}
                            isDisabled={rejectBlock !== null}
                            onPress={() => onSelectForReject(issue)}
                          >
                            Đưa vào Reject
                          </Button>
                        </span>
                      )}
                    </>
                  )}

                  {canRule && (
                    <Button
                      size="xs"
                      color="secondary"
                      isDisabled={pending}
                      onPress={() => setRuling(issue)}
                    >
                      Phán quyết
                    </Button>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}

      {disputing && (
        <DisputeIssueDialog
          key={disputing.id}
          projectId={projectId}
          issue={disputing}
          onClose={() => setDisputing(null)}
          onDone={() => {
            setDisputing(null)
            reload()
          }}
        />
      )}

      {ruling && (
        <RuleIssueDialog
          key={ruling.id}
          projectId={projectId}
          issue={ruling}
          onClose={() => setRuling(null)}
          onDone={() => {
            setRuling(null)
            reload()
          }}
        />
      )}
    </div>
  )
}

function DisputeIssueDialog({
  projectId,
  issue,
  onClose,
  onDone,
}: {
  projectId: number
  issue: JobIssue
  onClose: () => void
  onDone: () => void
}) {
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const { run, pending } = useAction()

  async function submit() {
    const clean = reason.trim()
    if (clean.length < 3) {
      setError('Vui lòng nhập lý do phản hồi tối thiểu 3 ký tự.')
      return
    }
    setError(null)
    if (
      await run(
        () => disputeJobIssue(projectId, issue.id, clean),
        `Đã gửi phản hồi cho Issue #${issue.cvat_issue_id}`,
      )
    ) {
      onDone()
    }
  }

  return (
    <FormDialog
      isOpen
      title={`Phản hồi Issue #${issue.cvat_issue_id}`}
      description="Gửi yêu cầu để Project Manager đối chiếu và phán quyết."
      submitLabel="Gửi phản hồi"
      onClose={onClose}
      onSubmit={submit}
      pending={pending}
    >
      <TextArea
        label="Lý do phản hồi *"
        rows={3}
        value={reason}
        onChange={(v) => {
          setReason(v)
          if (error) setError(null)
        }}
        isInvalid={!!error}
        hint={error ?? undefined}
        placeholder="Nêu rõ lý do theo hướng dẫn gán nhãn hoặc frame cụ thể…"
      />
    </FormDialog>
  )
}

function RuleIssueDialog({
  projectId,
  issue,
  onClose,
  onDone,
}: {
  projectId: number
  issue: JobIssue
  onClose: () => void
  onDone: () => void
}) {
  const [decision, setDecision] = useState<JobIssueRuleDecision>('ruling')
  const [rulingLabel, setRulingLabel] = useState(issue.ruling_label || '')
  const [attrsRaw, setAttrsRaw] = useState(formatRulingAttributes(issue.ruling_attributes))
  const [rulingNote, setRulingNote] = useState(issue.ruling_note || '')
  const [rejectDispute, setRejectDispute] = useState(false)
  const [attrsError, setAttrsError] = useState<string | null>(null)
  const { run, pending } = useAction()

  async function submit() {
    const parsedAttrs = parseRulingAttributes(attrsRaw)
    if (!parsedAttrs.valid) {
      setAttrsError(parsedAttrs.error)
      return
    }
    setAttrsError(null)
    const ok = await run(
      () =>
        ruleJobIssue(projectId, issue.id, {
          decision,
          ruling_label: rulingLabel.trim(),
          ruling_attributes: parsedAttrs.value,
          ruling_note: rulingNote.trim(),
          dispute_outcome: issue.is_disputed && rejectDispute ? 'rejected' : null,
        }),
      `Đã lưu phán quyết cho Issue #${issue.cvat_issue_id}`,
    )
    if (ok) onDone()
  }

  return (
    <FormDialog
      isOpen
      title={`Phán quyết PM — Issue #${issue.cvat_issue_id}`}
      description={`${formatIssueFrameLabel(issue)}${issue.defect_code ? ` · ${issue.defect_code}` : ''}`}
      submitLabel="Lưu phán quyết"
      onClose={onClose}
      onSubmit={submit}
      pending={pending}
    >
      <div className="flex flex-col gap-3">
        <Select
          label="Quyết định *"
          size="sm"
          items={RULE_DECISIONS}
          selectedKey={decision}
          onSelectionChange={(k) => setDecision(k as JobIssueRuleDecision)}
        >
          {(item) => <Select.Item id={item.id} label={item.label} />}
        </Select>

        {decision === 'ruling' && (
          <>
            <Input
              label="Nhãn phán quyết (tuỳ chọn)"
              size="sm"
              value={rulingLabel}
              onChange={setRulingLabel}
              placeholder="VD: Car / Pedestrian"
            />
            <TextArea
              label="Thuộc tính phán quyết (mỗi dòng key=value)"
              rows={3}
              value={attrsRaw}
              onChange={(v) => {
                setAttrsRaw(v)
                if (attrsError) setAttrsError(null)
              }}
              isInvalid={!!attrsError}
              hint={attrsError ?? undefined}
              placeholder={'occluded=true\ntruncated=0'}
            />
          </>
        )}

        <TextArea
          label="Ghi chú phán quyết"
          rows={3}
          value={rulingNote}
          onChange={setRulingNote}
          placeholder="Giải thích quyết định để Annotator và QC thực hiện thống nhất…"
        />

        {issue.is_disputed && decision !== 'not_an_issue' && (
          <Checkbox
            size="sm"
            isSelected={rejectDispute}
            onChange={setRejectDispute}
            label="Đóng yêu cầu phản hồi của Annotator là Từ chối"
          />
        )}
      </div>
    </FormDialog>
  )
}
