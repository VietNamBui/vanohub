import { apiClient } from '../../shared/api/client'

export interface CvatLinkState {
  linked: boolean
  cvat_user_id: number | null
  cvat_username: string | null
  linked_at: string | null
  /** Địa chỉ CVAT mở trên trình duyệt (để tạo Access Token). */
  cvat_url: string
  /** Số job (có trên CVAT) bạn đang giữ. */
  jobs_held: number
  /** Chỉ có sau khi liên kết / huỷ liên kết: kết quả đẩy assignee sang CVAT. */
  sync?: { pushed: number; error: string | null }
}

export const getCvatLink = async () => (await apiClient.get<CvatLinkState>('/cvat/link/')).data
/** Token chỉ dùng để xác minh rồi bị bỏ, backend không lưu. */
export const linkCvat = async (token: string) => (await apiClient.post<CvatLinkState>('/cvat/link/', { token })).data
export const unlinkCvat = async () => (await apiClient.delete<CvatLinkState>('/cvat/link/')).data
