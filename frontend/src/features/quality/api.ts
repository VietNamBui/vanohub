import { apiClient } from '../../shared/api/client'
import { cleanParams, type Paginated } from '../../shared/api/types'
import type { Job, JobDetail } from '../jobs/types'
import type {
  Audit,
  AuditInput,
  AuditPreview,
  AuditSample,
  AuditStrategy,
  ErrorCategory,
  ErrorInput,
  Qc1JobTab,
  Qc1Scope,
  Qc1Summary,
  Qc2Summary,
} from './types'

const p = (projectId: number, path: string) => `/projects/${projectId}/${path}`

// --- Danh mục lỗi ---
export const listErrorCategories = async (projectId: number, stage?: 'qc1' | 'qc2') =>
  (await apiClient.get<ErrorCategory[]>(p(projectId, 'error-categories/'), { params: cleanParams({ stage }) })).data
export const createErrorCategory = async (projectId: number, data: Partial<ErrorCategory>) =>
  (await apiClient.post<ErrorCategory>(p(projectId, 'error-categories/'), data)).data
export const updateErrorCategory = async (projectId: number, id: number, data: Partial<ErrorCategory>) =>
  (await apiClient.patch<ErrorCategory>(p(projectId, `error-categories/${id}/`), data)).data

// --- Audit (quản lý) ---
export const listAudits = async (projectId: number, params: { status?: string; batch?: number } = {}) =>
  (await apiClient.get<Audit[]>(p(projectId, 'audits/'), { params: cleanParams(params) })).data
export const previewAudit = async (projectId: number, data: AuditInput) =>
  (await apiClient.post<AuditPreview>(p(projectId, 'audits/preview/'), data)).data
export const createAudit = async (projectId: number, data: AuditInput) =>
  (await apiClient.post<Audit>(p(projectId, 'audits/'), data)).data
export const completeAudit = async (projectId: number, auditId: number) =>
  (await apiClient.post<Audit>(p(projectId, `audits/${auditId}/complete/`))).data

// --- Mẫu audit (thực hiện QC2) ---
export const listAuditSamples = async (
  projectId: number,
  params: { audit?: number; result?: string; mine?: boolean; open?: boolean } = {},
) =>
  (
    await apiClient.get<AuditSample[]>(p(projectId, 'audit-samples/'), {
      params: cleanParams({ ...params, mine: params.mine ? 1 : undefined, open: params.open ? 1 : undefined }),
    })
  ).data
export const passSample = async (projectId: number, sampleId: number, comment = '') =>
  (await apiClient.post<AuditSample>(p(projectId, `audit-samples/${sampleId}/pass/`), { comment })).data
export const rejectSample = async (projectId: number, sampleId: number, errors: ErrorInput[], comment = '') =>
  (await apiClient.post<AuditSample>(p(projectId, `audit-samples/${sampleId}/reject/`), { errors, comment })).data
export const assignSampleAuditor = async (projectId: number, sampleId: number, auditor: number) =>
  (await apiClient.post<AuditSample>(p(projectId, `audit-samples/${sampleId}/assign/`), { auditor })).data

export const getQc2Summary = async (projectId: number, period: string, scope?: 'mine') =>
  (await apiClient.get<Qc2Summary>(p(projectId, 'qc2-summary/'), { params: cleanParams({ period, scope }) })).data

export const getAuditStrategy = async (projectId: number) =>
  (await apiClient.get<AuditStrategy>(p(projectId, 'audit-strategy/'))).data

// --- Level 1 QC (QC1) ---
export const listQc1Jobs = async (
  projectId: number,
  params: { scope?: Qc1Scope; tab?: Qc1JobTab; search?: string; page?: number; overdue?: boolean } = {},
) =>
  (
    await apiClient.get<Paginated<Job>>(p(projectId, 'qc1/jobs/'), {
      params: cleanParams({
        scope: params.scope,
        tab: params.tab === 'all' ? undefined : params.tab,
        search: params.search,
        page: params.page,
        overdue: params.overdue ? 1 : undefined,
      }),
    })
  ).data

export const getQc1Job = async (projectId: number, jobId: number) =>
  (await apiClient.get<JobDetail>(p(projectId, `qc1/jobs/${jobId}/`))).data

export const startQc1Job = async (projectId: number, jobId: number, note = '') =>
  (await apiClient.post<JobDetail>(p(projectId, `qc1/jobs/${jobId}/start/`), { note })).data

export const passQc1Job = async (projectId: number, jobId: number, comment = '') =>
  (await apiClient.post<JobDetail>(p(projectId, `qc1/jobs/${jobId}/pass/`), { comment })).data

export const rejectQc1Job = async (projectId: number, jobId: number, errors: ErrorInput[], comment = '') =>
  (await apiClient.post<JobDetail>(p(projectId, `qc1/jobs/${jobId}/reject/`), { errors, comment })).data

export const getQc1Summary = async (projectId: number, period: string, scope?: 'mine') =>
  (await apiClient.get<Qc1Summary>(p(projectId, 'qc1-summary/'), { params: cleanParams({ period, scope }) })).data
