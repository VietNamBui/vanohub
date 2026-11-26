import { Plus, SearchLg, SwitchHorizontal01, Trash01, UserPlus01 } from '@untitledui/icons'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { Table } from '@/components/application/table/table'
import { Tabs } from '@/components/application/tabs/tabs'
import { Button } from '@/components/base/buttons/button'
import { Badge } from '@/components/base/badges/badges'
import { Input } from '@/components/base/input/input'
import { Tooltip, TooltipTrigger } from '@/components/base/tooltip/tooltip'
import { getErrorMessage } from '../../../shared/api/errors'
import StatCard from '../../../shared/components/ui/StatCard'
import EmptyRow from '../../../shared/components/ui/EmptyRow'
import { useAuth } from '../../auth/useAuth'
import { useProject } from '../../projects/projectContext'
import type { Member } from '../../projects/types'
import CreateMemberDialog from '../components/CreateMemberDialog'
import MemberPasswordCell from '../components/MemberPasswordCell'
import MemberRolesCell from '../components/MemberRolesCell'
import TeamDialogs, { type TeamDialogState } from '../components/TeamDialogs'
import { type RoleState, useTeamData } from '../hooks/useTeamData'
import type { Team, Workload } from '../types'

type TabKey = 'teams' | 'members'

/**
 * PM-07 Phân roster & luân chuyển + PM-08 Team & Thành viên (giao diện Untitled UI).
 * Đề xuất (chưa chốt): mỗi người chỉ thuộc một team trong dự án → đổi team = điều chuyển.
 * "Quá tải" = số job đang annotate > sức chứa (giống trang Workload).
 * "Thêm thành viên" tạo tài khoản mới (hệ thống sinh tài khoản + mật khẩu tạm); xếp người vào team ở cột thao tác.
 */
export default function TeamsPage() {
  const { project, projectId } = useProject()
  const [tab, setTab] = useState<TabKey>('teams')
  const [search, setSearch] = useState('')
  const [dialog, setDialog] = useState<TeamDialogState>(null)
  const [creating, setCreating] = useState(false)
  const navigate = useNavigate()
  const data = useTeamData(projectId)
  const { teams: teamList, members: memberList, workload: loadList, error, isLoading } = data

  const overloaded = loadList.filter((w) => w.holding > w.capacity).length
  const keyword = search.trim().toLowerCase()
  const shownTeams = teamList.filter((t) =>
    !keyword || t.name.toLowerCase().includes(keyword))
  const shownMembers = memberList.filter((m) =>
    !keyword || [m.user.full_name, m.user.username, m.team?.name ?? ''].some((s) => s.toLowerCase().includes(keyword)))
  const unassignedCount = memberList.filter((m) => !m.team).length

  const done = () => {
    setDialog(null)
    data.reload()
  }

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 md:p-6">
      <div className="flex flex-col gap-5 rounded-2xl bg-primary p-5 shadow-xs ring-1 ring-secondary md:p-6">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-display-xs font-semibold text-primary">Team & Members</h1>
            <p className="mt-1 text-sm text-tertiary">Organization: {project.name}</p>
          </div>
          <Button size="md" iconLeading={Plus} onPress={() => setCreating(true)}>Thêm thành viên</Button>
        </header>

        {error != null ? (
          <div className="flex flex-col items-center gap-3 py-12 text-center">
            <p className="text-sm text-error-primary">{getErrorMessage(error)}</p>
            <Button color="secondary" onPress={data.retry}>Thử lại</Button>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <StatCard value={isLoading ? '–' : teamList.length} label="Teams" />
              <StatCard value={isLoading ? '–' : memberList.length} label="Thành viên" />
              <StatCard value={isLoading ? '–' : overloaded} label="Quá tải" tone={overloaded ? 'error' : undefined} />
            </div>

            <Tabs selectedKey={tab} onSelectionChange={(key) => setTab(key as TabKey)}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <Tabs.List type="button-gray" size="sm" aria-label="Chế độ xem">
                  <Tabs.Item id="teams" label="Teams" />
                  <Tabs.Item id="members" label="Thành viên" badge={unassignedCount ? `${unassignedCount} chưa có team` : undefined} />
                </Tabs.List>
                <Button color="secondary" size="sm" iconLeading={Plus} onPress={() => setDialog({ type: 'create-team' })}>Tạo team</Button>
              </div>

              <Input
                className="mt-4"
                icon={SearchLg}
                aria-label="Tìm kiếm"
                placeholder={tab === 'teams' ? 'Tìm team…' : 'Tìm thành viên hoặc team…'}
                value={search}
                onChange={setSearch}
              />

              <Tabs.Panel id="teams" className="mt-4">
                <TeamsTable teams={shownTeams} isLoading={isLoading} onOpen={(teamId) => navigate(String(teamId))}
                  onDelete={(team) => setDialog({ type: 'delete-team', team })} />
              </Tabs.Panel>
              <Tabs.Panel id="members" className="mt-4">
                <MembersTable members={shownMembers} workload={loadList} isLoading={isLoading} openDialog={setDialog}
                  projectId={projectId} onRolesChange={data.setMemberRoles} />
              </Tabs.Panel>
            </Tabs>
          </>
        )}
      </div>

      <TeamDialogs state={dialog} projectId={projectId} teams={teamList} members={memberList} onClose={() => setDialog(null)} onDone={done} />
      {creating && (
        <CreateMemberDialog projectId={projectId} teams={teamList} onClose={() => setCreating(false)}
          onDone={() => { setCreating(false); data.reload() }} />
      )}
    </div>
  )
}

