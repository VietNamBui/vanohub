import { Navigate, Outlet, useLocation } from 'react-router'
import StateView from '../../shared/components/StateView'
import { useAuth } from './useAuth'

/** Bọc các route cần đăng nhập. Chưa đăng nhập → chuyển về /login, nhớ trang đang muốn vào. */
export default function RequireAuth() {
  const { status } = useAuth()
  const location = useLocation()

  if (status === 'checking') return <StateView kind="loading" />
  if (status === 'anonymous') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  return <Outlet />
}
