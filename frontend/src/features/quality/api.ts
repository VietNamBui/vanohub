import { apiClient } from '../../shared/api/client'
import { cleanParams } from '../../shared/api/types'
import type { Audit, AuditSample, AuditStrategy, ErrorCategory, ErrorInput, Qc2Summary } from './types'

const p = (projectId: number, path: string) => `/projects/${projectId}/${path}`

// --- Danh mục lỗi (QC2 chọn khi Reject; trang quản lý đã bỏ khỏi menu) ---
export const listErrorCategories = async (projectId: number, stage?: 'qc1' | 'qc2') =>
  (await apiClient.get<ErrorCategory[]>(p(projectId, 'error-categories/'), { params: cleanParams({ stage }) })).data

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
export const rejectSample = async (projectId: number, sampleId: number, errors: ErrorInput[], comment = '') =>
  (await apiClient.post<AuditSample>(p(projectId, `audit-samples/${sampleId}/reject/`), { errors, comment })).data
export const assignSampleAuditor = async (projectId: number, sampleId: number, auditor: number) =>
  (await apiClient.post<AuditSample>(p(projectId, `audit-samples/${sampleId}/assign/`), { auditor })).data

export const getQc2Summary = async (projectId: number, period: string, scope?: 'mine') =>
  (await apiClient.get<Qc2Summary>(p(projectId, 'qc2-summary/'), { params: cleanParams({ period, scope }) })).data

export const getAuditStrategy = async (projectId: number) =>
  (await apiClient.get<AuditStrategy>(p(projectId, 'audit-strategy/'))).data
