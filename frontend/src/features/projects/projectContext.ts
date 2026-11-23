import { createContext, useContext } from 'react'
import type { Capability } from '../../shared/types/capabilities'
import type { ProjectDetail } from './types'

export interface ProjectContextValue {
  project: ProjectDetail
  projectId: number
  /** Có capability trong dự án không — chỉ để ẩn/hiện UI; backend luôn tự kiểm tra lại. */
  can: (capability: Capability) => boolean
  reload: () => void
}

export const ProjectContext = createContext<ProjectContextValue | null>(null)

export function useProject() {
  const value = useContext(ProjectContext)
  if (!value) throw new Error('useProject phải được dùng bên trong ProjectLayout')
  return value
}
