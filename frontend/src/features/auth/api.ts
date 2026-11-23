import { apiClient } from '../../shared/api/client'
import type { CurrentUser, TokenPair } from './types'

export async function obtainTokens(username: string, password: string): Promise<TokenPair> {
  const { data } = await apiClient.post<TokenPair>('/auth/token/', { username, password })
  return data
}

export async function fetchCurrentUser(): Promise<CurrentUser> {
  const { data } = await apiClient.get<CurrentUser>('/auth/me/')
  return data
}
