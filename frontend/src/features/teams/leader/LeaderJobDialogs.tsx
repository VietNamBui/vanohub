import dayjs from 'dayjs'
import { useState } from 'react'
import { Tabs } from '@/components/application/tabs/tabs'
import { TextArea } from '@/components/base/textarea/textarea'
import FormDialog from '../../../shared/components/ui/FormDialog'
import { useAction } from '../../../shared/hooks/useAction'
import { cx } from '@/utils/cx'
import { leaderAssign, leaderBulkAssign, leaderBulkDeadline, leaderDeadline } from './api'
import type { LeaderMember } from './types'

export type LeaderDialogState =
  | { type: 'assign'; jobIds: number[]; label: string }
  | { type: 'deadline'; jobIds: number[]; label: string; current?: string | null }
  | null

interface Props {
  state: LeaderDialogState
  projectId: number
  members: LeaderMember[]
  onClose: () => void
  onDone: () => void
}

export default function LeaderJobDialogs({ state, ...props }: Props) {
  if (!state) return null
  return state.type === 'assign'
    ? <ReassignDialog {...props} jobIds={state.jobIds} label={state.label} />
    : <DeadlineDialog {...props} jobIds={state.jobIds} label={state.label} current={state.current} />
}

type Field = 'annotator' | 'qc1_reviewer'

/** TL-09 "Gợi ý người nhận khi Giao lại": thành viên có vai trò phù hợp, xếp theo tải thấp nhất. */
function ReassignDialog({ projectId, members, onClose, onDone, jobIds, label }: Omit<Props, 'state'> & { jobIds: number[]; label: string }) {
  const [field, setField] = useState<Field>('annotator')
  const [userId, setUserId] = useState<number | null>(null)
  const [note, setNote] = useState('')
  const { run, pending } = useAction()
  const role = field === 'annotator' ? 'annotator' : 'qc1'
  const load = (m: LeaderMember) => (field === 'annotator' ? m.holding : m.qc1_holding)
  const candidates = members
    .filter((m) => m.roles.includes(role))
    .sort((a, b) => load(a) / Math.max(a.capacity, 1) - load(b) / Math.max(b.capacity, 1))

  async function submit() {
    if (userId == null) return
    const data = { [field]: userId, note }
    const ok = jobIds.length === 1
      ? await run(() => leaderAssign(projectId, jobIds[0], data), 'Đã giao lại job')
      : await run(() => leaderBulkAssign(projectId, jobIds, data), `Đã giao lại ${jobIds.length} job`)
    if (ok) onDone()
  }

  return (
    <FormDialog isOpen title="Giao lại job" description={label} submitLabel="Giao lại" onClose={onClose} onSubmit={submit} pending={pending}>
      <Tabs selectedKey={field} onSelectionChange={(k) => { setField(k as Field); setUserId(null) }}>
        <Tabs.List type="button-border" size="sm" fullWidth aria-label="Giao phần việc">
          <Tabs.Item id="annotator" label="Người annotate" />
          <Tabs.Item id="qc1_reviewer" label="Người QC1" />
        </Tabs.List>
      </Tabs>
      <div>
        <p className="mb-2 text-sm font-medium text-secondary">Chọn người nhận <span className="font-normal text-tertiary">· xếp theo tải thấp nhất</span></p>
        {candidates.length === 0 ? (
          <p className="rounded-lg bg-secondary p-3 text-sm text-tertiary">Team chưa có ai có vai trò {field === 'annotator' ? 'Annotator' : 'QC1'}.</p>
        ) : (
          <div role="radiogroup" aria-label="Người nhận" className="flex max-h-64 flex-col gap-1.5 overflow-y-auto">
            {candidates.map((m, i) => {
              const selected = userId === m.user.id
              const percent = Math.round((load(m) * 100) / Math.max(m.capacity, 1))
              return (
                <button
                  key={m.user.id} type="button" role="radio" aria-checked={selected} onClick={() => setUserId(m.user.id)}
                  className={cx('flex items-center gap-3 rounded-lg px-3 py-2.5 text-left ring-1 ring-inset transition',
                    selected ? 'bg-brand-primary_alt ring-2 ring-brand' : 'ring-secondary hover:bg-primary_hover')}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium text-secondary">
                      {m.user.full_name}
                      {i === 0 && <span className="ml-2 rounded-md bg-success-primary px-1.5 py-0.5 text-xs font-medium text-success-primary">Gợi ý</span>}
                    </span>
                    <span className="block text-xs text-tertiary">{m.user.username}</span>
                  </span>
                  <span className={cx('text-sm tabular-nums', percent > 100 ? 'font-semibold text-error-primary' : 'text-tertiary')}>
                    {load(m)}/{m.capacity}
                  </span>
                </button>
              )
            })}
          </div>
        )}
      </div>
      <TextArea label="Ghi chú (không bắt buộc)" rows={2} value={note} onChange={setNote} />
    </FormDialog>
  )
}

function DeadlineDialog({ projectId, onClose, onDone, jobIds, label, current }: Omit<Props, 'state' | 'members'> & { jobIds: number[]; label: string; current?: string | null }) {
  const [value, setValue] = useState(current ? dayjs(current).format('YYYY-MM-DDTHH:mm') : '')
  const [note, setNote] = useState('')
  const { run, pending } = useAction()

  async function submit() {
    const deadline = value ? dayjs(value).toISOString() : null
    const ok = jobIds.length === 1
      ? await run(() => leaderDeadline(projectId, jobIds[0], deadline, note), 'Đã đặt deadline')
      : await run(() => leaderBulkDeadline(projectId, jobIds, deadline, note), `Đã đặt deadline cho ${jobIds.length} job`)
    if (ok) onDone()
  }

  return (
    <FormDialog isOpen title="Đặt deadline" description={label} onClose={onClose} onSubmit={submit} pending={pending}>
      <label className="flex flex-col gap-1.5">
        <span className="text-sm font-medium text-secondary">Deadline</span>
        <input
          type="datetime-local" value={value} onChange={(e) => setValue(e.target.value)}
          className="rounded-lg bg-primary px-3.5 py-2.5 text-md text-primary shadow-xs ring-1 ring-primary outline-none ring-inset focus:ring-2 focus:ring-brand"
        />
        <span className="text-sm text-tertiary">Để trống = bỏ deadline.</span>
      </label>
      <TextArea label="Lý do (lưu vào lịch sử deadline)" rows={2} value={note} onChange={setNote} />
    </FormDialog>
  )
}
