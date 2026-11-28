import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { setSessionExpiredHandler } from '../../shared/api/client'
import { tokenStorage } from '../../shared/api/tokenStorage'
import { fetchCurrentUser, obtainTokens } from './api'
import { AuthContext, type AuthStatus } from './authContext'
import type { CurrentUser } from './types'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [signedOut, setSignedOut] = useState(false)
  const [lastUsername, setLastUsername] = useState<string | null>(null)
  // Có token đã lưu → cần hỏi backend xem token còn dùng được không.
  const [status, setStatus] = useState<AuthStatus>(() =>
    tokenStorage.getAccess() ? 'checking' : 'anonymous',
  )

  useEffect(() => {
    // Khi refresh token cũng hết hạn, axios client gọi hàm này.
    setSessionExpiredHandler(() => {
      setUser((prev) => {
        if (prev?.username) setLastUsername(prev.username)
        return null
      })
      setSignedOut(false)
      setStatus('anonymous')
    })
  }, [])

  useEffect(() => {
    if (!tokenStorage.getAccess()) return
    fetchCurrentUser().then(
      (me) => {
        setUser(me)
        setLastUsername(me.username)
        setSignedOut(false)
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
    setLastUsername(me.username)
    setSignedOut(false)
    setStatus('authenticated')
  }, [])

  const logout = useCallback(() => {
    tokenStorage.clear()
    setUser(null)
    setLastUsername(null)
    setSignedOut(true)
    setStatus('anonymous')
  }, [])

  const refreshUser = useCallback(async () => {
    if (!tokenStorage.getAccess()) return null
    const me = await fetchCurrentUser()
    setUser(me)
    setLastUsername(me.username)
    setStatus('authenticated')
    return me
  }, [])

  const value = useMemo(
    () => ({ status, user, signedOut, lastUsername, login, logout, refreshUser, setUser }),
    [status, user, signedOut, lastUsername, login, logout, refreshUser],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
