import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Tooltip, message } from 'antd'
import dayjs from 'dayjs'
import { DashTable, Segmented, StatCard, Tag, Who, fmt } from '../../design'
import { DeadlineTag, StageTag } from '../../components'
import type { StoreValue } from '../../mock/store'
import { deadlineStatus, eventsOfJob, hoursLeft, jobDeadline, userById, workingHours } from '../../mock/selectors'
import type { Job, JobStage } from '../../mock/types'
import { ListCard, ListControls, ProgressCell, pagination, scopedJobsOfBatch, type BackLink } from './queueShared'
import { useJobActions } from './JobActions'
import { nextJob } from './queueScope'

interface Row {
  job: Job; hours: number; lastAt: string | null; reason: string | null
  dueAt: string | null; late: boolean
}

const STEP_OF: Record<JobStage, 'annotate' | 'qc1' | 'qc2' | 'done'> = {
  unassigned_pool: 'annotate', team_pool: 'annotate', anno_in_progress: 'annotate',
  qc1_pending: 'qc1', qc1_in_progress: 'qc1', qc2_pending: 'qc2', qc2_in_progress: 'qc2',
  ready_to_deliver: 'done', delivered: 'done',
}
type Sort = 'due' | 'progress' | 'updated'
/** Bộ lọc nhanh cấp Job. */
type Quick = 'all' | 'pool' | 'qc1' | 'late'
const QUICK: Record<Quick, (r: Row) => boolean> = {
  all: () => true,
  pool: (r) => r.job.stage === 'team_pool',
  qc1: (r) => r.job.stage === 'qc1_pending' || r.job.stage === 'qc1_in_progress',
  late: (r) => r.late,
}
const FAR = '9999-12-31'

