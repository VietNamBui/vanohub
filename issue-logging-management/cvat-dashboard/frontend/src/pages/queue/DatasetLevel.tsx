import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Tooltip } from 'antd'
import dayjs from 'dayjs'
import { StatCard, fmt } from '../../design'
import type { StoreValue } from '../../mock/store'
import type { Dataset } from '../../mock/types'
import { DueCell, ListCard, ListControls, PctBar, ProgressCell, QUEUE_ROOT, RowList, batchesInScope, datasetsInScope, dueTone, scopedJobsOfBatch, type BackLink, type ListRow } from './queueShared'

interface Row {
  ds: Dataset; meta: Dataset
  pending: number; active: number; ready: number; delivered: number
  jobs: number; done: number
}

type Sort = 'due' | 'progress'
const FAR = '9999-12-31'

export default function DatasetLevel({ s, projectId, back }: { s: StoreValue; projectId: string; back: BackLink }) {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('all')
  const [sort, setSort] = useState<Sort>('due')

  const rows: Row[] = useMemo(() => datasetsInScope(s, projectId).map((ds) => {
    const bs = batchesInScope(s, ds.id)
    const jobs = bs.flatMap((b) => scopedJobsOfBatch(s, b.id))
    const n = (st: string[]) => bs.filter((b) => st.includes(b.status)).length
    return {
      ds, meta: ds, pending: n(['pending']), active: n(['in_progress', 'in_audit']),
      ready: bs.filter((b) => b.status === 'ready').length, delivered: bs.filter((b) => b.status === 'delivered').length,
      jobs: jobs.length, done: jobs.filter((j) => j.stage === 'ready_to_deliver' || j.stage === 'delivered').length,
    }
  }), [s, projectId])

  const q = search.trim().toLowerCase()
  const shown = rows
    .filter((r) => (status === 'all' || (status === 'unsplit' ? r.pending > 0 : status === 'active' ? r.active > 0 : r.pending + r.active === 0))
      && (!q || r.ds.name.toLowerCase().includes(q) || r.ds.nasPath.toLowerCase().includes(q)))
    .sort((a, b) => (sort === 'due'
      ? (a.meta.dueAt ?? FAR).localeCompare(b.meta.dueAt ?? FAR)
      : (b.done / Math.max(1, b.jobs)) - (a.done / Math.max(1, a.jobs))))

  const dues = rows.map((r) => r.meta.dueAt).filter((d): d is string => !!d).sort()
  const avgPre = rows.length ? Math.round(rows.reduce((n, r) => n + r.meta.preprocessedPct, 0) / rows.length) : 0

  const clear = () => { setSearch(''); setStatus('all') }
  const listRows: ListRow[] = shown.map((r) => ({
    key: r.ds.id, tone: dueTone(r.meta.dueAt, s.now, r.jobs > 0 && r.done === r.jobs), label: `Mở dataset ${r.ds.name}`,
    onOpen: () => navigate(`${QUEUE_ROOT}/${projectId}/${r.ds.id}`),
    cells: [
      <Tooltip key="n" title={<><div>{r.ds.nasPath}</div><div>{fmt(r.ds.fileCount)} file · {fmt(r.ds.frameCount)} frame · {fmt(r.meta.sceneCount)} scene</div><div>{r.meta.partnerNote}</div></>}>
        <div className="aq-name">
          <span className="aq-title"><b>{r.ds.name}</b></span>
          <span className="cvd-muted">Nhận {dayjs(r.ds.receivedAt).format('DD/MM/YYYY')}</span>
        </div>
      </Tooltip>,
      <DueCell key="d" dueAt={r.meta.dueAt} now={s.now} />,
      <Tooltip key="c" title={`Tiền xử lý ${r.meta.preprocessedPct}% · lên CVAT ${r.meta.onCvatPct}%`}>
        <div><PctBar value={r.meta.onCvatPct} tone="green" /></div>
      </Tooltip>,
      <span key="b" className="aq-num">{r.active} / {r.pending + r.active + r.ready + r.delivered}</span>,
      <ProgressCell key="p" done={r.done} total={r.jobs} tone="green" />,
    ],
  }))

  return (
    <>
      <div className="cvd-grid cvd-row-stats">
        <StatCard label="Số lô (batch)" value={fmt(rows.reduce((n, r) => n + r.pending + r.active + r.ready + r.delivered, 0))} suffix="batch" />
        <StatCard label="Tổng frame" value={fmt(rows.reduce((n, r) => n + r.ds.frameCount, 0))} suffix="frame" />
        <StatCard label="Tiền xử lý trung bình" value={`${avgPre}%`} progress={{ value: avgPre, max: 100, tone: 'blue' }} />
        <StatCard label="Hạn lô gần nhất" value={dues[0] ? dayjs(dues[0]).format('DD/MM') : '—'} foot={dues[0] ? undefined : 'Chưa đặt hạn'} />
      </div>
      <div className="cvd-row-full">
        <ListCard title="Dataset" backLabel={back.label} onBack={() => navigate(back.to)}>
          <ListControls<Sort>
            search={search} onSearch={setSearch} placeholder="Tìm dataset hoặc đường dẫn NAS…"
            status={status} onStatus={setStatus}
            statusOptions={[{ value: 'all', label: 'Mọi trạng thái' }, { value: 'unsplit', label: 'Còn batch chưa chia' }, { value: 'active', label: 'Đang xử lý' }, { value: 'finished', label: 'Không còn batch chạy' }]}
            sort={sort} onSort={setSort} sortOptions={[{ value: 'due', label: 'Sắp theo hạn lô' }, { value: 'progress', label: 'Sắp theo tiến độ' }]}
          />
          <RowList heads={['Dataset', 'Hạn lô', 'Đã lên CVAT', 'Batch đang / tổng', 'Tiến độ']} cols="minmax(0,2fr) minmax(0,1.5fr) minmax(0,1.3fr) minmax(0,1fr) minmax(0,1.4fr)" rows={listRows} emptyText="Không có dataset khớp bộ lọc." onClear={clear} resetKey={`${search}|${status}|${sort}`} />
        </ListCard>
      </div>
    </>
  )
}
