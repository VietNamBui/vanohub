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
  const [roleOverrides, setRoleOverrides] = useState<Record<number, RoleState>>({})

  const teams = useRequest(`teams:${projectId}:${version}`, () => listTeams(projectId))
  const members = useRequest(`members:${projectId}:all:${version}`, () => listMembers(projectId))
  const workload = useRequest(`workload:${projectId}:${version}`, () => getWorkload(projectId))

  const memberList = useMemo(
    () => (members.data ?? []).map((m) => (roleOverrides[m.user.id] ? { ...m, ...roleOverrides[m.user.id] } : m)),
    [members.data, roleOverrides],
  )

  const reload = useCallback(() => {
    setRoleOverrides({})
    setVersion((v) => v + 1)
  }, [])

  const setMemberRoles = useCallback((userId: number, roles: RoleState) => {
    setRoleOverrides((current) => ({ ...current, [userId]: roles }))
  }, [])

  /** Vai trò của một người: vai trò vừa gán trên giao diện (nếu có), không thì vai trò backend trả kèm. */
  const rolesOf = useCallback((userId: number, fallback: RoleState): RoleState => roleOverrides[userId] ?? fallback, [roleOverrides])

  return {
    rolesOf,
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

/** Vai trò hiệu lực + vai trò gán trực tiếp của một người. */
export interface RoleState {
  roles: Role[]
  direct_roles: Role[]
}
