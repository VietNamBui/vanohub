import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { setSessionExpiredHandler } from '../../shared/api/client'
import { tokenStorage } from '../../shared/api/tokenStorage'
import { fetchCurrentUser, obtainTokens } from './api'
import { AuthContext, type AuthStatus } from './authContext'
import type { CurrentUser } from './types'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null)
  // Có token đã lưu → cần hỏi backend xem token còn dùng được không.
  const [status, setStatus] = useState<AuthStatus>(() =>
    tokenStorage.getAccess() ? 'checking' : 'anonymous',
  )

  useEffect(() => {
    // Khi refresh token cũng hết hạn, axios client gọi hàm này.
    setSessionExpiredHandler(() => {
      setUser(null)
      setStatus('anonymous')
    })
  }, [])

  useEffect(() => {
    if (!tokenStorage.getAccess()) return
    fetchCurrentUser().then(
      (me) => {
        setUser(me)
        setStatus('authenticated')
      },
      () => {
        tokenStorage.clear()
        setStatus('anonymous')
      },
    )
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const tokens = await obtainTokens(username, password)
    tokenStorage.save(tokens.access, tokens.refresh)
    const me = await fetchCurrentUser()
    setUser(me)
    setStatus('authenticated')
  }, [])

  const logout = useCallback(() => {
    tokenStorage.clear()
    setUser(null)
    setStatus('anonymous')
  }, [])

  const value = useMemo(() => ({ status, user, login, logout }), [status, user, login, logout])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
