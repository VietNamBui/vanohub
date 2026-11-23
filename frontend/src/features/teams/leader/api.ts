import { apiClient } from '../../../shared/api/client'
import { cleanParams, type Paginated } from '../../../shared/api/types'
import type { Role } from '../../../shared/types/roles'
import type { AssignInput } from '../../jobs/api'
import type { Job, JobDetail } from '../../jobs/types'
import type { LeaderDashboard, LeaderJobTab, LeaderTeam } from './types'

const p = (projectId: number, path: string) => `/projects/${projectId}/leader/${path}`

export const listLeaderTeams = async (projectId: number) => (await apiClient.get<LeaderTeam[]>(p(projectId, 'teams/'))).data
export const getLeaderDashboard = async (projectId: number, period: string, team?: number) =>
  (await apiClient.get<LeaderDashboard>(p(projectId, 'dashboard/'), { params: cleanParams({ period, team }) })).data

export const listLeaderJobs = async (projectId: number, params: { tab?: LeaderJobTab; search?: string; team?: number; page?: number }) =>
  (await apiClient.get<Paginated<Job>>(p(projectId, 'jobs/'), {
    params: cleanParams({ ...params, tab: params.tab === 'all' ? undefined : params.tab, page_size: 50 }),
  })).data
export const getLeaderJob = async (projectId: number, jobId: number) => (await apiClient.get<JobDetail>(p(projectId, `jobs/${jobId}/`))).data
export const leaderAssign = async (projectId: number, jobId: number, data: AssignInput) =>
  (await apiClient.post<JobDetail>(p(projectId, `jobs/${jobId}/assign/`), data)).data
export const leaderDeadline = async (projectId: number, jobId: number, deadline: string | null, note = '') =>
  (await apiClient.post<JobDetail>(p(projectId, `jobs/${jobId}/deadline/`), { deadline, note })).data
export const leaderBulkAssign = async (projectId: number, ids: number[], data: AssignInput) =>
  (await apiClient.post<{ updated: number }>(p(projectId, 'jobs/bulk-assign/'), { ids, ...data })).data
export const leaderBulkDeadline = async (projectId: number, ids: number[], deadline: string | null, note = '') =>
  (await apiClient.post<{ updated: number }>(p(projectId, 'jobs/bulk-deadline/'), { ids, deadline, note })).data

export const grantQc1 = async (projectId: number, teamId: number, userId: number) =>
  (await apiClient.post<{ user: number; roles: Role[] }>(p(projectId, `teams/${teamId}/members/${userId}/qc1/`))).data
export const revokeQc1 = async (projectId: number, teamId: number, userId: number) =>
  (await apiClient.delete<{ user: number; roles: Role[] }>(p(projectId, `teams/${teamId}/members/${userId}/qc1/`))).data
