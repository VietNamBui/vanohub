import { useState } from 'react'
import { TextArea } from '@/components/base/textarea/textarea'
import FormDialog from '../../../shared/components/ui/FormDialog'
import { formatDateTimeLocalVN, parseDateTimeLocalVN } from '../../../shared/utils/format'

interface Props {
  open: boolean
  title?: string
  /** Deadline hiện tại (ISO string). Hỗ trợ cả `currentDeadline` lẫn `initial` cho các caller cũ. */
  currentDeadline?: string | null
  initial?: string | null
  confirmLoading?: boolean
  onCancel: () => void
  onSubmit: (deadline: string | null, note: string) => void
}

export default function DeadlineModal(props: Props) {
  if (!props.open) return null
  const existingDeadline = props.currentDeadline ?? props.initial ?? null
  return (
    <DeadlineForm
      key={`${props.title ?? ''}:${existingDeadline ?? 'none'}`}
      {...props}
      existingDeadline={existingDeadline}
    />
  )
}

function DeadlineForm({
  open,
  title,
  existingDeadline,
  confirmLoading,
  onCancel,
  onSubmit,
}: Props & { existingDeadline: string | null }) {
  const initialLocal = formatDateTimeLocalVN(existingDeadline)
  const [deadline, setDeadline] = useState(initialLocal)
  const [note, setNote] = useState('')
  const [noteError, setNoteError] = useState<string | null>(null)

  const requiresNote = Boolean(existingDeadline) && deadline !== initialLocal

  function handleSubmit() {
    const trimmedNote = note.trim()
    if (requiresNote && !trimmedNote) {
      setNoteError('Vui lòng nhập lý do khi thay đổi deadline.')
      return
    }
    setNoteError(null)
    onSubmit(parseDateTimeLocalVN(deadline), trimmedNote)
  }

  return (
    <FormDialog
      isOpen={open}
      onClose={onCancel}
      title={title ?? 'Đặt deadline'}
      submitLabel="Lưu"
      onSubmit={handleSubmit}
      pending={confirmLoading}
    >
      <div className="flex flex-col gap-4">
        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-secondary">Deadline (UTC+7)</span>
          <input
            type="datetime-local"
            value={deadline}
            onChange={(e) => {
              setDeadline(e.target.value)
              if (noteError) setNoteError(null)
            }}
            className="rounded-lg bg-primary px-3.5 py-2.5 text-md text-primary shadow-xs ring-1 ring-primary outline-none ring-inset focus:ring-2 focus:ring-brand"
          />
          <span className="text-sm text-tertiary">
            Giờ Việt Nam (UTC+7). Để trống để bỏ deadline.
          </span>
        </label>

        <TextArea
          label={requiresNote ? 'Ghi chú *' : 'Ghi chú'}
          placeholder={
            requiresNote
              ? 'Bắt buộc nhập lý do thay đổi deadline (lưu vào lịch sử)…'
              : 'Lý do đổi deadline (lưu vào lịch sử)'
          }
          rows={2}
          value={note}
          onChange={(v) => {
            setNote(v)
            if (noteError) setNoteError(null)
          }}
          isInvalid={!!noteError}
          hint={noteError ?? undefined}
        />
      </div>
    </FormDialog>
  )
}
