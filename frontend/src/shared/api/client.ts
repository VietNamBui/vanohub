import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { tokenStorage } from './tokenStorage'

/** Axios instance dùng chung cho mọi lời gọi API của Vanohub. */
export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
})

// 1) Trước mỗi request: gắn access token nếu có.
apiClient.interceptors.request.use((config) => {
  const access = tokenStorage.getAccess()
  if (access) config.headers.Authorization = `Bearer ${access}`
  return config
})

// 2) Khi nhận 401: thử làm mới access token MỘT lần rồi gửi lại request.
//    Nếu nhiều request cùng gặp 401, chúng dùng chung một lần refresh.
let refreshing: Promise<string> | null = null
let onSessionExpired: () => void = () => {}

/** AuthProvider đăng ký hàm này để đưa người dùng về trạng thái chưa đăng nhập. */
export function setSessionExpiredHandler(handler: () => void) {
  onSessionExpired = handler
}

async function refreshAccessToken(): Promise<string> {
  const refresh = tokenStorage.getRefresh()
  if (!refresh) throw new Error('No refresh token')
  // Dùng axios gốc (không qua interceptor) để tránh vòng lặp.
  const { data } = await axios.post<{ access: string }>(
    `${import.meta.env.VITE_API_BASE_URL}/auth/token/refresh/`,
    { refresh },
  )
  tokenStorage.save(data.access)
  return data.access
}

type RetriableConfig = InternalAxiosRequestConfig & { _retried?: boolean }

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetriableConfig | undefined
    const isAuthEndpoint = config?.url?.startsWith('/auth/token')

    if (error.response?.status !== 401 || !config || config._retried || isAuthEndpoint) {
      throw error
    }

    config._retried = true
    try {
      refreshing ??= refreshAccessToken().finally(() => {
        refreshing = null
      })
      const access = await refreshing
      config.headers.Authorization = `Bearer ${access}`
      return apiClient(config)
    } catch {
      tokenStorage.clear()
      onSessionExpired()
      throw error
    }
  },
)