export default function JobLevel({ s, batchId, back }: { s: StoreValue; batchId: string; back: BackLink }) {
  const navigate = useNavigate()
  const [msg, ctx] = message.useMessage()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('all')
  const [sort, setSort] = useState<Sort>('due')
  const [quick, setQuick] = useState<Quick>('all')
  const actions = useJobActions(s)
  const isLead = s.currentUser.role === 'lead'

  const rows: Row[] = useMemo(() => scopedJobsOfBatch(s, batchId).map((job) => {
    const ev = eventsOfJob(s, job.id)
    const ret = [...ev].reverse().find((e) => e.reworkAgainst && e.reworkAgainst.length > 0)
    const d = jobDeadline(s, job)
    return {
      job, hours: workingHours(ev.map((e) => new Date(e.at).getTime())), lastAt: ev[ev.length - 1]?.at ?? null,
      reason: ret ? `${ret.errorCategory ?? 'Lỗi'}: ${ret.reason ?? '—'}` : null,
      dueAt: d?.dueAt ?? null, late: deadlineStatus(s, job) === 'overdue',
    }
  }), [s, batchId])

  const q = search.trim().toLowerCase()
  const shown = rows
    .filter((r) => QUICK[quick](r) && (status === 'all' || (status === 'late' ? r.late : status === 'rework' ? r.job.reworkCount > 0 : STEP_OF[r.job.stage] === status))
      && (!q || r.job.id.toLowerCase().includes(q) || String(r.job.cvatJobId).includes(q)))
    .sort((a, b) => {
      if (sort === 'updated') return (b.lastAt ?? '').localeCompare(a.lastAt ?? '')
      if (sort === 'progress') return (b.job.editedCuboids / Math.max(1, b.job.prelabelCuboids)) - (a.job.editedCuboids / Math.max(1, a.job.prelabelCuboids))
      return (a.dueAt ?? FAR).localeCompare(b.dueAt ?? FAR)
    })

  const count = (step: string) => rows.filter((r) => STEP_OF[r.job.stage] === step).length
  const edited = rows.reduce((n, r) => n + r.job.editedCuboids, 0)
  const prelabel = rows.reduce((n, r) => n + r.job.prelabelCuboids, 0)

  const next = isLead ? nextJob(s, s.currentUser, rows.map((r) => r.job)) : undefined
  const quickOptions = (['all', 'pool', 'qc1', 'late'] as Quick[]).map((k) => ({
    value: k, label: `${{ all: 'Tất cả', pool: 'Chờ giao', qc1: 'Chờ QC1', late: 'Trễ' }[k]} (${rows.filter(QUICK[k]).length})`,
  }))

  const who = (id: string | null) => {
    const u = userById(s, id)
    return u ? <Who name={u.name} /> : <span className="cvd-muted">—</span>
  }

  // Chỉ giữ cột quan trọng; QC2, frame, thời gian làm, cập nhật cuối vào tooltip của Job; lệch CVAT thành ⚠ cạnh ID.
  const columns = [
    {
      title: 'Job', key: 'id',
      render: (_: unknown, r: Row) => (
        <Tooltip title={<><div>QC2: {r.job.qc2Id ? (s.users.find((u) => u.id === r.job.qc2Id)?.name ?? r.job.qc2Id) : '—'}</div><div>{fmt(r.job.frames)} frame · làm {(Math.round(r.hours * 10) / 10).toLocaleString('vi-VN')} giờ</div><div>Cập nhật {r.lastAt ? dayjs(r.lastAt).format('DD/MM HH:mm') : '—'}</div>{r.job.cvatDrift && <div>⚠ Lệch CVAT: {r.job.cvatDrift}</div>}</>}>
          <div className="aq-name">
            <span><a onClick={() => navigate(`/jobs/${r.job.id}`)}>#{r.job.cvatJobId}</a>{r.job.cvatDrift && <span className="aq-drift"> ⚠</span>}</span>
            <a className="cvd-muted" onClick={() => msg.info(`Mở job #${r.job.cvatJobId} trên CVAT (giả lập)`)}>Mở trên CVAT</a>
          </div>
        </Tooltip>
      ),
    },
    { title: 'Annotator', key: 'anno', render: (_: unknown, r: Row) => who(r.job.annotatorId) },
    { title: 'QC1', key: 'qc1', render: (_: unknown, r: Row) => who(r.job.qc1Id) },
    { title: 'Trạng thái', key: 'stage', render: (_: unknown, r: Row) => <StageTag stage={r.job.stage} /> },
    {
      title: 'Tiến độ (cuboid)', key: 'progress', width: 190,
      render: (_: unknown, r: Row) => <ProgressCell done={r.job.editedCuboids} total={r.job.prelabelCuboids} />,
    },
    {
      title: 'Hạn', key: 'due',
      render: (_: unknown, r: Row) => {
        const d = jobDeadline(s, r.job)
        return d ? <DeadlineTag status={deadlineStatus(s, r.job)} dueAt={d.dueAt} hoursLeft={hoursLeft(s, r.job)} source={d.source} compact /> : <span className="cvd-muted">—</span>
      },
    },
    {
      title: 'Làm lại', key: 'rework',
      render: (_: unknown, r: Row) => (r.job.reworkCount > 0
        ? <Tooltip title={r.reason ?? 'Chưa có lý do ghi nhận'}><span><Tag tone="pink">{r.job.reworkCount} lần</Tag></span></Tooltip>
        : <span className="cvd-muted">0</span>),
    },
    { title: 'Thao tác', key: 'actions', render: (_: unknown, r: Row) => actions.render(r.job) },
  ]

  return (
    <>
      {ctx}
      {actions.holder}
      <div className="cvd-grid cvd-row-stats">
        <StatCard label="Job theo bước" value={fmt(rows.length)} suffix="job" foot={`Gán nhãn ${count('annotate')} · QC1 ${count('qc1')} · QC2 ${count('qc2')} · Xong ${count('done')}`} />
        <StatCard label="Job trễ" value={fmt(rows.filter((r) => r.late).length)} suffix="job" />
        <StatCard label="Làm lại" value={fmt(rows.filter((r) => r.job.reworkCount > 0).length)} suffix="job" />
        <StatCard label="Cuboid đã sửa" value={fmt(edited)} suffix={`/ ${fmt(prelabel)} prelabel`} progress={{ value: edited, max: prelabel, tone: 'blue' }} />
      </div>
      <div className="cvd-row-full">
        <ListCard
          title="Job" backLabel={back.label} onBack={() => navigate(back.to)}
          extra={isLead && (
            <Button type="primary" shape="round" disabled={!next} onClick={() => next && navigate(`/jobs/${next.id}`)}>
              Bắt đầu job tiếp theo
            </Button>
          )}
        >
          <div className="aq-toolbar"><Segmented<Quick> options={quickOptions} value={quick} onChange={setQuick} /></div>
          <ListControls<Sort>
            search={search} onSearch={setSearch} placeholder="Tìm Job ID hoặc CVAT job…"
            status={status} onStatus={setStatus}
            statusOptions={[
              { value: 'all', label: 'Mọi trạng thái' }, { value: 'annotate', label: 'Đang ở Gán nhãn' }, { value: 'qc1', label: 'Đang ở QC1' },
              { value: 'qc2', label: 'Đang ở QC2' }, { value: 'done', label: 'Hoàn tất' }, { value: 'late', label: 'Chỉ job trễ' }, { value: 'rework', label: 'Chỉ job làm lại' },
            ]}
            sort={sort} onSort={setSort} sortOptions={[{ value: 'due', label: 'Sắp theo hạn' }, { value: 'progress', label: 'Sắp theo tiến độ' }, { value: 'updated', label: 'Cập nhật gần nhất' }]}
          />
          <DashTable<Row> className="aq-jobtable" sticky={{ offsetHeader: 48 }} rowKey={(r) => r.job.id} columns={columns} dataSource={shown} pagination={pagination} locale={{ emptyText: 'Không có job khớp bộ lọc.' }} />
        </ListCard>
      </div>
    </>
  )
}
