import { useState } from 'react'
import { Input } from '@/components/base/input/input'
import { InputNumber } from '@/components/base/input/input-number'
import { Select } from '@/components/base/select/select'
import type { SelectItemType } from '@/components/base/select/select-shared'
import FormDialog from '../../../shared/components/ui/FormDialog'
import { useAction } from '../../../shared/hooks/useAction'
import type { Member } from '../../projects/types'
import { addTeamMember, createTeam, deleteTeam, removeTeamMember, setMemberCapacity, transferMember, updateTeam } from '../api'
import type { Team, TeamMember } from '../types'

export type TeamDialogState =
  | { type: 'create-team' }
  | { type: 'edit-team'; team: Team }
  | { type: 'delete-team'; team: Team }
  | { type: 'add-member'; teamId?: number }
  | { type: 'transfer'; userId: number; fromTeamId?: number }
  | { type: 'capacity'; team: Team; member: TeamMember }
  | { type: 'remove'; team: Team; member: TeamMember }
  | null

interface Props {
  state: TeamDialogState
  projectId: number
  teams: Team[]
  members: Member[]
  onClose: () => void
  /** Gọi sau khi lưu thành công → trang tải lại dữ liệu. */
  onDone: () => void
}

/** Mọi hộp thoại của trang Team & Members. Mỗi lần mở là một component mới → form tự reset. */
export default function TeamDialogs({ state, ...props }: Props) {
  if (!state) return null
  switch (state.type) {
    case 'create-team':
      return <TeamFormDialog {...props} />
    case 'edit-team':
      return <TeamFormDialog {...props} team={state.team} />
    case 'delete-team':
      return <DeleteTeamDialog {...props} team={state.team} />
    case 'add-member':
      return <AddMemberDialog {...props} teamId={state.teamId} />
    case 'transfer':
      return <TransferDialog {...props} userId={state.userId} fromTeamId={state.fromTeamId} />
    case 'capacity':
      return <CapacityDialog {...props} team={state.team} member={state.member} />
    case 'remove':
      return <RemoveDialog {...props} team={state.team} member={state.member} />
  }
}

type DialogProps = Omit<Props, 'state'>

const memberItem = (m: Member): SelectItemType => ({ id: m.user.id, label: m.user.full_name, supportingText: m.user.username })

function TeamFormDialog({ projectId, onClose, onDone, team }: DialogProps & { team?: Team }) {
  const [name, setName] = useState(team?.name ?? '')
  const { run, pending } = useAction()

  async function submit() {
    const data = { name: name.trim() }
    const ok = team
      ? await run(() => updateTeam(projectId, team.id, data), 'Đã lưu team')
      : await run(() => createTeam(projectId, data), 'Đã tạo team')
    if (ok) onDone()
  }

  return (
    <FormDialog isOpen title={team ? 'Sửa team' : 'Tạo team'} onClose={onClose} onSubmit={submit} pending={pending}>
      <Input label="Tên team" isRequired autoFocus value={name} onChange={setName} placeholder="VD: Team Alpha" />
    </FormDialog>
  )
}

function AddMemberDialog({ projectId, teams, members, onClose, onDone, teamId }: DialogProps & { teamId?: number }) {
  const [team, setTeam] = useState<number | null>(teamId ?? teams[0]?.id ?? null)
  const [user, setUser] = useState<number | null>(null)
  const [capacity, setCapacity] = useState(5)
  const { run, pending } = useAction()
  // Đề xuất đang dùng: mỗi người chỉ thuộc một team → chỉ thêm được người chưa có team.
  const unassigned = members.filter((m) => !m.team)

  async function submit() {
    if (team == null || user == null) return
    const ok = await run(() => addTeamMember(projectId, team, user, capacity), 'Đã thêm thành viên')
    if (ok) onDone()
  }

  return (
    <FormDialog
      isOpen
      title="Thêm thành viên"
      description="Người đã thuộc team khác phải dùng Điều chuyển."
      onClose={onClose}
      onSubmit={submit}
      pending={pending}
    >
      {teamId == null && (
        <Select label="Team" isRequired placeholder="Chọn team" items={teams.map((t) => ({ id: t.id, label: t.name }))}
          selectedKey={team} onSelectionChange={(key) => setTeam(Number(key))}>
          {(item) => <Select.Item id={item.id} label={item.label} />}
        </Select>
      )}
      <Select
        label="Thành viên"
        isRequired
        placeholder={unassigned.length ? 'Chọn người' : 'Mọi người đã có team'}
        isDisabled={!unassigned.length}
        items={unassigned.map(memberItem)}
        selectedKey={user}
        onSelectionChange={(key) => setUser(Number(key))}
      >
        {(item) => <Select.Item id={item.id} label={item.label} supportingText={item.supportingText} />}
      </Select>
      <InputNumber label="Sức chứa" hint="Số job tối đa người này giữ cùng lúc." minValue={1} maxValue={100}
        value={capacity} onChange={(v) => setCapacity(Number.isNaN(v) ? 5 : v)} />
    </FormDialog>
  )
}

