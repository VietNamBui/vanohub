import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Tooltip } from 'antd'
import dayjs from 'dayjs'
import { message } from 'antd'
import { StatCard, Tag, Who, fmt } from '../../design'
import { ForecastBadge } from '../../components'
import type { StoreValue } from '../../mock/store'
import {
  BATCH_STATUS_LABEL, batchForecast, batchStats, datasetById, nextAuditLevel, overdueJobs, projectById,
} from '../../mock/selectors'
import type { BatchForecast } from '../../mock/deadline'
import type { Batch, JobStage } from '../../mock/types'
import { DueCell, ListCard, ListControls, PriorityStars, RowList, queueBatchPath, batchesInScope, canSetPriority, jobInScope, scopedJobsOfBatch, type BackLink, type ListRow, type RowTone } from './queueShared'
import { leadBatches } from './queueScope'
import { canManageBatch, useBatchActions } from './BatchActions'

/** Màu đoạn thanh phân bổ. */
const SEGMENTS: { key: string; label: string; color: string; stages: JobStage[] }[] = [
  { key: 'anno', label: 'Gán nhãn', color: '#1d6ff2', stages: ['unassigned_pool', 'team_pool', 'anno_in_progress'] },
  { key: 'qc1', label: 'QC1', color: '#f59e0b', stages: ['qc1_pending', 'qc1_in_progress'] },
  { key: 'qc2', label: 'QC2 · Audit', color: '#a855f7', stages: ['qc2_pending', 'qc2_in_progress'] },
  { key: 'done', label: 'Giao hàng', color: '#2fae32', stages: ['ready_to_deliver', 'delivered'] },
]

interface Row {
  batch: Batch; priority: number; forecast: BatchForecast
  byStage: Record<JobStage, number>; total: number; done: number
  late: number; rework: number; locked: boolean
  teams: string[]; qc1: string | null; qc2: string | null; auditText: string
}

type Sort = 'priority' | 'due' | 'progress'

/** Có `datasetId` ⇒ cấp Batch của một dataset (admin/pm); thiếu ⇒ gốc của lead: batch của team từ mọi dự án (plan 06). */
export interface BatchLevelProps { s: StoreValue; projectId?: string; datasetId?: string; back?: BackLink }

