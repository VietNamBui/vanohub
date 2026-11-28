import { apiClient } from '../../shared/api/client'
import { cleanParams, type Paginated } from '../../shared/api/types'
import type { Job, JobDetail, ReworkScope } from '../jobs/types'
import type {
  Audit,
  AuditSample,
  AuditStrategy,
  ErrorCategory,
  ErrorCategoryInput,
  ErrorInput,
  JobIssue,
  JobIssueDisputeResult,
  JobIssueImportResult,
  JobIssueListParams,
  JobIssueRulePayload,
  Qc1JobTab,
  Qc1Scope,
  Qc1Summary,
  Qc2Summary,
} from './types'

const p = (projectId: number, path: string) => `/projects/${projectId}/${path}`

function serializeErrorInput(error: ErrorInput): ErrorInput {
  const isMissingObject = Boolean(error.is_missing_object)
  return {
    category: error.category,
    ...(error.job_issue != null ? { job_issue: error.job_issue } : {}),
    severity: error.severity,
    verdict: isMissingObject ? 'fail' : (error.verdict ?? 'fail'),
    frame_number: error.frame_number ?? null,
    cvat_object_id: isMissingObject ? null : (error.cvat_object_id ?? null),
    is_missing_object: isMissingObject,
    location: error.location ?? '',
    description: error.description ?? '',
  }
}

// --- Danh mục lỗi (QC1 & QC2 chọn khi Reject; giữ CRUD trong Hybrid để kiểm tra) ---
export const listErrorCategories = async (projectId: number, stage?: 'qc1' | 'qc2') =>
  (await apiClient.get<ErrorCategory[]>(p(projectId, 'error-categories/'), { params: cleanParams({ stage }) })).data
export const createErrorCategory = async (
  projectId: number,
  data: ErrorCategoryInput,
) => (await apiClient.post<ErrorCategory>(p(projectId, 'error-categories/'), data)).data
export const updateErrorCategory = async (
  projectId: number,
  categoryId: number,
  data: ErrorCategoryInput,
) => (await apiClient.patch<ErrorCategory>(p(projectId, `error-categories/${categoryId}/`), data)).data

// --- Audit (quản lý) ---
export const listAudits = async (projectId: number, params: { status?: string; batch?: number } = {}) =>
  (await apiClient.get<Audit[]>(p(projectId, 'audits/'), { params: cleanParams(params) })).data

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
export const rejectSample = async (
  projectId: number,
  sampleId: number,
  errors: ErrorInput[],
  comment = '',
  rework_scope: ReworkScope = 'partial',
) =>
  (
    await apiClient.post<AuditSample>(p(projectId, `audit-samples/${sampleId}/reject/`), {
      errors: errors.map(serializeErrorInput),
      comment,
      rework_scope,
    })
  ).data
export const rejectAuditSample = rejectSample
export const assignSampleAuditor = async (projectId: number, sampleId: number, auditor: number) =>
  (await apiClient.post<AuditSample>(p(projectId, `audit-samples/${sampleId}/assign/`), { auditor })).data

export const getQc2Summary = async (projectId: number, period: string, scope?: 'mine') =>
  (await apiClient.get<Qc2Summary>(p(projectId, 'qc2-summary/'), { params: cleanParams({ period, scope }) })).data

export const getAuditStrategy = async (projectId: number) =>
  (await apiClient.get<AuditStrategy>(p(projectId, 'audit-strategy/'))).data

// --- Level 1 QC (QC1) ---
export const listQc1Jobs = async (
  projectId: number,
  params: {
    scope?: Qc1Scope
    tab?: Qc1JobTab
    search?: string
    page?: number
    page_size?: number
    overdue?: boolean
    due_soon?: boolean
  } = {},
) =>
  (
    await apiClient.get<Paginated<Job>>(p(projectId, 'qc1/jobs/'), {
      params: cleanParams({
        scope: params.scope,
        tab: params.tab === 'all' ? undefined : params.tab,
        search: params.search,
        page: params.page,
        page_size: params.page_size,
        overdue: params.overdue ? 1 : undefined,
        due_soon: params.due_soon ? 1 : undefined,
      }),
    })
  ).data

export const getQc1Job = async (projectId: number, jobId: number) =>
  (await apiClient.get<JobDetail>(p(projectId, `qc1/jobs/${jobId}/`))).data

export const startQc1Job = async (projectId: number, jobId: number, note = '') =>
  (await apiClient.post<JobDetail>(p(projectId, `qc1/jobs/${jobId}/start/`), { note })).data

export const passQc1Job = async (projectId: number, jobId: number, comment = '') =>
  (await apiClient.post<JobDetail>(p(projectId, `qc1/jobs/${jobId}/pass/`), { comment })).data

export const rejectQc1Job = async (
  projectId: number,
  jobId: number,
  errors: ErrorInput[],
  comment = '',
  rework_scope: ReworkScope = 'partial',
) =>
  (
    await apiClient.post<JobDetail>(p(projectId, `qc1/jobs/${jobId}/reject/`), {
      errors: errors.map(serializeErrorInput),
      comment,
      rework_scope,
    })
  ).data
export const qc1RejectJob = rejectQc1Job

export const getQc1Summary = async (projectId: number, period: string, scope?: 'mine') =>
  (await apiClient.get<Qc1Summary>(p(projectId, 'qc1-summary/'), { params: cleanParams({ period, scope }) })).data

// --- Job Issues (đồng bộ một chiều từ CVAT + vòng đời VanoHub) ---
export const listJobIssues = async (projectId: number, params: JobIssueListParams = {}) =>
  (
    await apiClient.get<Paginated<JobIssue>>(p(projectId, 'issues/'), {
      params: cleanParams({
        job: params.job,
        status: params.status,
        severity: params.severity,
        primary_category: params.primary_category,
        authority_status: params.authority_status,
        is_clarification:
          params.is_clarification !== undefined ? (params.is_clarification ? 1 : 0) : undefined,
        is_disputed: params.is_disputed !== undefined ? (params.is_disputed ? 1 : 0) : undefined,
        tampered: params.tampered !== undefined ? (params.tampered ? 1 : 0) : undefined,
        source_missing: params.source_missing !== undefined ? (params.source_missing ? 1 : 0) : undefined,
        page: params.page,
        page_size: params.page_size,
      }),
    })
  ).data

export const importJobIssues = async (projectId: number, jobId: number) =>
  (await apiClient.post<JobIssueImportResult>(p(projectId, 'issues/import/'), { job: jobId })).data

export const addressJobIssue = async (projectId: number, issueId: number, note = '') =>
  (await apiClient.post<JobIssue>(p(projectId, `issues/${issueId}/address/`), { note })).data

export const disputeJobIssue = async (projectId: number, issueId: number, reason: string) =>
  (await apiClient.post<JobIssueDisputeResult>(p(projectId, `issues/${issueId}/dispute/`), { reason })).data

export const resolveJobIssue = async (projectId: number, issueId: number, note = '') =>
  (await apiClient.post<JobIssue>(p(projectId, `issues/${issueId}/resolve/`), { note })).data

export const reopenJobIssue = async (projectId: number, issueId: number, note = '') =>
  (await apiClient.post<JobIssue>(p(projectId, `issues/${issueId}/reopen/`), { note })).data

export const ruleJobIssue = async (projectId: number, issueId: number, payload: JobIssueRulePayload) =>
  (await apiClient.post<JobIssue>(p(projectId, `issues/${issueId}/rule/`), payload)).data
