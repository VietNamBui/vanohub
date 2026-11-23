/** Dạng trả về của các API có phân trang (PageNumberPagination của DRF). */
export interface Paginated<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export interface UserBrief {
  id: number
  username: string
  full_name: string
}

/** Bỏ các giá trị rỗng để không gửi `?status=&batch=` lên API. */
export function cleanParams(params: Record<string, string | number | boolean | undefined | null>) {
  return Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '' && v !== false),
  )
}