export default function BatchLevel({ s, projectId, datasetId, back }: BatchLevelProps) {
  const root = datasetId === undefined
  const navigate = useNavigate()
  const [msg, ctx] = message.useMessage()
  /** Q-I3: ★ đi qua action của store (đúng 1 sự kiện khi đổi). */
  const onPriority = (batchId: string, v: number) => {
    try { s.setBatchPriority(batchId, v as 1 | 2 | 3 | 4 | 5) } catch (e) { msg.error(e instanceof Error ? e.message : 'Không đổi được ưu tiên') }
  }
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('all')
  const [sort, setSort] = useState<Sort>('priority')
  const batchActions = useBatchActions(s)

  const rows: Row[] = useMemo(() => (root ? leadBatches(s, s.currentUser) : batchesInScope(s, datasetId)).map((batch) => {
    const inScope = jobInScope(s.currentUser)
    const st = batchStats(s, batch.id)
    const jobs = scopedJobsOfBatch(s, batch.id)
    const byStage = Object.fromEntries(Object.keys(st.byStage).map((k) => [k, 0])) as Record<JobStage, number>
    jobs.forEach((j) => { byStage[j.stage] += 1 })
    const audits = s.audits.filter((a) => a.batchIds.includes(batch.id)).sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    const au = audits[0]
    return {
      batch, priority: batch.priority, forecast: batchForecast(s, batch.id),
      byStage, total: jobs.length, done: jobs.filter((j) => j.stage === 'ready_to_deliver' || j.stage === 'delivered').length,
      late: overdueJobs(s, { batchIds: [batch.id] }).filter(inScope).length, rework: jobs.filter((j) => j.reworkCount > 0).length, locked: st.locked,
      teams: st.picNames.annotate, qc1: st.picNames.qc1, qc2: st.picNames.qc2,
      auditText: au ? `${au.status === 'passed' ? 'Đạt' : au.status === 'failed' ? 'Trượt' : 'Đang mở'} ${au.percent}% · ${dayjs(au.createdAt).format('DD/MM')}` : 'Chưa audit',
    }
  }), [s, datasetId, root])
  // Cột menu ⋯ hiện khi có ít nhất một batch trong danh sách user quản lý được (R9).
  const anyManage = rows.some((r) => canManageBatch(s, r.batch))

  const q = search.trim().toLowerCase()
  const FAR = '9999-12-31'
  const shown = rows
    .filter((r) => (status === 'all' || r.batch.status === status)
      && (!q || r.batch.name.toLowerCase().includes(q) || r.batch.id.toLowerCase().includes(q) || String(r.batch.cvatTaskId).includes(q)
        || (root && (projectById(s, r.batch.projectId)?.name.toLowerCase().includes(q) || datasetById(s, r.batch.datasetId)?.name.toLowerCase().includes(q)))))
    .sort((a, b) => {
      const due = (a.batch.dueAt ?? FAR).localeCompare(b.batch.dueAt ?? FAR)
      if (sort === 'due') return due
      if (sort === 'progress') return (b.done / Math.max(1, b.total)) - (a.done / Math.max(1, a.total))
      return b.priority - a.priority || due
    })

  const dues = rows.map((r) => r.batch.dueAt).filter((d): d is string => !!d).sort()
  const nextLevel = root ? 0 : nextAuditLevel(s, projectId!).percent
  const atRisk = rows.filter((r) => r.forecast.verdict === 'at_risk' || r.forecast.verdict === 'late').length

  const clear = () => { setSearch(''); setStatus('all') }
  const toneOf = (r: Row): RowTone => {
    const v = r.forecast.verdict
    if (r.late > 0 || v === 'late') return 'bad'
    return v === 'at_risk' ? 'warn' : v === 'on_track' ? 'ok' : 'idle'
  }
  const listRows: ListRow[] = shown.map((r) => ({
    key: r.batch.id, tone: toneOf(r), label: `Mở batch ${r.batch.name}`,
    onOpen: () => navigate(queueBatchPath(r.batch)),
    cells: [
      <div className="aq-name" key="n">
        <span className="aq-title"><b>{r.batch.name}</b>{r.locked && <Tag tone="orange">Đã khoá</Tag>}</span>
        {root && <span className="cvd-muted">{projectById(s, r.batch.projectId)?.name ?? r.batch.projectId} · {datasetById(s, r.batch.datasetId)?.name ?? r.batch.datasetId}</span>}
        <span className="cvd-muted">{BATCH_STATUS_LABEL[r.batch.status]} · CVAT #{r.batch.cvatTaskId}</span>
      </div>,
      <PriorityStars key="s" value={r.priority} onChange={canSetPriority(s, r.batch) ? (v) => onPriority(r.batch.id, v) : undefined} />,
      <Tooltip key="t" title={<><div>QC1: {r.qc1 ?? '—'}</div><div>QC2: {r.qc2 ?? '—'}</div><div>Audit kế tiếp {nextLevel}% · gần nhất: {r.auditText}</div></>}>
        <span><Who name={r.teams.join(', ') || 'Chưa chia'} /></span>
      </Tooltip>,
      <div className="aq-name" key="d"><DueCell dueAt={r.batch.dueAt} now={s.now} /><ForecastBadge forecast={r.forecast} /></div>,
      <div className="aq-name" key="p">
        <div className="aq-dist" aria-label="Phân bổ job theo bước">
          {SEGMENTS.map((g) => {
            const v = g.stages.reduce((n, st) => n + r.byStage[st], 0)
            return v > 0 && (
              <Tooltip key={g.key} title={`${g.label}: ${fmt(v)} job`}>
                <span style={{ width: `${(v / Math.max(1, r.total)) * 100}%`, background: g.color }} />
              </Tooltip>
            )
          })}
        </div>
        <span className="cvd-muted aq-num">{fmt(r.done)}/{fmt(r.total)} job xong</span>
      </div>,
      <span key="f" className="aq-tags">
        {r.late > 0 && <Tag tone="pink">{r.late} trễ</Tag>}
        {r.rework > 0 && <Tag tone="orange">{r.rework} làm lại</Tag>}
        {r.late === 0 && r.rework === 0 && <span className="cvd-muted">—</span>}
      </span>,
      ...(canManageBatch(s, r.batch) ? [<span key="m">{batchActions.menu(r.batch)}</span>] : []),
    ],
  }))

  const legend = SEGMENTS.map((g) => <span key={g.key} className="aq-legend"><i style={{ background: g.color }} />{g.label}</span>)
  const totalLate = rows.reduce((n, r) => n + r.late, 0)

  return (
    <>
      {ctx}
      {batchActions.holder}
      <div className="cvd-grid cvd-row-stats">
        <StatCard label="Số batch" value={fmt(rows.length)} suffix="batch" />
        <StatCard label="Job trễ" value={fmt(totalLate)} suffix="job" />
        {root
          ? <StatCard label="Batch có nguy cơ" value={fmt(atRisk)} suffix="batch" foot="Dự báo trễ hoặc có nguy cơ trễ" />
          : <StatCard label="Mức audit kế tiếp" value={`${nextLevel}%`} foot="Theo lịch sử audit của dự án" />}
        <StatCard label="Hạn gần nhất" value={dues[0] ? dayjs(dues[0]).format('DD/MM') : '—'} foot={dues[0] ? undefined : 'Chưa đặt hạn'} />
      </div>
      <div className="cvd-row-full">
        <ListCard title="Batch" extra={<span className="aq-legends">{legend}</span>} backLabel={back?.label} onBack={back ? () => navigate(back.to) : undefined}>
          <ListControls<Sort>
            search={search} onSearch={setSearch} placeholder={root ? 'Tìm batch, ID, CVAT task, dự án…' : 'Tìm batch, ID, CVAT task…'}
            status={status} onStatus={setStatus}
            statusOptions={[{ value: 'all', label: 'Mọi trạng thái' }, ...(Object.keys(BATCH_STATUS_LABEL) as Batch['status'][]).map((k) => ({ value: k, label: BATCH_STATUS_LABEL[k] }))]}
            sort={sort} onSort={setSort} sortOptions={[{ value: 'priority', label: 'Ưu tiên ★ rồi hạn' }, { value: 'due', label: 'Sắp theo hạn giao' }, { value: 'progress', label: 'Sắp theo tiến độ' }]}
          />
          <RowList heads={['Batch', 'Ưu tiên', 'Team', 'Hạn giao', 'Tiến độ', 'Cảnh báo', ...(anyManage ? [''] : [])]} cols={`minmax(0,1.8fr) 108px minmax(0,1.2fr) minmax(0,1.5fr) minmax(0,1.5fr) minmax(0,1fr)${anyManage ? ' 44px' : ''}`} rows={listRows} emptyText="Không có batch khớp bộ lọc." onClear={clear} resetKey={`${search}|${status}|${sort}`} />
        </ListCard>
      </div>
    </>
  )
}
