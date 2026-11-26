import { createContext, useContext } from 'react'

export interface ShellContextValue {
  projectId: number | null
  openSearch: () => void
  openSupport: () => void
}

export const ShellContext = createContext<ShellContextValue>({
  projectId: null,
  openSearch: () => {},
  openSupport: () => {},
})

export function useShell() {
  return useContext(ShellContext)
}
