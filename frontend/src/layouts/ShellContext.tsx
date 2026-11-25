import { createContext, useContext } from 'react'

export interface ShellContextValue {
  projectId: number | null
  teamLeaderName: string | null
  setTeamLeaderName: (name: string | null) => void
  openSearch: () => void
  openSupport: () => void
}

export const ShellContext = createContext<ShellContextValue>({
  projectId: null,
  teamLeaderName: null,
  setTeamLeaderName: () => {},
  openSearch: () => {},
  openSupport: () => {},
})

export function useShell() {
  return useContext(ShellContext)
}
