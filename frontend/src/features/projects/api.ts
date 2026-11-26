import { apiClient } from '../../shared/api/client'
import { cleanParams, type Paginated } from '../../shared/api/types'
import type { Role } from '../../shared/types/roles'
import type {
  ActivityLog,
  Announcement,
  CreatedMember,
  CreateMemberInput,
  Batch,
  CvatLabel,
  Dataset,
  Guideline,
  Member,
  MemberCredential,
  MemberPerformance,
  PermissionMatrix,
  ProjectDetail,
  ProjectOverview,
  ProjectSettings,
  ProjectSummary,
  ProjectsSyncResult,
  ProjectSyncResult,
  TeamRanking,
} from './types'

const p = (projectId: number, path: string) => `/projects/${projectId}/${path}`

export const listProjects = async () => (await apiClient.get<ProjectSummary[]>('/projects/')).data
export const getProject = async (id: number) => (await apiClient.get<ProjectDetail>(`/projects/${id}/`)).data

// --- Cấu hình & thành viên ---
export const getSettings = async (id: number) => (await apiClient.get<ProjectSettings>(p(id, 'settings/'))).data
export const updateSettings = async (id: number, data: Partial<ProjectSettings>) =>
  (await apiClient.patch<ProjectSettings>(p(id, 'settings/'), data)).data
export const listMembers = async (id: number, role?: string) =>
  (await apiClient.get<Member[]>(p(id, 'members/'), { params: cleanParams({ role }) })).data
export const getPermissionMatrix = async (id: number) =>
  (await apiClient.get<PermissionMatrix>(p(id, 'permission-matrix/'))).data

// --- Dataset ---
export const listDatasets = async (id: number, params: { status?: string; search?: string } = {}) =>
  (await apiClient.get<Dataset[]>(p(id, 'datasets/'), { params: cleanParams(params) })).data
export const updateDataset = async (id: number, datasetId: number, data: Partial<Dataset>) =>
  (await apiClient.patch<Dataset>(p(id, `datasets/${datasetId}/`), data)).data
export const setDatasetLock = async (id: number, datasetId: number, lock: boolean) =>
  (await apiClient.post<Dataset>(p(id, `datasets/${datasetId}/${lock ? 'lock' : 'unlock'}/`))).data

// --- Batch ---
/** "Task" (CVAT task) của organization. */
export const listBatches = async (id: number, params: { dataset?: number; status?: string; search?: string } = {}) =>
  (await apiClient.get<Batch[]>(p(id, 'batches/'), { params: cleanParams(params) })).data
export const updateBatch = async (id: number, batchId: number, data: { deadline?: string | null; team?: number | null }) =>
  (await apiClient.patch<Batch>(p(id, `batches/${batchId}/`), data)).data
export const setBatchLock = async (id: number, batchId: number, lock: boolean) =>
  (await apiClient.post<Batch>(p(id, `batches/${batchId}/${lock ? 'lock' : 'unlock'}/`))).data

// --- Đồng bộ CVAT (Organization → Project → Task → Job) ---
/** Kéo project / task / job của organization từ CVAT về. */
export const syncProjectWithCvat = async (id: number, countObjects = false) =>
  (await apiClient.post<ProjectSyncResult>(p(id, 'cvat-sync/'), { count_objects: countObjects }, { timeout: 120_000 })).data
/** Kéo CVAT organization (và vai trò thành viên) về VanoHub. */
export const syncOrganizationsFromCvat = async () =>
  (await apiClient.post<ProjectsSyncResult>('/cvat/sync-organizations/', {}, { timeout: 120_000 })).data
/** Bộ nhãn của một CVAT project (Dataset). */
export const getDatasetLabels = async (id: number, datasetId: number) =>
  (await apiClient.get<{ labels: CvatLabel[]; detail?: string }>(p(id, `datasets/${datasetId}/labels/`))).data

// --- Nhật ký, thông báo, guideline ---
export const listActivity = async (
  id: number,
  params: { page?: number; actor?: number; action?: string; date_from?: string; date_to?: string },
) => (await apiClient.get<Paginated<ActivityLog>>(p(id, 'activity/'), { params: cleanParams(params) })).data
export const listAnnouncements = async (id: number) =>
  (await apiClient.get<Announcement[]>(p(id, 'announcements/'))).data
export const listGuidelines = async (id: number) => (await apiClient.get<Guideline[]>(p(id, 'guidelines/'))).data
export const publishGuideline = async (id: number, data: { title: string; content: string }) =>
  (await apiClient.post<Guideline>(p(id, 'guidelines/'), data)).data

// --- Analytics ---
export const getOverview = async (id: number, period: string) =>
  (await apiClient.get<ProjectOverview>(p(id, 'overview/'), { params: { period } })).data
export const getTeamRanking = async (id: number) => (await apiClient.get<TeamRanking>(p(id, 'team-ranking/'))).data
export const getMemberPerformance = async (id: number) =>
  (await apiClient.get<MemberPerformance[]>(p(id, 'member-performance/'))).data

// --- CVAT ---
export const getCvatStatus = async () =>
  (await apiClient.get<{ connected: boolean; url: string; version?: string; detail?: string }>('/cvat/status/')).data
/** PM tạo tài khoản mới cho thành viên — hệ thống sinh tài khoản (nếu bỏ trống) và mật khẩu tạm. */
export const createMember = async (id: number, data: CreateMemberInput) =>
  (await apiClient.post<CreatedMember>(p(id, 'members/'), data)).data
/** Xem tài khoản + mật khẩu tạm (mỗi lần xem đều được ghi lịch sử). */
export const getMemberCredential = async (id: number, userId: number) =>
  (await apiClient.get<MemberCredential>(p(id, `members/${userId}/credential/`))).data
export const resetMemberPassword = async (id: number, userId: number) =>
  (await apiClient.post<MemberCredential>(p(id, `members/${userId}/reset-password/`))).data

/** Gán thêm một vai trò trong dự án cho thành viên. Trả về toàn bộ vai trò hiệu lực sau khi gán. */
export const addMemberRole = async (id: number, userId: number, role: Role) =>
  (await apiClient.post<MemberRoles>(p(id, `members/${userId}/roles/`), { role })).data
/** Gỡ một vai trò. Backend từ chối nếu là vai trò cuối cùng, vai trò đi kèm, hoặc người đó đang giữ việc của vai trò ấy. */
export const removeMemberRole = async (id: number, userId: number, role: Role) =>
  (await apiClient.delete<MemberRoles>(p(id, `members/${userId}/roles/${role}/`))).data

export interface MemberRoles {
  user: number
  roles: Role[]
  direct_roles: Role[]
}
