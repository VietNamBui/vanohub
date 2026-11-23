import { Navigate } from 'react-router'
import { useAuth } from '../auth/useAuth'
import StateView from '../../shared/components/StateView'
import { useRequest } from '../../shared/hooks/useRequest'
import { listProjects } from './api'
import { getLastProjectId } from './lastProject'

/**
 * Trang "/" sau khi đăng nhập.
 * - PM (ở bất kỳ dự án nào): vào trang chọn dự án.
 * - Vai trò khác: vào thẳng dự án mở gần nhất (nếu vẫn còn quyền), không thì dự án đầu tiên.
 * Trong dự án, ProjectIndexRedirect chọn trang theo quyền (PM → Tổng quan dự án).
 * Chưa có dự án nào → về danh sách dự án để thấy thông báo.
 */
export default function HomeRedirect() {
  const { user } = useAuth()
  const isPm = user?.role_assignments.some((a) => a.role === 'project_manager') ?? false
  if (isPm) return <Navigate to="/projects" replace />
  return <OpenLastProject />
}

function OpenLastProject() {
  const { data: projects, error, isLoading } = useRequest('projects', listProjects)

  if (isLoading) return <StateView kind="loading" />
  if (error != null || !projects?.length) return <Navigate to="/projects" replace />
  const last = getLastProjectId()
  const target = projects.find((p) => p.id === last) ?? projects[0]
  return <Navigate to={`/projects/${target.id}`} replace />
}
