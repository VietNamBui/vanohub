import { apiClient } from '../../shared/api/client'
import { cleanParams } from '../../shared/api/types'
import type { Team, Workload } from './types'

const p = (projectId: number, path: string) => `/projects/${projectId}/${path}`

export const listTeams = async (projectId: number) => (await apiClient.get<Team[]>(p(projectId, 'teams/'))).data
export const createTeam = async (projectId: number, data: { name: string; leader?: number | null }) =>
  (await apiClient.post<Team>(p(projectId, 'teams/'), data)).data
export const updateTeam = async (projectId: number, teamId: number, data: { name?: string; leader?: number | null }) =>
  (await apiClient.patch<Team>(p(projectId, `teams/${teamId}/`), data)).data
export const deleteTeam = async (projectId: number, teamId: number) => {
  await apiClient.delete(p(projectId, `teams/${teamId}/`))
}
export const addTeamMember = async (projectId: number, teamId: number, user: number, capacity?: number) =>
  (await apiClient.post<Team>(p(projectId, `teams/${teamId}/add-member/`), { user, capacity })).data
export const removeTeamMember = async (projectId: number, teamId: number, user: number) =>
  (await apiClient.post<Team>(p(projectId, `teams/${teamId}/remove-member/`), { user })).data
export const setMemberCapacity = async (projectId: number, teamId: number, user: number, capacity: number) =>
  (await apiClient.post<Team>(p(projectId, `teams/${teamId}/set-capacity/`), { user, capacity })).data
export const transferMember = async (projectId: number, user: number, toTeam: number) =>
  (await apiClient.post(p(projectId, 'teams/transfer/'), { user, to_team: toTeam })).data
export const getWorkload = async (projectId: number, team?: number) =>
  (await apiClient.get<Workload[]>(p(projectId, 'teams/workload/'), { params: cleanParams({ team }) })).data
