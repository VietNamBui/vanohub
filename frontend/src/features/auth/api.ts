import { apiClient } from '../../shared/api/client'
import type { CurrentUser, ProfileUpdateInput, TokenPair } from './types'

export async function obtainTokens(username: string, password: string): Promise<TokenPair> {
  const { data } = await apiClient.post<TokenPair>('/auth/token/', { username, password })
  return data
}

export async function fetchCurrentUser(): Promise<CurrentUser> {
  const { data } = await apiClient.get<CurrentUser>('/auth/me/')
  return data
}

export async function updateCurrentUser(payload: ProfileUpdateInput): Promise<CurrentUser> {
  const { data } = await apiClient.patch<CurrentUser>('/auth/me/', payload)
  return data
}

export async function changePassword(payload: { current_password: string; new_password: string }): Promise<{ detail: string }> {
  const { data } = await apiClient.post<{ detail: string }>('/auth/change-password/', payload)
  return data
}
