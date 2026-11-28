import { createContext } from 'react'
import type { CurrentUser } from './types'

/** checking: đang kiểm tra token đã lưu khi mở trang. */
export type AuthStatus = 'checking' | 'authenticated' | 'anonymous'

export interface AuthContextValue {
  status: AuthStatus
  user: CurrentUser | null
  /** true sau khi đăng xuất chủ động để tránh chuyển hướng ngược về URL của tài khoản cũ. */
  signedOut: boolean
  /** Username gần nhất trước khi phiên hết hạn (tránh trả về URL của tài khoản khác). */
  lastUsername: string | null
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  refreshUser: () => Promise<CurrentUser | null>
  setUser: (user: CurrentUser | null) => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)
