import { apiClient } from '../../../shared/api/client'
import { cleanParams, type Paginated } from '../../../shared/api/types'
import type { AnnotatorDashboard, AnnotatorJobTab, Job, JobDetail, JobFilters, QueueStage } from '../types'

const p = (projectId: number, path: string) => `/projects/${projectId}/${path}`

export const listJobs = async (projectId: number, filters: JobFilters) =>
  (
    await apiClient.get<Paginated<Job>>(p(projectId, 'jobs/'), {
      params: cleanParams({
        ...filters,
        escalated: filters.escalated ? 1 : undefined,
        overdue: filters.overdue ? 1 : undefined,
        unassigned: filters.unassigned ? 1 : undefined,
        locked: filters.locked ? 1 : undefined,
      }),
    })
  ).data

export const getJob = async (projectId: number, jobId: number) =>
  (await apiClient.get<JobDetail>(p(projectId, `jobs/${jobId}/`))).data

export interface AssignInput {
  annotator?: number | null
  qc1_reviewer?: number | null
  note?: string
}

export const assignJob = async (projectId: number, jobId: number, data: AssignInput) =>
  (await apiClient.post<JobDetail>(p(projectId, `jobs/${jobId}/assign/`), data)).data
export const setJobDeadline = async (projectId: number, jobId: number, deadline: string | null, note = '') =>
  (await apiClient.post<JobDetail>(p(projectId, `jobs/${jobId}/deadline/`), { deadline, note })).data
export const setJobLock = async (projectId: number, jobId: number, lock: boolean, note = '') =>
  (await apiClient.post<JobDetail>(p(projectId, `jobs/${jobId}/${lock ? 'lock' : 'unlock'}/`), { note })).data
export const resolveEscalation = async (projectId: number, jobId: number, annotator: number | undefined, note: string) =>
  (
    await apiClient.post<JobDetail>(p(projectId, `jobs/${jobId}/resolve-escalation/`), {
      ...(annotator ? { annotator } : {}),
      note,
    })
  ).data
export const bulkAssign = async (projectId: number, ids: number[], data: AssignInput) =>
  (await apiClient.post<{ updated: number }>(p(projectId, 'jobs/bulk-assign/'), { ids, ...data })).data
export const bulkDeadline = async (projectId: number, ids: number[], deadline: string | null, note = '') =>
  (await apiClient.post<{ updated: number }>(p(projectId, 'jobs/bulk-deadline/'), { ids, deadline, note })).data

export const getJobQueue = async (projectId: number, batch?: number) =>
  (
    await apiClient.get<{ stages: QueueStage[]; done: number; total: number }>(p(projectId, 'job-queue/'), {
      params: cleanParams({ batch }),
    })
  ).data

// --- Không gian làm việc Annotator ---
export const listAnnotatorJobs = async (
  projectId: number,
  params: { tab?: AnnotatorJobTab; search?: string; page?: number; overdue?: boolean } = {},
) =>
  (
    await apiClient.get<Paginated<Job>>(p(projectId, 'annotator/jobs/'), {
      params: cleanParams({
        tab: params.tab === 'all' ? undefined : params.tab,
        search: params.search,
        page: params.page,
        overdue: params.overdue ? 1 : undefined,
      }),
    })
  ).data

export const getAnnotatorJob = async (projectId: number, jobId: number) =>
  (await apiClient.get<JobDetail>(p(projectId, `annotator/jobs/${jobId}/`))).data

export const startAnnotatorJob = async (projectId: number, jobId: number, note = '') =>
  (await apiClient.post<JobDetail>(p(projectId, `annotator/jobs/${jobId}/start/`), { note })).data

export const submitAnnotatorJob = async (
  projectId: number,
  jobId: number,
  data: { note?: string; object_count?: number | null } = {},
) => (await apiClient.post<JobDetail>(p(projectId, `annotator/jobs/${jobId}/submit/`), data)).data

export const getAnnotatorDashboard = async (projectId: number, period: string) =>
  (await apiClient.get<AnnotatorDashboard>(p(projectId, 'annotator/dashboard/'), { params: cleanParams({ period }) })).data
