import { isAxiosError } from 'axios'

export type ErrorKind = 'unauthorized' | 'forbidden' | 'not_found' | 'network' | 'validation' | 'unknown'

/** Phân loại lỗi để giao diện hiển thị đúng trạng thái (CMN-04). */
export function getErrorKind(error: unknown): ErrorKind {
  if (!isAxiosError(error)) return 'unknown'
  if (!error.response) return 'network'
  switch (error.response.status) {
    case 400:
      return 'validation'
    case 401:
      return 'unauthorized'
    case 403:
      return 'forbidden'
    case 404:
      return 'not_found'
    default:
      return 'unknown'
  }
}

/** Lấy câu thông báo từ body lỗi của DRF: {"detail": ...}, {"field": ["..."]} hoặc ["..."]. */
function extractDetail(data: unknown): string | null {
  if (data == null) return null
  if (typeof data === 'string') return data.length < 300 && !data.startsWith('<') ? data : null
  if (Array.isArray(data)) return extractDetail(data[0])
  if (typeof data === 'object') {
    const obj = data as Record<string, unknown>
    if ('detail' in obj) return extractDetail(obj.detail)
    const first = Object.entries(obj)[0]
    if (!first) return null
    const [key, value] = first
    const message = extractDetail(value)
    return message && key !== 'non_field_errors' && !/^\d+$/.test(key) ? `${key}: ${message}` : message
  }
  return null
}

export function getErrorMessage(error: unknown): string {
  if (isAxiosError(error) && error.response) {
    const detail = extractDetail(error.response.data)
    if (detail && error.response.status !== 401) return detail
  }
  switch (getErrorKind(error)) {
    case 'network':
      return 'Không kết nối được máy chủ. Kiểm tra backend đã chạy chưa.'
    case 'unauthorized':
      return 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.'
    case 'forbidden':
      return 'Bạn không có quyền thực hiện thao tác này.'
    case 'not_found':
      return 'Không tìm thấy dữ liệu hoặc bạn không có quyền truy cập.'
    default:
      return 'Đã có lỗi xảy ra. Vui lòng thử lại.'
  }
}
