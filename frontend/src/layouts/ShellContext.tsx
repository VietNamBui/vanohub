import { createContext, useContext } from 'react'
import type { Capability } from '../shared/types/capabilities'

export interface ProjectCapabilitiesState {
  projectId: number
  capabilities: Capability[]
}

export interface ShellContextValue {
  projectId: number | null
  projectCapabilities: ProjectCapabilitiesState | null
  setProjectCapabilities: (value: ProjectCapabilitiesState | null) => void
  openSearch: () => void
  openSupport: () => void
}

export const ShellContext = createContext<ShellContextValue>({
  projectId: null,
  projectCapabilities: null,
  setProjectCapabilities: () => {},
  openSearch: () => {},
  openSupport: () => {},
})

export function useShell() {
  return useContext(ShellContext)
}
