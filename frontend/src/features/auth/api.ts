import { apiClient } from '../../shared/api/client'
import type { CurrentUser, ProfileUpdateInput, TokenPair } from './types'

export async function obtainTokens(username: string, password: string): Promise<TokenPair> {
  const { data } = await apiClient.post<TokenPair>('/auth/token/', { username, password })
  return data
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await apiClient.post('/auth/me/password/', { current_password: currentPassword, new_password: newPassword })
}

export async function fetchCurrentUser(): Promise<CurrentUser> {
  const { data } = await apiClient.get<CurrentUser>('/auth/me/')
  return data
}

export async function updateCurrentUser(payload: ProfileUpdateInput): Promise<CurrentUser> {
  const { data } = await apiClient.patch<CurrentUser>('/auth/me/', payload)
  return data
}
