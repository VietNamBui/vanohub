import type { DashboardState } from './types'
import { visibleBatches, visibleJobs, visibleProjects } from './selectors'

export interface SearchResult { id: string; type: 'Job' | 'Batch' | 'Dự án' | 'Dataset'; title: string; link: string }
const normalize = (v: string) => v.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/g, 'd').toLowerCase()
export function searchFor(s: DashboardState, userId: string, query: string): SearchResult[] {
  const user = s.users.find(u => u.id === userId)
  const q = normalize(query.trim())
  if (!user || !q) return []
  const match = (...values: string[]) => values.some(v => normalize(v).includes(q))
  const results: SearchResult[] = visibleJobs(s, user).filter(j => match(j.id, String(j.cvatJobId))).map(j => ({ id: j.id, type: 'Job', title: `${j.id} · CVAT ${j.cvatJobId}`, link: `/jobs/${j.id}` }))
  if (user.role === 'annotator') return results
  results.push(...visibleBatches(s, user).filter(b => match(b.id, b.name, String(b.cvatTaskId))).map(b => ({ id: b.id, type: 'Batch' as const, title: b.name, link: `/queue/${b.projectId}/${b.datasetId}/${b.id}` })))
  if (user.role === 'lead') return results
  const projects = visibleProjects(s, user)
  results.push(...projects.filter(p => match(p.id, p.name, p.code)).map(p => ({ id: p.id, type: 'Dự án' as const, title: p.name, link: `/queue/${p.id}` })))
  results.push(...s.datasets.filter(d => projects.some(p => p.id === d.projectId) && match(d.id, d.name)).map(d => ({ id: d.id, type: 'Dataset' as const, title: d.name, link: `/queue/${d.projectId}/${d.id}` })))
  return results
}
