// Lưu JWT trong localStorage — đơn giản cho giai đoạn MVP.
// Đánh đổi: nếu trang bị XSS thì token có thể bị đọc. Có thể chuyển refresh token
// sang cookie HttpOnly sau này mà không phải sửa các nơi gọi API.

const ACCESS_KEY = 'vanohub.access'
const REFRESH_KEY = 'vanohub.refresh'

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

export const tokenStorage = {
  getAccess: () => read(ACCESS_KEY),
  getRefresh: () => read(REFRESH_KEY),
  save(access: string, refresh?: string) {
    try {
      localStorage.setItem(ACCESS_KEY, access)
      if (refresh) localStorage.setItem(REFRESH_KEY, refresh)
    } catch {
      // Trình duyệt chặn storage: phiên chỉ sống đến khi tải lại trang.
    }
  },
  clear() {
    try {
      localStorage.removeItem(ACCESS_KEY)
      localStorage.removeItem(REFRESH_KEY)
    } catch {
      // bỏ qua
    }
  },
}
