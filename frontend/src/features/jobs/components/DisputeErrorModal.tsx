import { useState } from 'react'
import { Input } from '@/components/base/input/input'
import { NativeSelect } from '@/components/base/select/select-native'
import { TextArea } from '@/components/base/textarea/textarea'
import FormDialog from '../../../shared/components/ui/FormDialog'
import { useAction } from '../../../shared/hooks/useAction'
import { createAnnotatorRequest } from '../api'
import { formatErrorLocationSummary } from '../jobHelpers'
import type { JobErrorBrief } from '../types'

interface Props {
  isOpen: boolean
  projectId: number
  jobId: number
  jobName: string
  errors: JobErrorBrief[]
  initialErrorId?: number | null
  onClose: () => void
  onSubmitted?: () => void
}

/** Hộp thoại phản hồi lỗi của QC1 — chọn lỗi theo frame/object và gửi đến Project Manager. */
export default function DisputeErrorModal(props: Props) {
  if (!props.isOpen) return null
  return <DisputeErrorForm key={`${props.jobId}:${props.initialErrorId ?? 'first'}`} {...props} />
}

function DisputeErrorForm({
  isOpen,
  projectId,
  jobId,
  jobName,
  errors,
  initialErrorId,
  onClose,
  onSubmitted,
}: Props) {
  const { run, pending } = useAction()
  const first = initialErrorId ?? errors[0]?.id ?? null
  const [selectedErrorId, setSelectedErrorId] = useState<string>(first ? String(first) : '')
  const [reasonSummary, setReasonSummary] = useState('')
  const [details, setDetails] = useState('')
  const [validationError, setValidationError] = useState<string | null>(null)

  async function handleSubmit() {
    const combinedReason = [reasonSummary.trim(), details.trim()].filter(Boolean).join('\n')
    if (combinedReason.length < 3) {
      setValidationError('Vui lòng nhập lý do phản hồi lỗi.')
      return
    }
    setValidationError(null)
    const errObj = errors.find((er) => String(er.id) === selectedErrorId)
    const locSummary = errObj ? formatErrorLocationSummary(errObj) : ''
    const title = errObj
      ? `Không đồng ý lỗi '${errObj.category}'${locSummary ? ` (${locSummary})` : ''}`
      : reasonSummary.trim() || `Phản hồi lỗi QC1 · ${jobName}`

    const ok = await run(
      () =>
        createAnnotatorRequest(projectId, {
          job: jobId,
          review_error: errObj ? errObj.id : null,
          ...(errObj?.job_issue != null ? { job_issue: errObj.job_issue } : {}),
          request_type: 'error_dispute',
          title,
          reason: combinedReason,
        }),
      'Đã gửi phản hồi lỗi tới Project Manager',
    )
    if (ok) {
      onSubmitted?.()
      onClose()
    }
  }

  const options = [
    ...(errors.length === 0 ? [{ value: '', label: 'Không chọn lỗi cụ thể (phản hồi chung)' }] : []),
    ...errors.map((err) => {
      const summary = formatErrorLocationSummary(err)
      return {
        value: String(err.id),
        label: `${err.category}${summary ? ` · ${summary}` : ''}`,
      }
    }),
  ]

  return (
    <FormDialog
      isOpen={isOpen}
      onClose={onClose}
      title="Phản hồi lỗi của QC1"
      description={`${jobName} · Gửi đến Project Manager xem xét và phân xử.`}
      submitLabel="Gửi phản hồi"
      onSubmit={handleSubmit}
      pending={pending}
    >
      <div className="flex flex-col gap-4">
        <NativeSelect
          name="review_error"
          label="Lỗi và vị trí *"
          value={selectedErrorId}
          onChange={(e) => setSelectedErrorId(e.target.value)}
          options={options}
        />

        <Input
          name="reason_summary"
          label="Lý do phản hồi *"
          placeholder="VD: Đối tượng bị che khuất hoàn toàn nên đúng quy tắc v2.3…"
          value={reasonSummary}
          onChange={(v) => {
            setReasonSummary(v)
            if (validationError) setValidationError(null)
          }}
          isInvalid={!!validationError}
          hint={validationError ?? undefined}
        />

        <TextArea
          name="details"
          label="Bằng chứng / ghi chú thêm (không bắt buộc)"
          placeholder="Ghi rõ frame liên quan, mục hướng dẫn áp dụng hoặc ngữ cảnh trên CVAT…"
          rows={3}
          value={details}
          onChange={setDetails}
        />
      </div>
    </FormDialog>
  )
}
