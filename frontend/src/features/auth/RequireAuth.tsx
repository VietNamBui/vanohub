import { Navigate, Outlet, useLocation } from 'react-router'
import StateView from '../../shared/components/StateView'
import { useAuth } from './useAuth'

/** Bọc các route cần đăng nhập. Chưa đăng nhập → chuyển về /login, nhớ trang muốn vào nếu không phải đăng xuất chủ động. */
export default function RequireAuth() {
  const { status, signedOut, lastUsername } = useAuth()
  const location = useLocation()

  if (status === 'checking') return <StateView kind="loading" />
  if (status === 'anonymous') {
    if (signedOut) {
      return <Navigate to="/login" replace />
    }
    return (
      <Navigate
        to="/login"
        replace
        state={{
          from: `${location.pathname}${location.search}`,
          ...(lastUsername ? { expectedUsername: lastUsername } : {}),
        }}
      />
    )
  }
  return <Outlet />
}
