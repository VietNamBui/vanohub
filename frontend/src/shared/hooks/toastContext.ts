import { createContext, useContext } from 'react'

export type ToastKind = 'success' | 'error' | 'warning' | 'info'

export interface ToastApi {
  success: (text: string, durationSec?: number) => void
  error: (text: string, durationSec?: number) => void
  warning: (text: string, durationSec?: number) => void
  info: (text: string, durationSec?: number) => void
}

const NOOP_TOAST: ToastApi = {
  success: () => {},
  error: () => {},
  warning: () => {},
  info: () => {},
}

export const ToastContext = createContext<ToastApi>(NOOP_TOAST)

export function useToast(): ToastApi {
  return useContext(ToastContext)
}
