import type { ReactNode } from 'react'
import { Navigate } from 'react-router'
import StateView from '../../shared/components/StateView'
import type { Capability } from '../../shared/types/capabilities'
import { useProject } from './projectContext'

/** Chặn trang nếu thiếu capability (chỉ là lớp UI — API vẫn tự kiểm tra quyền). */
export function RequireCap({ cap, children }: { cap: Capability | Capability[]; children: ReactNode }) {
  const { can } = useProject()
  const ok = Array.isArray(cap) ? cap.some(can) : can(cap)
  if (!ok) return <StateView kind="forbidden" description="Liên hệ PM nếu bạn cần quyền truy cập." />
  return <>{children}</>
}

/** Trang mặc định khi vào dự án theo vai trò cao nhất trong dự án. */
export function ProjectIndexRedirect() {
  const { can } = useProject()
  if (can('view_dashboard')) return <Navigate to="overview" replace />
  if (can('perform_audit')) return <Navigate to="qc2/dashboard" replace />
  if (can('perform_qc1')) return <Navigate to="qc1/dashboard" replace />
  if (can('annotate_jobs')) return <Navigate to="annotator/dashboard" replace />
  return <Navigate to="guidelines" replace />
}
