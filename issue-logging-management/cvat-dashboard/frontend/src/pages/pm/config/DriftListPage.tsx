import { message } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { RowList, StageTag, stopRow, type ListRow } from '../../../components'
import { Card, PageTitle, Pill, StatCard, Tag, fmt } from '../../../design'
import { driftedJobs, projectById, teamById } from '../../../mock/selectors'
import { useStore } from '../../../mock/store'
import type { Job } from '../../../mock/types'
import './config.scss'

export default function DriftListPage() {
  const s = useStore()
  const nav = useNavigate()
  const [resolved, setResolved] = useState<Set<string>>(new Set())
  const jobs = driftedJobs(s)
  const pending = jobs.length - resolved.size

  const markResolved = (j: Job) => { setResolved(new Set(resolved).add(j.id)); message.success(`Đã đánh dấu job #${j.cvatJobId}`) }
  // Vạch màu: chưa xử lý hồng · đã xử lý xanh.
  const rows: ListRow[] = jobs.map((j) => {
    const done = resolved.has(j.id)
    return {
      key: j.id, tone: done ? 'ok' : 'bad', label: `Mở job #${j.cvatJobId}`, onOpen: () => nav(`/jobs/${j.id}`),
      cells: [
        <b>#{j.cvatJobId}</b>,
        projectById(s, j.projectId)?.name ?? '—',
        j.teamId ? <Tag tone="gray">{teamById(s, j.teamId)?.name}</Tag> : <span className="cvd-muted">—</span>,
        <StageTag stage={j.stage} />,
        <span className="cf-pink">{j.cvatDrift}</span>,
        done ? <Tag tone="green">Đã xử lý</Tag> : (
          <span className="cvd-rowlist-actions" onClick={stopRow}>
            <Pill onClick={() => markResolved(j)}>Đánh dấu đã xử lý</Pill>
            <Pill onClick={() => message.info('Mở job trên CVAT (giả lập)')}>Mở trên CVAT</Pill>
          </span>
        ),
      ],
    }
  })

  return (
    <>
      <PageTitle title="Job lệch CVAT" />
      <div className="cvd-grid cvd-row-stats">
        <StatCard label="Chưa xử lý" value={fmt(pending)} suffix={`/ ${fmt(jobs.length)}`} foot="Trạng thái dashboard không khớp CVAT" progress={{ value: pending, max: Math.max(1, jobs.length), tone: 'pink' }} />
      </div>
      <div className="cvd-row-full">
        <Card title="So sánh dashboard và CVAT">
          <RowList
            heads={['Job', 'Dự án', 'Team', 'Trên dashboard', 'Trên CVAT', 'Xử lý']}
            cols="minmax(0,0.8fr) minmax(0,1.4fr) minmax(0,1fr) minmax(0,1.2fr) minmax(0,1.2fr) minmax(0,2fr)"
            rows={rows} emptyText="Không có job lệch." emptyHint="Mọi job trên dashboard đang khớp CVAT."
          />
        </Card>
      </div>
    </>
  )
}
