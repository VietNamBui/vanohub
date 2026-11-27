import { useState } from 'react'
import { TextArea } from '@/components/base/textarea/textarea'
import FormDialog from '../../../shared/components/ui/FormDialog'
import MemberSelect from '../../projects/components/MemberSelect'

export interface AssignValues {
  annotator?: number | null
  qc1_reviewer?: number | null
  note?: string
}

interface Props {
  open: boolean
  projectId: number
  title?: string
  initial?: AssignValues
  confirmLoading?: boolean
  onCancel: () => void
  onSubmit: (values: AssignValues) => void
}

/**
 * Giao lại annotator / người QC1. Chỉ field nào được đổi mới gửi lên backend
 * (để giao nhiều job cùng lúc mà không ghi đè field còn lại).
 */
export default function AssignModal(props: Props) {
  if (!props.open) return null
  return (
    <AssignForm
      key={`${props.projectId}:${props.title ?? ''}:${props.initial?.annotator ?? 'none'}:${props.initial?.qc1_reviewer ?? 'none'}`}
      {...props}
    />
  )
}

function AssignForm({ open, projectId, title, initial, confirmLoading, onCancel, onSubmit }: Props) {
  const [annotator, setAnnotator] = useState<number | null>(initial?.annotator ?? null)
  const [qc1Reviewer, setQc1Reviewer] = useState<number | null>(initial?.qc1_reviewer ?? null)
  const [touchedAnnotator, setTouchedAnnotator] = useState(false)
  const [touchedQc1, setTouchedQc1] = useState(false)
  const [note, setNote] = useState(initial?.note ?? '')

  function handleSubmit() {
    if (!touchedAnnotator && !touchedQc1) {
      onCancel()
      return
    }
    const payload: AssignValues = { note }
    if (touchedAnnotator) payload.annotator = annotator
    if (touchedQc1) payload.qc1_reviewer = qc1Reviewer
    onSubmit(payload)
  }

  return (
    <FormDialog
      isOpen={open}
      onClose={onCancel}
      title={title ?? 'Giao lại job'}
      submitLabel="Lưu"
      onSubmit={handleSubmit}
      pending={confirmLoading}
    >
      <div className="flex flex-col gap-4">
        <MemberSelect
          projectId={projectId}
          role="annotator"
          label="Annotator"
          hint="Chỉ hiện người có vai trò Annotator. Số job là số job đang giữ."
          value={annotator}
          onChange={(id) => {
            setAnnotator(id)
            setTouchedAnnotator(true)
          }}
        />
        <MemberSelect
          projectId={projectId}
          role="qc1"
          label="Người QC1"
          hint="Luật bốn mắt: không được trùng annotator."
          value={qc1Reviewer}
          onChange={(id) => {
            setQc1Reviewer(id)
            setTouchedQc1(true)
          }}
        />
        <TextArea
          label="Ghi chú"
          placeholder="Lý do giao lại (lưu vào lịch sử)"
          rows={2}
          value={note}
          onChange={setNote}
        />
      </div>
    </FormDialog>
  )
}
