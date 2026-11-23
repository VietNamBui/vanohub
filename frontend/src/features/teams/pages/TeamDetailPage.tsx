import { ArrowLeft, Edit01, Edit05, SwitchHorizontal01, Trash01, UserPlus01 } from '@untitledui/icons'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { Table } from '@/components/application/table/table'
import { Button } from '@/components/base/buttons/button'
import { Dropdown } from '@/components/base/dropdown/dropdown'
import { getErrorMessage } from '../../../shared/api/errors'
import EmptyRow from '../../../shared/components/ui/EmptyRow'
import StatCard from '../../../shared/components/ui/StatCard'
import { useProject } from '../../projects/projectContext'
import MemberRolesCell from '../components/MemberRolesCell'
import TeamDialogs, { type TeamDialogState } from '../components/TeamDialogs'
import { useTeamData } from '../hooks/useTeamData'
import type { TeamMember } from '../types'

/** Trang chi tiết một team: /projects/:projectId/teams/:teamId */
export default function TeamDetailPage() {
  const { projectId } = useProject()
  const teamId = Number(useParams().teamId)
  const data = useTeamData(projectId)
  const [dialog, setDialog] = useState<TeamDialogState>(null)
  const team = data.teams.find((t) => t.id === teamId)
  const backTo = `/projects/${projectId}/teams`

  const back = (
    <Link to={backTo} className="inline-flex items-center gap-1.5 text-sm font-semibold text-tertiary hover:text-secondary">
      <ArrowLeft className="size-4" /> Team & Members
    </Link>
  )

  if (data.error != null || (!data.isLoading && !team)) {
    return (
      <div className="mx-auto flex max-w-6xl flex-col gap-4 p-4 md:p-6">
        {back}
        <div className="flex flex-col items-center gap-3 rounded-2xl bg-primary py-12 text-center ring-1 ring-secondary">
          <p className="text-sm text-tertiary">{data.error != null ? getErrorMessage(data.error) : 'Không tìm thấy team này trong dự án.'}</p>
          {data.error != null && <Button color="secondary" onPress={data.retry}>Thử lại</Button>}
        </div>
      </div>
    )
  }

  const memberOf = (userId: number) => data.members.find((m) => m.user.id === userId)
  const loadOf = (userId: number) => data.workload.find((w) => w.user.id === userId)
  const teamMembers = team?.members ?? []
  const qc1Count = teamMembers.filter((tm) => memberOf(tm.user.id)?.roles.includes('qc1')).length
  const activeJobs = teamMembers.reduce((sum, tm) => sum + (memberOf(tm.user.id)?.active_jobs ?? 0), 0)
  const dash = (n: number) => (data.isLoading ? '–' : n)

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4 p-4 md:p-6">
      {back}
      <div className="flex flex-col gap-6 rounded-2xl bg-primary p-5 shadow-xs ring-1 ring-secondary md:p-6">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-display-xs font-semibold text-primary">{team?.name ?? 'Đang tải…'}</h1>
            <p className="mt-1 text-sm text-tertiary">Team Leader: {team ? team.leader_detail?.full_name ?? 'Chưa có' : '–'}</p>
          </div>
          {team && <Button color="secondary" size="sm" iconLeading={Edit01} onPress={() => setDialog({ type: 'edit-team', team })}>Sửa</Button>}
        </header>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <StatCard value={dash(teamMembers.length)} label="Thành viên" />
          <StatCard value={dash(qc1Count)} label="Có quyền QC1" />
          <StatCard value={dash(activeJobs)} label="Job đang mở" />
        </div>

        <div className="flex items-center justify-between gap-3">
          <h2 className="text-md font-semibold text-primary">Thành viên của team</h2>
          {team && (
            <Button color="secondary" size="sm" iconLeading={UserPlus01} onPress={() => setDialog({ type: 'add-member', teamId: team.id })}>
              Thêm thành viên
            </Button>
          )}
        </div>

        <div className="overflow-hidden rounded-xl ring-1 ring-secondary">
          <Table aria-label={`Thành viên ${team?.name ?? ''}`} size="sm">
            <Table.Header>
              <Table.Head id="member" label="Thành viên" isRowHeader />
              <Table.Head id="roles" label="Vai trò" tooltip="Bấm + để gán thêm vai trò trong dự án." />
              <Table.Head id="jobs" label="Job" tooltip="Số job đang mở người này giữ khi annotate." />
              <Table.Head id="load" label="Tải" tooltip="Job đang annotate / sức chứa." />
              <Table.Head id="actions" />
            </Table.Header>
            <Table.Body items={teamMembers} renderEmptyState={() => <EmptyRow text={data.isLoading ? 'Đang tải…' : 'Team chưa có thành viên'} />}>
              {(tm: TeamMember) => {
                const load = loadOf(tm.user.id)
                const overloaded = load != null && load.holding > load.capacity
                return (
                  <Table.Row id={tm.id}>
                    <Table.Cell>
                      <div className="font-medium text-primary">{tm.user.full_name}</div>
                      <div className="text-xs text-tertiary">{tm.user.username}</div>
                    </Table.Cell>
                    <Table.Cell>
                      <MemberRolesCell projectId={projectId} userId={tm.user.id} userName={tm.user.full_name}
                        roles={memberOf(tm.user.id)?.roles ?? []} onChange={(roles) => data.setMemberRoles(tm.user.id, roles)} />
                    </Table.Cell>
                    <Table.Cell className="tabular-nums">{memberOf(tm.user.id)?.active_jobs ?? 0}</Table.Cell>
                    <Table.Cell className={overloaded ? 'font-medium text-error-primary tabular-nums' : 'tabular-nums'}>
                      {load?.holding ?? 0}/{tm.capacity}
                    </Table.Cell>
                    <Table.Cell className="w-12">
                      {team && (
                        <Dropdown.Root>
                          <Dropdown.DotsButton />
                          <Dropdown.Popover className="w-56">
                            <Dropdown.Menu aria-label="Thao tác">
                              <Dropdown.Item icon={Edit05} label="Sửa sức chứa" onAction={() => setDialog({ type: 'capacity', team, member: tm })} />
                              <Dropdown.Item icon={SwitchHorizontal01} label="Điều chuyển team"
                                onAction={() => setDialog({ type: 'transfer', userId: tm.user.id, fromTeamId: team.id })} />
                              <Dropdown.Separator />
                              <Dropdown.Item icon={Trash01} label="Bỏ khỏi team" onAction={() => setDialog({ type: 'remove', team, member: tm })} />
                            </Dropdown.Menu>
                          </Dropdown.Popover>
                        </Dropdown.Root>
                      )}
                    </Table.Cell>
                  </Table.Row>
                )
              }}
            </Table.Body>
          </Table>
        </div>
      </div>

      <TeamDialogs
        state={dialog}
        projectId={projectId}
        teams={data.teams}
        members={data.members}
        onClose={() => setDialog(null)}
        onDone={() => {
          setDialog(null)
          data.reload()
        }}
      />
    </div>
  )
}