function TransferDialog({ projectId, teams, members, onClose, onDone, userId, fromTeamId }: DialogProps & { userId: number; fromTeamId?: number }) {
  const [toTeam, setToTeam] = useState<number | null>(null)
  const { run, pending } = useAction()
  const member = members.find((m) => m.user.id === userId)

  async function submit() {
    if (toTeam == null) return
    const ok = await run(() => transferMember(projectId, userId, toTeam), fromTeamId ? 'Đã điều chuyển' : 'Đã xếp vào team')
    if (ok) onDone()
  }

  return (
    <FormDialog
      isOpen
      title={fromTeamId ? 'Điều chuyển sang team khác' : 'Xếp vào team'}
      description={member && `${member.user.full_name}${member.team ? ` · đang ở ${member.team.name}` : ' · chưa có team'}`}
      onClose={onClose}
      onSubmit={submit}
      pending={pending}
    >
      <Select label="Team đích" isRequired placeholder="Chọn team"
        items={teams.filter((t) => t.id !== fromTeamId).map((t) => ({ id: t.id, label: t.name }))}
        selectedKey={toTeam} onSelectionChange={(key) => setToTeam(Number(key))}>
        {(item) => <Select.Item id={item.id} label={item.label} />}
      </Select>
    </FormDialog>
  )
}

function CapacityDialog({ projectId, onClose, onDone, team, member }: DialogProps & { team: Team; member: TeamMember }) {
  const [capacity, setCapacity] = useState(member.capacity)
  const { run, pending } = useAction()

  async function submit() {
    const ok = await run(() => setMemberCapacity(projectId, team.id, member.user.id, capacity), 'Đã lưu sức chứa')
    if (ok) onDone()
  }

  return (
    <FormDialog isOpen title="Sửa sức chứa" description={member.user.full_name} onClose={onClose} onSubmit={submit} pending={pending}>
      <InputNumber label="Sức chứa" hint="Số job tối đa người này giữ cùng lúc." minValue={1} maxValue={100} autoFocus
        value={capacity} onChange={(v) => setCapacity(Number.isNaN(v) ? member.capacity : v)} />
    </FormDialog>
  )
}

function RemoveDialog({ projectId, onClose, onDone, team, member }: DialogProps & { team: Team; member: TeamMember }) {
  const { run, pending } = useAction()

  async function submit() {
    const ok = await run(() => removeTeamMember(projectId, team.id, member.user.id), 'Đã bỏ khỏi team')
    if (ok) onDone()
  }

  return (
    <FormDialog
      isOpen
      destructive
      title="Bỏ khỏi team?"
      description={`${member.user.full_name} sẽ rời ${team.name}. Vai trò trong dự án và job đang giữ không thay đổi.`}
      submitLabel="Bỏ khỏi team"
      onClose={onClose}
      onSubmit={submit}
      pending={pending}
    />
  )
}

function DeleteTeamDialog({ projectId, onClose, onDone, team }: DialogProps & { team: Team }) {
  const { run, pending } = useAction()

  async function submit() {
    const ok = await run(async () => {
      await deleteTeam(projectId, team.id)
      return true
    }, `Đã xoá ${team.name}`)
    if (ok) onDone()
  }

  return (
    <FormDialog
      isOpen
      destructive
      title={`Xoá ${team.name}?`}
      description={
        <>
          {team.members.length > 0
            ? `${team.members.length} thành viên sẽ chuyển sang "Chưa có team" (vai trò và job đang giữ không đổi). `
            : 'Team chưa có thành viên. '}
          Batch đang giao cho team sẽ thành "Chưa giao"; thông báo gửi riêng cho team này bị xoá. Không hoàn tác được.
        </>
      }
      submitLabel="Xoá team"
      onClose={onClose}
      onSubmit={submit}
      pending={pending}
    />
  )
}
