// Nhớ dự án mở gần nhất trên trình duyệt này (chỉ là tiện ích; quyền vẫn do backend kiểm tra).
const KEY = 'vanohub:lastProjectId'

export function getLastProjectId(): number | null {
  try {
    const value = Number(localStorage.getItem(KEY))
    return Number.isInteger(value) && value > 0 ? value : null
  } catch {
    return null
  }
}

export function setLastProjectId(projectId: number) {
  try {
    localStorage.setItem(KEY, String(projectId))
  } catch {
    // Trình duyệt chặn localStorage → bỏ qua, chỉ mất tính năng "nhớ dự án".
  }
}
