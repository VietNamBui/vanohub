import { Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useStore } from '../mock/store'
import { batchById, teamById, userById } from '../mock/selectors'
import type { Job } from '../mock/types'
import { StageTag } from './StageTag'
import { DashTable, Tag } from '../design'

export type JobColumnKey =
  | 'job' | 'task' | 'team' | 'annotator' | 'qc1' | 'stage' | 'prelabel' | 'edited' | 'frames' | 'rework' | 'drift'

export interface JobTableProps {
  jobs: Job[]
  /** Cột hiển thị, theo thứ tự. Mặc định: job, task, team, annotator, qc1, stage, rework. */
  columns?: JobColumnKey[]
  /** Cột cuối "Thao tác" — render prop trả nút cho từng job. */
  renderActions?: (job: Job) => ReactNode
  actionsTitle?: string
  pageSize?: number
  loading?: boolean
}

const DEFAULT_COLUMNS: JobColumnKey[] = ['job', 'task', 'team', 'annotator', 'qc1', 'stage', 'rework']

export function JobTable({ jobs, columns = DEFAULT_COLUMNS, renderActions, actionsTitle = 'Thao tác', pageSize = 10, loading }: JobTableProps) {
  const s = useStore()
  const name = (id: string | null) => userById(s, id)?.name ?? '—'
  const defs: Record<JobColumnKey, ColumnsType<Job>[number]> = {
    job: { title: 'Job', key: 'job', render: (_, j) => <Link to={`/jobs/${j.id}`}>#{j.cvatJobId}</Link> },
    task: {
      title: 'Batch', key: 'task',
      render: (_, j) => batchById(s, j.batchId)?.name ?? j.batchId,
    },
    team: { title: 'Team', key: 'team', render: (_, j) => (j.teamId ? teamById(s, j.teamId)?.name : '—') },
    annotator: { title: 'Annotator', key: 'annotator', render: (_, j) => name(j.annotatorId) },
    qc1: { title: 'QC1', key: 'qc1', render: (_, j) => name(j.qc1Id) },
    stage: { title: 'Trạng thái', key: 'stage', render: (_, j) => <StageTag stage={j.stage} /> },
    prelabel: { title: 'Prelabel', key: 'prelabel', align: 'right', sorter: (a, b) => a.prelabelCuboids - b.prelabelCuboids, render: (_, j) => j.prelabelCuboids.toLocaleString('vi-VN') },
    edited: { title: 'Đã sửa', key: 'edited', align: 'right', sorter: (a, b) => a.editedCuboids - b.editedCuboids, render: (_, j) => j.editedCuboids.toLocaleString('vi-VN') },
    frames: { title: 'Frame', key: 'frames', align: 'right', render: (_, j) => j.frames },
    rework: { title: 'Làm lại', key: 'rework', align: 'right', sorter: (a, b) => a.reworkCount - b.reworkCount, render: (_, j) => (j.reworkCount ? <Tag tone="pink">{j.reworkCount}</Tag> : 0) },
    drift: { title: 'Lệch CVAT', key: 'drift', render: (_, j) => (j.cvatDrift ? <Tooltip title={j.cvatDrift}><Tag tone="orange">Lệch</Tag></Tooltip> : '—') },
  }
  const cols: ColumnsType<Job> = columns.map((k) => defs[k])
  if (renderActions) cols.push({ title: actionsTitle, key: 'actions', render: (_, j) => renderActions(j) })
  return <DashTable<Job> rowKey="id" loading={loading} dataSource={jobs} columns={cols} pagination={{ pageSize, showSizeChanger: false }} />
}
