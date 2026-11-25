import { apiClient } from '../../shared/api/client'
import { cleanParams, type Paginated } from '../../shared/api/types'
import type { Role } from '../../shared/types/roles'
import type {
  ActivityLog,
  Announcement,
  Batch,
  Dataset,
  Delivery,
  DeliveryCandidate,
  Guideline,
  Member,
  MemberPerformance,
  NotificationFeed,
  PermissionMatrix,
  ProjectDetail,
  ProjectOverview,
  ProjectSettings,
  ProjectSummary,
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
export const createDataset = async (id: number, data: { name: string; description?: string }) =>
  (await apiClient.post<Dataset>(p(id, 'datasets/'), data)).data
export const updateDataset = async (id: number, datasetId: number, data: Partial<Dataset>) =>
  (await apiClient.patch<Dataset>(p(id, `datasets/${datasetId}/`), data)).data
export const setDatasetLock = async (id: number, datasetId: number, lock: boolean) =>
  (await apiClient.post<Dataset>(p(id, `datasets/${datasetId}/${lock ? 'lock' : 'unlock'}/`))).data

// --- Batch ---
export const listBatches = async (id: number, params: { dataset?: number; status?: string; search?: string } = {}) =>
  (await apiClient.get<Batch[]>(p(id, 'batches/'), { params: cleanParams(params) })).data
export const createBatch = async (id: number, data: { dataset: number; name: string; deadline?: string | null }) =>
  (await apiClient.post<Batch>(p(id, 'batches/'), data)).data
export const updateBatch = async (id: number, batchId: number, data: { name?: string; deadline?: string | null; team?: number | null }) =>
  (await apiClient.patch<Batch>(p(id, `batches/${batchId}/`), data)).data
export const setBatchLock = async (id: number, batchId: number, lock: boolean) =>
  (await apiClient.post<Batch>(p(id, `batches/${batchId}/${lock ? 'lock' : 'unlock'}/`))).data
export const importBatchFromCvat = async (id: number, batchId: number, cvatTaskId: number) =>
  (
    await apiClient.post<{ task_name: string; created: number; updated: number; total: number }>(
      p(id, `batches/${batchId}/import-cvat/`),
      { cvat_task_id: cvatTaskId },
    )
  ).data
export const syncBatchWithCvat = async (id: number, batchId: number, countObjects: boolean) =>
  (
    await apiClient.post<{ updated: number; total: number }>(p(id, `batches/${batchId}/sync-cvat/`), {
      count_objects: countObjects,
    })
  ).data

// --- Delivery ---
export const listDeliveries = async (id: number) => (await apiClient.get<Delivery[]>(p(id, 'deliveries/'))).data
export const listDeliveryCandidates = async (id: number) =>
  (await apiClient.get<DeliveryCandidate[]>(p(id, 'deliveries/candidates/'))).data
export const createDelivery = async (id: number, data: { batch: number; note?: string }) =>
  (await apiClient.post<Delivery>(p(id, 'deliveries/'), data)).data
export const updateDelivery = async (id: number, deliveryId: number, data: { note?: string; client_feedback?: string }) =>
  (await apiClient.patch<Delivery>(p(id, `deliveries/${deliveryId}/`), data)).data

// --- Nhật ký, thông báo, guideline ---
export const listActivity = async (
  id: number,
  params: { page?: number; actor?: number; action?: string; date_from?: string; date_to?: string },
) => (await apiClient.get<Paginated<ActivityLog>>(p(id, 'activity/'), { params: cleanParams(params) })).data
export const listAnnouncements = async (id: number) =>
  (await apiClient.get<Announcement[]>(p(id, 'announcements/'))).data
export const listProjectNotifications = async (id: number) =>
  (await apiClient.get<NotificationFeed>(p(id, 'notifications/'))).data
export const markProjectNotificationsRead = async (id: number, notification_id?: number) =>
  (
    await apiClient.post<{ updated: number }>(
      p(id, 'notifications/mark-read/'),
      notification_id != null ? { notification_id } : {},
    )
  ).data
export const sendAnnouncement = async (
  id: number,
  data: { content: string; target_roles: string[]; target_team?: number | null },
) => (await apiClient.post<Announcement>(p(id, 'announcements/'), data)).data
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
/** Gán thêm một vai trò trong dự án cho thành viên. Trả về toàn bộ vai trò hiệu lực sau khi gán. */
export const addMemberRole = async (id: number, userId: number, role: Role) =>
  (await apiClient.post<{ user: number; roles: Role[] }>(p(id, `members/${userId}/roles/`), { role })).data
