import type { DashboardState } from './types'
import { batchForecast, deadlineStatus, jobDeadline, stepOfStage, visibleBatches, visibleJobs } from './selectors'
export interface Notification { id: string; type: 'return' | 'deadline' | 'distribution' | 'qc1' | 'risk' | 'drift'; title: string; at: string; link: string }
export function notificationsFor(s: DashboardState, userId: string): Notification[] {
  const user = s.users.find(u => u.id === userId)
  if (!user) return []
  const out: Notification[] = []
  const now = new Date(s.now).getTime()
  const recent = (at: string) => { const age = now - new Date(at).getTime(); return age >= 0 && age <= 7 * 86400000 }
  // QC assignment is independently actionable even for users whose role is annotator.
  const visibleIds = new Set(visibleJobs(s, user).map(j => j.id))
  const jobs = s.jobs.filter(j => visibleIds.has(j.id) || j.qc1Id === userId || j.qc2Id === userId)
  for (const j of jobs) {
    const link = `/jobs/${j.id}`
    const events = s.events.filter(e => e.jobId === j.id && e.at <= s.now).sort((a,b) => b.at.localeCompare(a.at) || b.id.localeCompare(a.id))
    const latest = events[0]?.at ?? s.now
    const returned = events.find(e => ['qc1_return', 'qc2_return_qc1', 'qc2_return_anno'].includes(e.type) && e.reworkAgainst?.includes(userId))
    if (returned && recent(returned.at)) out.push({ id: `return:${returned.id}`, type: 'return', title: `Job #${j.cvatJobId} bị trả về`, at: returned.at, link })
    const step = stepOfStage(j.stage)
    const owner = step === 'annotate' ? j.annotatorId : step === 'qc1' ? j.qc1Id : step === 'qc2' ? j.qc2Id : null
    const status = deadlineStatus(s, j)
    if (owner === userId && (status === 'overdue' || status === 'due_soon')) {
      const due = jobDeadline(s, j)!
      out.push({ id: `deadline:${j.id}:${step}:${due.dueAt}:${status}`, type: 'deadline', title: `Job #${j.cvatJobId} ${status === 'overdue' ? 'đã trễ hạn' : 'sắp đến hạn'}`, at: latest, link })
    }
    if (j.qc1Id === userId && j.stage === 'qc1_pending') out.push({ id: `qc1:${j.id}:${events.find(e => e.toStage === 'qc1_pending')?.id ?? 'initial'}`, type: 'qc1', title: `Job #${j.cvatJobId} chờ QC1`, at: latest, link })
    if ((user.role === 'pm' || user.role === 'admin') && j.cvatDrift) out.push({ id: `drift:${j.id}`, type: 'drift', title: `Job #${j.cvatJobId} lệch CVAT`, at: latest, link })
  }
  for (const b of visibleBatches(s, user)) {
    const link = `/queue/${b.projectId}/${b.datasetId}/${b.id}`
    if (user.role === 'lead') {
      const event = s.batchEvents.filter(e => e.batchId === b.id && e.type === 'distribute' && recent(e.at)).sort((a,b) => b.at.localeCompare(a.at))[0]
      if (event && b.teamId !== null && user.teamIds.includes(b.teamId)) out.push({ id: `distribution:${event.id}`, type: 'distribution', title: `${b.name} mới chia cho team`, at: event.at, link })
    }
    if (user.role === 'pm' || user.role === 'admin') {
      const forecast = batchForecast(s, b.id)
      if (forecast.verdict === 'late' || forecast.verdict === 'at_risk') out.push({ id: `risk:${b.id}:${b.dueAt}:${forecast.verdict}`, type: 'risk', title: `${b.name} có nguy cơ trễ`, at: s.batchEvents.filter(e => e.batchId === b.id && e.at <= s.now).sort((a,b) => b.at.localeCompare(a.at))[0]?.at ?? s.now, link })
    }
  }
  return out.sort((a,b) => b.at.localeCompare(a.at) || a.id.localeCompare(b.id))
}
