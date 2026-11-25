import { createContext } from 'react'
import type { CurrentUser } from './types'

/** checking: đang kiểm tra token đã lưu khi mở trang. */
export type AuthStatus = 'checking' | 'authenticated' | 'anonymous'

export interface AuthContextValue {
  status: AuthStatus
  user: CurrentUser | null
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  refreshUser: () => Promise<CurrentUser | null>
  setUser: (user: CurrentUser | null) => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)