function TeamsTable({ teams, isLoading, onOpen, onDelete }: {
  teams: Team[]
  isLoading: boolean
  onOpen: (teamId: number) => void
  onDelete: (team: Team) => void
}) {
  return (
    <Table aria-label="Danh sách team" size="sm" onRowAction={(key) => onOpen(Number(key))}>
      <Table.Header>
        <Table.Head id="name" label="Team" isRowHeader />
        <Table.Head id="members" label="Thành viên" />
        <Table.Head id="actions" label="Thao tác" className="w-32" />
      </Table.Header>
      <Table.Body items={teams} renderEmptyState={() => <EmptyRow text={isLoading ? 'Đang tải…' : 'Chưa có team nào'} />}>
        {(team) => (
          <Table.Row id={team.id} className="cursor-pointer">
            <Table.Cell className="font-medium text-primary">{team.name}</Table.Cell>
            <Table.Cell className="tabular-nums">{team.members.length}</Table.Cell>
            <Table.Cell>
              <Button color="tertiary-destructive" size="sm" iconLeading={Trash01} aria-label={`Xoá ${team.name}`}
                onPress={() => onDelete(team)}>
                Xoá
              </Button>
            </Table.Cell>
          </Table.Row>
        )}
      </Table.Body>
    </Table>
  )
}

function MembersTable({ members, workload, isLoading, openDialog, projectId, onRolesChange }: {
  projectId: number
  onRolesChange: (userId: number, roles: RoleState) => void
  members: Member[]
  workload: Workload[]
  isLoading: boolean
  openDialog: (state: TeamDialogState) => void
}) {
  const { user: me } = useAuth()
  return (
    <Table aria-label="Danh sách thành viên" size="sm">
      <Table.Header>
        <Table.Head id="member" label="Thành viên" isRowHeader />
        <Table.Head id="username" label="Tài khoản" />
        <Table.Head id="password" label="Mật khẩu"
          tooltip="Mật khẩu tạm do hệ thống cấp. Bấm con mắt để xem (có ghi lịch sử). Người dùng tự đổi mật khẩu thì không xem được nữa." />
        <Table.Head id="roles" label="Vai trò" tooltip="Bấm + để gán thêm vai trò trong organization." />
        <Table.Head id="cvat" label="CVAT" tooltip="Đã liên kết tài khoản CVAT chưa. Chưa liên kết vẫn giao job được; job sẽ đồng bộ sang CVAT khi họ liên kết." />
        <Table.Head id="team" label="Team" />
        <Table.Head id="jobs" label="Job" tooltip="Số job đang mở người này giữ khi annotate." />
        <Table.Head id="load" label="Tải" tooltip="Job đang annotate / sức chứa." />
        <Table.Head id="actions" />
      </Table.Header>
      <Table.Body items={members.map((m) => ({ ...m, id: m.user.id }))}
        renderEmptyState={() => <EmptyRow text={isLoading ? 'Đang tải…' : 'Không có thành viên phù hợp'} />}>
        {(m) => {
          const load = workload.find((w) => w.user.id === m.user.id)
          const overloaded = load != null && load.holding > load.capacity
          return (
            <Table.Row id={m.id}>
              <Table.Cell className="font-medium text-primary">{m.user.full_name}</Table.Cell>
              <Table.Cell className="font-mono text-sm">{m.user.username}</Table.Cell>
              <Table.Cell>
                <MemberPasswordCell projectId={projectId} member={m}
                  canReset={m.user.id !== me?.id && !m.roles.includes('project_manager')} />
              </Table.Cell>
              <Table.Cell>
                <MemberRolesCell projectId={projectId} userId={m.user.id} userName={m.user.full_name} roles={m.roles}
                  direct_roles={m.direct_roles} onChange={(state) => onRolesChange(m.user.id, state)} />
              </Table.Cell>
              <Table.Cell><CvatBadge member={m} /></Table.Cell>
              <Table.Cell>{m.team?.name ?? <span className="text-quaternary">Chưa có team</span>}</Table.Cell>
              <Table.Cell className="tabular-nums">{m.active_jobs}</Table.Cell>
              <Table.Cell className={overloaded ? 'font-medium text-error-primary tabular-nums' : 'tabular-nums'}>
                {load ? `${load.holding}/${load.capacity}` : '–'}
              </Table.Cell>
              <Table.Cell className="text-right">
                {m.team ? (
                  <Button color="link-gray" size="sm" iconLeading={SwitchHorizontal01}
                    onPress={() => openDialog({ type: 'transfer', userId: m.user.id, fromTeamId: m.team!.id })}>
                    Điều chuyển
                  </Button>
                ) : (
                  <Button color="link-color" size="sm" iconLeading={UserPlus01}
                    onPress={() => openDialog({ type: 'transfer', userId: m.user.id })}>
                    Xếp vào team
                  </Button>
                )}
              </Table.Cell>
            </Table.Row>
          )
        }}
      </Table.Body>
    </Table>
  )
}

function CvatBadge({ member }: { member: Member }) {
  if (!member.cvat_linked) return <Badge type="pill-color" size="sm" color="gray">Chưa liên kết</Badge>
  return (
    <Tooltip title={`Tài khoản CVAT: ${member.cvat_username}`}>
      <TooltipTrigger className="cursor-default">
        <Badge type="pill-color" size="sm" color="success">Đã liên kết</Badge>
      </TooltipTrigger>
    </Tooltip>
  )
}
