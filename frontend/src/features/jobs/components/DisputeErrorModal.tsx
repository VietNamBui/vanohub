import { InfoCircle, XClose } from '@untitledui/icons'
import { useState } from 'react'
import { Dialog, Modal, ModalOverlay } from '@/components/application/modals/modal'
import { Button } from '@/components/base/buttons/button'
import { Input } from '@/components/base/input/input'
import { NativeSelect } from '@/components/base/select/select-native'
import { TextArea } from '@/components/base/textarea/textarea'
import { useAction } from '../../../shared/hooks/useAction'
import { createAnnotatorRequest } from '../api'
import type { JobErrorBrief } from '../types'

interface Props {
  isOpen: boolean
  projectId: number
  jobId: number
  jobName: string
  teamLeaderName?: string | null
  errors: JobErrorBrief[]
  initialErrorId?: number | null
  onClose: () => void
  onSubmitted?: () => void
}

/** Modal "Phản hồi lỗi của QC1" (564px) — chọn lỗi theo frame/object và gửi đến Team Leader. */
export default function DisputeErrorModal(props: Props) {
  return (
    <ModalOverlay isOpen={props.isOpen} onOpenChange={(open) => !open && props.onClose()} isDismissable>
      <Modal className="max-w-[564px]">
        <Dialog aria-label="Phản hồi lỗi của QC1">
          {props.isOpen && (
            <DisputeErrorForm
              key={`${props.jobId}:${props.initialErrorId ?? 'first'}`}
              {...props}
            />
          )}
        </Dialog>
      </Modal>
    </ModalOverlay>
  )
}

function DisputeErrorForm({
  projectId,
  jobId,
  jobName,
  teamLeaderName,
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

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const combinedReason = [reasonSummary.trim(), details.trim()].filter(Boolean).join('\n')
    if (combinedReason.length < 3) {
      setValidationError('Vui lòng nhập lý do phản hồi lỗi.')
      return
    }
    setValidationError(null)
    const errObj = errors.find((er) => String(er.id) === selectedErrorId)
    const title = errObj
      ? `Không đồng ý lỗi '${errObj.category}'${errObj.location ? ` (${errObj.location})` : ''}`
      : reasonSummary.trim() || `Phản hồi lỗi QC1 · ${jobName}`

    const ok = await run(
      () =>
        createAnnotatorRequest(projectId, {
          job: jobId,
          review_error: errObj ? errObj.id : null,
          request_type: 'error_dispute',
          title,
          reason: combinedReason,
        }),
      'Đã gửi phản hồi lỗi tới Team Leader',
    )
    if (ok) {
      onSubmitted?.()
      onClose()
    }
  }

  const options = [
    ...(errors.length === 0 ? [{ value: '', label: 'Không chọn lỗi cụ thể (phản hồi chung)' }] : []),
    ...errors.map((err) => ({
      value: String(err.id),
      label: `${err.category}${err.location ? ` · ${err.location}` : ''}`,
    })),
  ]

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5 p-6">
      <div className="flex items-start justify-between">
        <span className="flex size-12 items-center justify-center rounded-full bg-[#F9F5FF]">
          <span className="flex size-9 items-center justify-center rounded-full bg-[#E9D7FE] text-[#6941C6]">
            <InfoCircle className="size-5" />
          </span>
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Đóng"
          className="flex size-8 cursor-pointer items-center justify-center rounded-lg text-[#98A2B3] hover:bg-[#F9FAFB] hover:text-[#475467]"
        >
          <XClose className="size-5" />
        </button>
      </div>

      <div>
        <h2 className="text-lg font-bold text-[#101828]">Phản hồi lỗi của QC1</h2>
        <p className="mt-1 text-sm text-[#475467]">
          {jobName} · Gửi đến TL {teamLeaderName || 'phụ trách team'}.
        </p>
      </div>

      <div className="flex flex-col gap-4">
        <NativeSelect
          label="Lỗi và vị trí *"
          value={selectedErrorId}
          onChange={(e) => setSelectedErrorId(e.target.value)}
          options={options}
        />

        <Input
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
          label="Bằng chứng / ghi chú thêm (không bắt buộc)"
          placeholder="Ghi rõ frame liên quan, mục hướng dẫn áp dụng hoặc ngữ cảnh trên CVAT…"
          rows={3}
          value={details}
          onChange={setDetails}
        />
      </div>

      <div className="flex items-center justify-end gap-3 pt-1">
        <Button color="secondary" size="md" onPress={onClose}>
          Hủy
        </Button>
        <Button type="submit" color="primary" size="md" isLoading={pending}>
          Gửi phản hồi
        </Button>
      </div>
    </form>
  )
}
