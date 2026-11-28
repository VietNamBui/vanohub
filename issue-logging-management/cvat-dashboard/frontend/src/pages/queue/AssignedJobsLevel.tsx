import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Tooltip } from 'antd'
import { DashTable, StatCard, Tag, Who, fmt } from '../../design'
import { DeadlineTag, StageTag } from '../../components'
import type { StoreValue } from '../../mock/store'
import { batchById, deadlineStatus, hoursLeft, jobDeadline, projectById, userById, userStats } from '../../mock/selectors'
import { isBatchLocked } from '../../mock/logic'
import type { Job } from '../../mock/types'
import { ListCard, ListControls, ProgressCell, pagination } from './queueShared'
import { assignedJobs, nextJob } from './queueScope'
import { useJobActions } from './JobActions'

interface Row { job: Job; dueAt: string | null; status: ReturnType<typeof deadlineStatus>; batchName: string; projectName: string; locked: boolean }
type Sort = 'due' | 'progress'
const FAR = '9999-12-31'

/** Gốc Hàng đợi của annotator: job được giao (hoặc QC1 khi isQc) từ mọi batch; Nộp / Check / Mở trên CVAT ngay trên dòng. */
export default function AssignedJobsLevel({ s }: { s: StoreValue }) {
  const navigate = useNavigate()
  const me = s.currentUser
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('all')
  const [sort, setSort] = useState<Sort>('due')
  const actions = useJobActions(s)

  const rows: Row[] = useMemo(() => assignedJobs(s, me).map((job) => {
    const b = batchById(s, job.batchId)
    return {
      job, dueAt: jobDeadline(s, job)?.dueAt ?? null, status: deadlineStatus(s, job),
      batchName: b?.name ?? job.batchId,
      projectName: projectById(s, job.projectId)?.name ?? job.projectId,
      locked: !!b && isBatchLocked(s, b),
    }
  }), [s, me])

  const q = search.trim().toLowerCase()
  const shown = rows
    .filter((r) => (status === 'all' || (status === 'rework' ? r.job.reworkCount > 0 : status === 'late' ? r.status === 'overdue' : r.job.stage === status))
      && (!q || r.job.id.toLowerCase().includes(q) || String(r.job.cvatJobId).includes(q) || r.batchName.toLowerCase().includes(q) || r.projectName.toLowerCase().includes(q)))
    .sort((a, b) => (sort === 'progress'
      ? (b.job.editedCuboids / Math.max(1, b.job.prelabelCuboids)) - (a.job.editedCuboids / Math.max(1, a.job.prelabelCuboids))
      : (a.dueAt ?? FAR).localeCompare(b.dueAt ?? FAR)))

  const working = rows.filter((r) => r.job.stage === 'anno_in_progress')
  const st = userStats(s, me.id)
  const next = nextJob(s, me, rows.map((r) => r.job))
  // Dải cảnh báo: job annotator đang giữ bị trễ / sắp trễ (chuyển từ trang Công việc của tôi cũ).
  const mineWorking = working.filter((r) => r.job.annotatorId === me.id)
  const nLate = mineWorking.filter((r) => r.status === 'overdue').length
  const nSoon = mineWorking.filter((r) => r.status === 'due_soon').length
  const alertParts = [nLate ? `${nLate} job trễ hạn` : '', nSoon ? `${nSoon} job sắp trễ` : ''].filter(Boolean)
  const who = (id: string | null) => { const u = userById(s, id); return u ? <Who name={u.name} /> : <span className="cvd-muted">—</span> }

  const columns = [
    {
      title: 'Job', key: 'id',
      render: (_: unknown, r: Row) => <div className="aq-name"><a onClick={() => navigate(`/jobs/${r.job.id}`)}>#{r.job.cvatJobId}</a></div>,
    },
    {
      title: 'Batch · Dự án', key: 'batch',
      render: (_: unknown, r: Row) => (
        <div className="aq-name">
          <span className="aq-title"><b>{r.batchName}</b>{r.locked && <Tag tone="orange">Đã khoá</Tag>}</span>
          <span className="cvd-muted">{r.projectName}</span>
        </div>
      ),
    },
    { title: 'QC1', key: 'qc1', render: (_: unknown, r: Row) => who(r.job.qc1Id) },
    { title: 'Trạng thái', key: 'stage', render: (_: unknown, r: Row) => <StageTag stage={r.job.stage} /> },
    { title: 'Tiến độ (cuboid)', key: 'progress', width: 190, render: (_: unknown, r: Row) => <ProgressCell done={r.job.editedCuboids} total={r.job.prelabelCuboids} /> },
    {
      title: 'Hạn', key: 'due',
      render: (_: unknown, r: Row) => {
        const d = jobDeadline(s, r.job)
        return d ? <DeadlineTag status={r.status} dueAt={d.dueAt} hoursLeft={hoursLeft(s, r.job)} source={d.source} compact /> : <span className="cvd-muted">—</span>
      },
    },
    {
      title: 'Làm lại', key: 'rework',
      render: (_: unknown, r: Row) => (r.job.reworkCount > 0 ? <Tooltip title="Job từng bị trả về"><span><Tag tone="pink">{r.job.reworkCount} lần</Tag></span></Tooltip> : <span className="cvd-muted">0</span>),
    },
    { title: 'Thao tác', key: 'actions', render: (_: unknown, r: Row) => actions.render(r.job) },
  ]

  return (
    <>
      {actions.holder}
      {alertParts.length > 0 && (
        <div role="alert" className={`aq-alert${nLate ? ' bad' : ''}`}>
          <span>{`Bạn có ${alertParts.join(', ')}`}</span>
          <Button shape="round" onClick={() => setStatus('late')} disabled={nLate === 0}>Xem job trễ</Button>
        </div>
      )}
      <div className="cvd-grid cvd-row-stats">
        <StatCard label="Job đang làm" value={fmt(working.length)} suffix="job" foot={`Tổng ${fmt(rows.length)} job được giao`} />
        <StatCard label="Bị trả về" value={fmt(working.filter((r) => r.job.reworkCount > 0).length)} suffix="job" />
        <StatCard label="Sắp trễ / trễ" value={fmt(working.filter((r) => r.status === 'due_soon' || r.status === 'overdue').length)} suffix="job" />
        <StatCard label="KPI hôm nay" value={fmt(st.kpiToday)} suffix={`/ ${fmt(st.kpiTarget)} cuboid`} progress={{ value: st.kpiToday, max: Math.max(1, st.kpiTarget), tone: 'blue' }} />
      </div>
      <div className="cvd-row-full">
        <ListCard
          title="Job được giao"
          extra={(
            <Button type="primary" shape="round" disabled={!next} onClick={() => next && navigate(`/jobs/${next.id}`)}>
              Bắt đầu job tiếp theo
            </Button>
          )}
        >
          <ListControls<Sort>
            search={search} onSearch={setSearch} placeholder="Tìm Job ID, CVAT job, batch, dự án…"
            status={status} onStatus={setStatus}
            statusOptions={[
              { value: 'all', label: 'Mọi trạng thái' }, { value: 'anno_in_progress', label: 'Đang làm' }, { value: 'late', label: 'Chỉ job trễ' }, { value: 'rework', label: 'Chỉ job làm lại' },
            ]}
            sort={sort} onSort={setSort} sortOptions={[{ value: 'due', label: 'Sắp theo hạn' }, { value: 'progress', label: 'Sắp theo tiến độ' }]}
          />
          <DashTable<Row> className="aq-jobtable" sticky={{ offsetHeader: 48 }} rowKey={(r) => r.job.id} columns={columns} dataSource={shown} pagination={pagination} locale={{ emptyText: 'Không có job khớp bộ lọc.' }} />
        </ListCard>
      </div>
    </>
  )
}
