import { Link, Navigate, useParams } from 'react-router-dom'
import type { ReactNode } from 'react'
import dayjs from 'dayjs'
import { Card } from '../../design'
import { ForecastBadge } from '../../components'
import { useStore, type StoreValue } from '../../mock/store'
import { BATCH_STATUS_LABEL, batchById, batchForecast, batchStats, datasetById, projectById, userById, visibleBatches, visibleProjects } from '../../mock/selectors'
import type { Batch, Dataset, Project } from '../../mock/types'
import { DueCell, QUEUE_ROOT, datasetsInScope, type Crumb } from './queueShared'
import ProjectLevel from './ProjectLevel'
import DatasetLevel from './DatasetLevel'
import BatchLevel from './BatchLevel'
import JobLevel from './JobLevel'
import AssignedJobsLevel from './AssignedJobsLevel'
import { levelAllowed, queueEntry } from './queueScope'
import './queue.scss'

function NotFound({ what }: { what: string }) {
  return (
    <Card>
      <div className="cvd-empty">Không tìm thấy {what}. <Link to={QUEUE_ROOT}>Về Hàng đợi</Link></div>
    </Card>
  )
}

/** Dòng phụ + chip hạn/dự báo của đầu trang theo cấp. */
function headInfo(s: StoreValue, level: number, project?: Project, dataset?: Dataset, batch?: Batch): { sub: string | null; chips: ReactNode } {
  if (level === 1 && project) {
    const kind = s.dataTypes.find((d) => d.id === project.dataTypeId)?.name ?? '—'
    const pm = userById(s, project.pmIds[0])?.name ?? 'Chưa có PM'
    return { sub: `${project.partner.name} · ${kind} · PM ${pm}`, chips: <span className="aq-chip"><DueCell dueAt={project.dueAt} now={s.now} /></span> }
  }
  if (level === 2 && dataset) {
    const nas = dataset.nasPath.split('/').filter(Boolean).slice(-2).join('/')
    return { sub: `Nhận ${dayjs(dataset.receivedAt).format('DD/MM/YYYY')} · …/${nas}`, chips: <span className="aq-chip"><DueCell dueAt={dataset.dueAt} now={s.now} /></span> }
  }
  if (level === 3 && batch) {
    const team = batchStats(s, batch.id).picNames.annotate.join(', ') || 'Chưa chia team'
    return {
      sub: `${team} · CVAT task #${batch.cvatTaskId} · ${BATCH_STATUS_LABEL[batch.status]}`,
      chips: <span className="aq-chip"><DueCell dueAt={batch.dueAt} now={s.now} /><ForecastBadge forecast={batchForecast(s, batch.id)} /></span>,
    }
  }
  return { sub: null, chips: null }
}

/** Hàng đợi bấm sâu: Dự án › Dataset › Batch › Job; cấp hiện tại suy ra từ params URL, phạm vi theo vai trò (Q-I1). */
export default function QueuePage() {
  const s = useStore()
  const { projectId, datasetId, batchId } = useParams()
  const me = s.currentUser

  const project = projectId ? projectById(s, projectId) : undefined
  const dataset = datasetId ? datasetById(s, datasetId) : undefined
  const batch = batchId ? batchById(s, batchId) : undefined

  const level = batchId ? 3 : datasetId ? 2 : projectId ? 1 : 0
  // Plan 06: chặn cấp trên cấp gốc của vai (lead: chỉ /queue và cấp Job; annotator: chỉ /queue) ⇒ về /queue.
  if (!levelAllowed(me.role, level)) return <Navigate to={QUEUE_ROOT} replace />
  const lead = me.role === 'lead'

  const crumbs: Crumb[] = [{ label: 'Hàng đợi', to: QUEUE_ROOT }]
  if (projectId && !lead) crumbs.push({ label: project?.name ?? projectId, to: `${QUEUE_ROOT}/${projectId}` })
  if (datasetId && !lead) crumbs.push({ label: dataset?.name ?? datasetId, to: `${QUEUE_ROOT}/${projectId}/${datasetId}` })
  if (batchId) crumbs.push({ label: batch?.name ?? batchId, to: `${QUEUE_ROOT}/${projectId}/${datasetId}/${batchId}` })

  const titles = ['Hàng đợi', project?.name, dataset?.name, batch?.name]

  // Q-I1: mọi cấp phải nằm trong phạm vi của người xem, nếu không ⇒ "Không tìm thấy".
  const inScope = (!projectId || (!!project && visibleProjects(s, me).some((p) => p.id === project.id)))
    && (!datasetId || (!!dataset && dataset.projectId === projectId && datasetsInScope(s, projectId!).some((d) => d.id === dataset.id)))
    && (!batchId || (!!batch && batch.datasetId === datasetId && batch.projectId === projectId && visibleBatches(s, me).some((b) => b.id === batch.id)))

  const back = level > 0 ? { to: crumbs[crumbs.length - 2].to ?? QUEUE_ROOT, label: crumbs[crumbs.length - 2].label } : undefined

  let body
  if (!inScope) body = <NotFound what={batchId && !batch ? 'batch' : datasetId && !dataset ? 'dataset' : projectId && !project ? 'dự án' : 'mục thuộc đường dẫn này'} />
  else if (level === 0) {
    const entry = queueEntry(me.role)
    body = entry === 'batches' ? <BatchLevel s={s} /> : entry === 'jobs' ? <AssignedJobsLevel s={s} /> : <ProjectLevel s={s} />
  }
  else if (level === 1) body = <DatasetLevel s={s} projectId={projectId!} back={back!} />
  else if (level === 2) body = <BatchLevel s={s} projectId={projectId!} datasetId={datasetId!} back={back!} />
  else body = <JobLevel s={s} batchId={batchId!} back={back!} />

  const head = inScope ? headInfo(s, level, project, dataset, batch) : { sub: null, chips: null }

  return (
    <div className="aq-page">
      <header className="aq-head">
        <div className="aq-head-main">
          <div className="aq-head-text">
            <div className="aq-h1row">
              <h1>{titles[level] ?? 'Hàng đợi'}</h1>
            </div>
            {head.sub && <p className="aq-sub">{head.sub}</p>}
          </div>
        </div>
        <div className="aq-head-side">{head.chips}</div>
      </header>
      {body}
    </div>
  )
}
