import { useState } from 'react'
import { Input } from '@/components/base/input/input'
import { TextArea } from '@/components/base/textarea/textarea'
import FormDialog from '../../../shared/components/ui/FormDialog'
import { useAction } from '../../../shared/hooks/useAction'
import { createAnnotatorRequest } from '../api'

interface Props {
  isOpen: boolean
  projectId: number
  jobId: number
  jobName: string
  onClose: () => void
  onSubmitted?: () => void
}

/** Hộp thoại báo vấn đề dữ liệu — gửi tới Project Manager xử lý và theo dõi ở Yêu cầu của tôi. */
export default function ReportDataIssueModal(props: Props) {
  if (!props.isOpen) return null
  return <ReportDataIssueForm key={props.jobId} {...props} />
}

function ReportDataIssueForm({ isOpen, projectId, jobId, jobName, onClose, onSubmitted }: Props) {
  const { run, pending } = useAction()
  const [title, setTitle] = useState('')
  const [reason, setReason] = useState('')
  const [validationError, setValidationError] = useState<string | null>(null)

  async function handleSubmit() {
    if (reason.trim().length < 3) {
      setValidationError('Vui lòng mô tả chi tiết sự cố dữ liệu và các frame bị ảnh hưởng.')
      return
    }
    setValidationError(null)
    const ok = await run(
      () =>
        createAnnotatorRequest(projectId, {
          job: jobId,
          request_type: 'data_issue',
          title: title.trim() || reason.trim().slice(0, 120),
          reason: reason.trim(),
        }),
      'Đã gửi báo cáo vấn đề dữ liệu tới Project Manager',
    )
    if (ok) {
      onSubmitted?.()
      onClose()
    }
  }

  return (
    <FormDialog
      isOpen={isOpen}
      onClose={onClose}
      title="Báo vấn đề dữ liệu"
      description={`${jobName} · Báo cáo dữ liệu hỏng / mờ point cloud sẽ được chuyển tới Project Manager để kiểm tra và thay thế.`}
      submitLabel="Gửi báo cáo"
      onSubmit={handleSubmit}
      pending={pending}
    >
      <div className="flex flex-col gap-4">
        <Input
          label="Tóm tắt vấn đề *"
          placeholder="VD: Point cloud mờ frame 90–96"
          value={title}
          onChange={setTitle}
        />

        <TextArea
          label="Mô tả chi tiết & phạm vi frame *"
          placeholder="Ghi rõ frame lỗi, hiện tượng (mất điểm Lidar, lệch calibration, ảnh camera đen)…"
          rows={4}
          value={reason}
          onChange={(v) => {
            setReason(v)
            if (validationError) setValidationError(null)
          }}
          isInvalid={!!validationError}
          hint={validationError ?? undefined}
        />
      </div>
    </FormDialog>
  )
}
