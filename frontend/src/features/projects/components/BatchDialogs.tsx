import dayjs from 'dayjs'
import { useState } from 'react'
import { Select } from '@/components/base/select/select'
import FormDialog from '../../../shared/components/ui/FormDialog'
import { useAction } from '../../../shared/hooks/useAction'
import type { Team } from '../../teams/types'
import { updateBatch } from '../api'
import type { Batch } from '../types'

const NO_TEAM = 0

/** Đặt deadline và team phụ trách cho một Task (model Batch). Tên task lấy từ CVAT, không sửa ở đây. */
export function TaskEditDialog({ projectId, teams, task, onClose, onDone }: {
  projectId: number
  teams: Team[]
  task: Batch
  onClose: () => void
  onDone: () => void
}) {
  const [deadline, setDeadline] = useState(task.deadline ? dayjs(task.deadline).format('YYYY-MM-DDTHH:mm') : '')
  const [team, setTeam] = useState<number>(task.team ?? NO_TEAM)
  const { run, pending } = useAction()

  async function submit() {
    const data = { deadline: deadline ? dayjs(deadline).toISOString() : null, team: team === NO_TEAM ? null : team }
    if (await run(() => updateBatch(projectId, task.id, data), `Đã lưu ${task.name}`)) onDone()
  }

  return (
    <FormDialog isOpen title="Deadline & team phụ trách" description={`${task.dataset_name} / ${task.name}`}
      onClose={onClose} onSubmit={submit} pending={pending}>
      <label className="flex flex-col gap-1.5">
        <span className="text-sm font-medium text-secondary">Deadline</span>
        <input type="datetime-local" value={deadline} onChange={(e) => setDeadline(e.target.value)}
          className="rounded-lg bg-primary px-3.5 py-2.5 text-md text-primary shadow-xs ring-1 ring-primary outline-none ring-inset focus:ring-2 focus:ring-brand" />
        <span className="text-sm text-tertiary">Mọi job chưa xong của task nhận deadline này. Để trống = bỏ deadline.</span>
      </label>
      <Select label="Team phụ trách" items={[{ id: NO_TEAM, label: 'Chưa giao' }, ...teams.map((t) => ({ id: t.id, label: t.name }))]}
        selectedKey={team} onSelectionChange={(k) => setTeam(Number(k))}>
        {(item) => <Select.Item id={item.id} label={item.label} />}
      </Select>
    </FormDialog>
  )
}
