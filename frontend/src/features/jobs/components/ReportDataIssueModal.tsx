import { AlertTriangle, XClose } from '@untitledui/icons'
import { useEffect, useState } from 'react'
import { Dialog, Modal, ModalOverlay } from '@/components/application/modals/modal'
import { Button } from '@/components/base/buttons/button'
import { Input } from '@/components/base/input/input'
import { TextArea } from '@/components/base/textarea/textarea'
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

/** Modal "Báo vấn đề dữ liệu" (Dữ liệu bị chặn — gửi PM xử lý và theo dõi ở Yêu cầu của tôi / TD13). */
export default function ReportDataIssueModal({ isOpen, projectId, jobId, jobName, onClose, onSubmitted }: Props) {
  const { run, pending } = useAction()
  const [title, setTitle] = useState('')
  const [reason, setReason] = useState('')
  const [validationError, setValidationError] = useState<string | null>(null)

  useEffect(() => {
    if (!isOpen) return
    setTitle('')
    setReason('')
    setValidationError(null)
  }, [isOpen])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
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
      'Đã gửi báo cáo vấn đề dữ liệu tới PM',
    )
    if (ok) {
      onSubmitted?.()
      onClose()
    }
  }

  return (
    <ModalOverlay isOpen={isOpen} onOpenChange={(open) => !open && onClose()} isDismissable>
      <Modal className="max-w-[564px]">
        <Dialog aria-label="Báo vấn đề dữ liệu">
          <form onSubmit={handleSubmit} className="flex flex-col gap-5 p-6">
            <div className="flex items-start justify-between">
              <span className="flex size-12 items-center justify-center rounded-full bg-[#FFFAEB]">
                <span className="flex size-9 items-center justify-center rounded-full bg-[#FEDF89] text-[#B54708]">
                  <AlertTriangle className="size-5" />
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
              <h2 className="text-lg font-bold text-[#101828]">Báo vấn đề dữ liệu</h2>
              <p className="mt-1 text-sm text-[#475467]">
                {jobName} · Báo cáo dữ liệu hỏng / mờ point cloud sẽ được chuyển tới PM để kiểm tra và thay thế.
              </p>
            </div>

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

            <div className="flex items-center justify-end gap-3 pt-1">
              <Button color="secondary" size="md" onPress={onClose}>
                Hủy
              </Button>
              <Button type="submit" color="primary" size="md" isLoading={pending}>
                Gửi báo cáo
              </Button>
            </div>
          </form>
        </Dialog>
      </Modal>
    </ModalOverlay>
  )
}
