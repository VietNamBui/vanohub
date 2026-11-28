import { createSeedState } from './seed'
import type { DashboardState } from './types'

/** R10: trạng thái demo lưu trong trình duyệt. Đổi schema ⇒ tăng version + đổi key để bản cũ tự về seed. */
export const STORAGE_KEY = 'cvat-dashboard-state-v2'
export const SCHEMA_VERSION = 2

type KeyValueStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

/** localStorage nếu dùng được (môi trường test/node hoặc trình duyệt chặn ⇒ null). */
export function browserStorage(): KeyValueStorage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    return null
  }
}

/** Đọc state đã lưu; thiếu / JSON hỏng / khác `schemaVersion` ⇒ seed mới. */
export function loadState(storage: KeyValueStorage | null = browserStorage()): DashboardState {
  try {
    const raw = storage?.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<DashboardState> | null
      if (parsed && parsed.schemaVersion === SCHEMA_VERSION && Array.isArray(parsed.users) && typeof parsed.currentUserId === 'string' && parsed.users.some(u => u?.id === parsed.currentUserId) && ['teams', 'dataTypes', 'projects', 'jobs', 'events', 'kpiDaily', 'datasets', 'batches', 'batchEvents', 'audits'].every(key => Array.isArray(parsed[key as keyof DashboardState])) && typeof parsed.now === 'string' && !!parsed.favorites && typeof parsed.favorites === 'object') {
        if (['jobs', 'batches', 'users'].every(key => (parsed[key as 'jobs'] ?? []).every(item => item && typeof item.id === 'string'))) return parsed as DashboardState
      }
    }
  } catch {
    // dữ liệu hỏng ⇒ về seed
  }
  return createSeedState()
}

/** Ghi state; lỗi (hết quota, bị chặn) bị bỏ qua — demo vẫn chạy trong bộ nhớ. */
export function saveState(state: DashboardState, storage: KeyValueStorage | null = browserStorage()): void {
  try {
    storage?.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch {
    // bỏ qua
  }
}

export function clearState(storage: KeyValueStorage | null = browserStorage()): void {
  try {
    storage?.removeItem(STORAGE_KEY)
  } catch {
    // bỏ qua
  }
}
