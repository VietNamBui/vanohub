import { useCallback, useMemo, useState } from 'react'
import { useRequest } from '../../../shared/hooks/useRequest'
import type { Role } from '../../../shared/types/roles'
import { listMembers } from '../../projects/api'
import { getWorkload, listTeams } from '../api'

/**
 * Dữ liệu dùng chung cho trang Team & Members và trang chi tiết team:
 * danh sách team, thành viên dự án, tải công việc.
 *
 * `setMemberRoles` vá vai trò của một người ngay tại chỗ (không tải lại cả trang),
 * nhờ vậy popup "+ vai trò" vẫn mở sau khi gán.
 */
export function useTeamData(projectId: number) {
  const [version, setVersion] = useState(0)
  const [roleOverrides, setRoleOverrides] = useState<Record<number, Role[]>>({})

  const teams = useRequest(`teams:${projectId}:${version}`, () => listTeams(projectId))
  const members = useRequest(`members:${projectId}:all:${version}`, () => listMembers(projectId))
  const workload = useRequest(`workload:${projectId}:${version}`, () => getWorkload(projectId))

  const memberList = useMemo(
    () => (members.data ?? []).map((m) => (roleOverrides[m.user.id] ? { ...m, roles: roleOverrides[m.user.id] } : m)),
    [members.data, roleOverrides],
  )

  const reload = useCallback(() => {
    setRoleOverrides({})
    setVersion((v) => v + 1)
  }, [])

  const setMemberRoles = useCallback((userId: number, roles: Role[]) => {
    setRoleOverrides((current) => ({ ...current, [userId]: roles }))
  }, [])

  return {
    teams: teams.data ?? [],
    members: memberList,
    workload: workload.data ?? [],
    isLoading: teams.isLoading || members.isLoading || workload.isLoading,
    error: teams.error ?? members.error ?? workload.error,
    retry: () => {
      teams.retry()
      members.retry()
      workload.retry()
    },
    reload,
    setMemberRoles,
  }
}
