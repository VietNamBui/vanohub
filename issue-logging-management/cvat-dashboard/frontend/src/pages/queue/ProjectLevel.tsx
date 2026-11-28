import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Select, Tooltip, message } from 'antd'
import dayjs from 'dayjs'
import { StatCard, Tag, Who, fmt, type Tone } from '../../design'
import type { StoreValue } from '../../mock/store'
import { batchForecast, overdueJobs, projectTeamIds, userById, visibleBatches, visibleProjects } from '../../mock/selectors'
import type { BatchForecast } from '../../mock/deadline'
import type { Project, ProjectStatus } from '../../mock/types'
import { stopRow } from '../../components'
import { DueCell, ListCard, ListControls, ProgressCell, QUEUE_ROOT, RowList, datasetsInScope, jobInScope, type ListRow, type RowTone } from './queueShared'
import { can } from '../../mock/policy'

const STATUS_VIEW: Record<ProjectStatus, { tone: Tone; label: string }> = {
  running: { tone: 'green', label: 'Đang chạy' }, paused: { tone: 'orange', label: 'Tạm dừng' }, done: { tone: 'gray', label: 'Hoàn tất' },
}
type Verdict = BatchForecast['verdict']
const RANK: Record<Verdict, number> = { late: 4, at_risk: 3, on_track: 2, no_due: 1, done: 0 }

interface Row {
  id: string; name: string; meta: Project; kind: string; kpi: number
  jobs: number; done: number; scenes: number; frames: number; cuboids: number
  pms: string[]; teams: number
  late: number; atRisk: number; datasets: number; batches: number; verdict: Verdict
}

function buildRows(s: StoreValue): Row[] {
  const inScope = jobInScope(s.currentUser)
  const myBatches = visibleBatches(s, s.currentUser)
  return visibleProjects(s, s.currentUser).map((p) => {
    const meta = p
    const dt = s.dataTypes.find((d) => d.id === p.dataTypeId)
    const jobs = s.jobs.filter((j) => j.projectId === p.id && inScope(j))
    const batches = myBatches.filter((b) => b.projectId === p.id && b.status !== 'released')
    const dss = datasetsInScope(s, p.id)
    const forecasts = batches.map((b) => batchForecast(s, b.id))
    const worst = forecasts.reduce<Verdict>((w, f) => (RANK[f.verdict] > RANK[w] ? f.verdict : w), 'done')
    return {
      id: p.id, name: p.name, meta, kind: dt?.name ?? '—', kpi: dt?.kpiPerDay ?? 0,
      jobs: jobs.length, done: jobs.filter((j) => j.stage === 'ready_to_deliver' || j.stage === 'delivered').length,
      scenes: dss.reduce((n, d) => n + d.sceneCount, 0), frames: dss.reduce((n, d) => n + d.frameCount, 0), cuboids: jobs.reduce((n, j) => n + j.prelabelCuboids, 0),
      pms: p.pmIds.map((id) => userById(s, id)?.name ?? id), teams: projectTeamIds(s, p.id).length,
      late: overdueJobs(s, { projectId: p.id }).filter(inScope).length,
      atRisk: forecasts.filter((f) => f.verdict === 'at_risk' || f.verdict === 'late').length,
      datasets: dss.length, batches: batches.length, verdict: worst,
    }
  })
}

/** Dự báo mức dự án = batch xấu nhất; hạn dự án đã qua mà vẫn còn job ⇒ trễ. */
function RiskTag({ row, now }: { row: Row; now: string }) {
  const overdue = row.done < row.jobs && new Date(row.meta.dueAt).getTime() < new Date(now).getTime()
  const v: Verdict = overdue ? 'late' : row.verdict
  const view: Record<Verdict, { tone: Tone; text: string }> = {
    late: { tone: 'pink', text: 'Trễ' }, at_risk: { tone: 'orange', text: 'Có nguy cơ trễ' }, on_track: { tone: 'green', text: 'Kịp hạn' },
    done: { tone: 'green', text: 'Đã xong' }, no_due: { tone: 'gray', text: 'Chưa có dự báo' },
  }
  return (
    <Tooltip title={`Theo batch có dự báo xấu nhất · ${row.atRisk} batch nguy cơ/trễ`}>
      <span><Tag tone={view[v].tone}>{view[v].text}</Tag></span>
    </Tooltip>
  )
}

type Sort = 'due' | 'progress'

export default function ProjectLevel({ s }: { s: StoreValue }) {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('all')
  const [sort, setSort] = useState<Sort>('due')
  const rows = useMemo(() => buildRows(s), [s])
  const pmOptions = useMemo(() => s.users.filter((u) => u.role === 'pm').map((u) => ({ value: u.id, label: u.name })), [s.users])
  const assign = (r: Row, pmIds: string[]) => {
    if (pmIds.length === 0) { message.warning('Dự án cần ít nhất một PM phụ trách'); return }
    try { s.assignProject(r.id, pmIds) } catch (e) { message.error((e as Error).message); return }
    message.success(`Đã giao ${r.name} cho ${pmIds.map((id) => pmOptions.find((o) => o.value === id)?.label ?? id).join(', ')}`)
  }

  const q = search.trim().toLowerCase()
  const shown = rows
    .filter((r) => (status === 'all' || r.meta.status === status) && (!q || r.name.toLowerCase().includes(q) || r.meta.code.toLowerCase().includes(q) || r.meta.partner.name.toLowerCase().includes(q)))
    .sort((a, b) => (sort === 'due'
      ? a.meta.dueAt.localeCompare(b.meta.dueAt)
      : (b.done / Math.max(1, b.jobs)) - (a.done / Math.max(1, a.jobs))))

  const running = rows.filter((r) => r.meta.status === 'running').length
  const nearest = rows.filter((r) => r.meta.status !== 'done').map((r) => r.meta.dueAt).sort()[0] ?? null
  const nearestDays = nearest ? Math.ceil((new Date(nearest).getTime() - new Date(s.now).getTime()) / 86_400_000) : null

  const clear = () => { setSearch(''); setStatus('all') }
  const toneOf = (r: Row): RowTone => {
    if (r.meta.status === 'done') return 'idle'
    const overdue = r.done < r.jobs && new Date(r.meta.dueAt).getTime() < new Date(s.now).getTime()
    const v: Verdict = overdue ? 'late' : r.verdict
    return v === 'late' ? 'bad' : v === 'at_risk' ? 'warn' : v === 'on_track' ? 'ok' : 'idle'
  }
  const listRows: ListRow[] = shown.map((r) => ({
    key: r.id, tone: toneOf(r), label: `Mở dự án ${r.name}`, onOpen: () => navigate(`${QUEUE_ROOT}/${r.id}`),
    cells: [
      <div className="aq-name" key="n">
        <span className="aq-title">
          <b>{r.name}</b>
          {r.meta.status !== 'running' && <Tag tone={STATUS_VIEW[r.meta.status].tone}>{STATUS_VIEW[r.meta.status].label}</Tag>}
        </span>
        <Tooltip title={<><div>{r.meta.partner.contact} · {r.meta.partner.email}</div><div>{r.meta.partner.contractNote}</div><div>{r.kind} · KPI {fmt(r.kpi)}/ngày · {fmt(r.frames)} frame</div></>}>
          <span className="cvd-muted aq-partner">{r.meta.partner.name}</span>
        </Tooltip>
      </div>,
      <div className="aq-name" key="d">
        <span className="cvd-muted">Giao {dayjs(r.meta.assignedAt).format('DD/MM/YYYY')}</span>
        <DueCell dueAt={r.meta.dueAt} now={s.now} />
        <RiskTag row={r} now={s.now} />
      </div>,
      <ProgressCell key="p" done={r.done} total={r.jobs} tone="green" />,
      r.late > 0 ? <Tag key="w" tone="pink">{r.late} job trễ</Tag> : <span key="w" className="cvd-muted">—</span>,
      can(s, s.currentUser, { kind: 'assignProject', projectId: r.id, pmIds: r.meta.pmIds }).ok ? (
        // chặn nổi bọt để chọn PM không mở dự án
        <span key="m" className="aq-pm aq-pm-edit" onClick={stopRow} onKeyDown={(e) => e.stopPropagation()}>
          <Select
            mode="multiple" className="aq-pm-select" value={r.meta.pmIds} options={pmOptions} onChange={(v: string[]) => assign(r, v)}
            optionFilterProp="label" placeholder="Chọn PM" aria-label={`PM phụ trách ${r.name}`} popupMatchSelectWidth={false}
          />
        </span>
      ) : (
        <span key="m" className="aq-pm">
          {r.pms.length ? <Who name={r.pms[0]} /> : <span className="cvd-muted">—</span>}
          {r.pms.length > 1 && <Tooltip title={r.pms.slice(1).join(', ')}><span><Tag tone="gray">+{r.pms.length - 1}</Tag></span></Tooltip>}
        </span>
      ),
    ],
  }))

  return (
    <>
      <div className="cvd-grid cvd-row-stats">
        <StatCard label="Dự án đang chạy" value={fmt(running)} suffix={`/ ${fmt(rows.length)}`} />
        <StatCard label="Job trễ" value={fmt(rows.reduce((n, r) => n + r.late, 0))} suffix="job" />
        <StatCard label="Batch có nguy cơ" value={fmt(rows.reduce((n, r) => n + r.atRisk, 0))} suffix="batch" />
        <StatCard label="Hạn gần nhất" value={nearest ? dayjs(nearest).format('DD/MM') : '—'} foot={nearestDays === null ? undefined : `Còn ${nearestDays} ngày`} />
      </div>
      <div className="cvd-row-full">
        <ListCard title="Dự án">
          <ListControls<Sort>
            search={search} onSearch={setSearch} placeholder="Tìm dự án, mã, đối tác…"
            status={status} onStatus={setStatus}
            statusOptions={[{ value: 'all', label: 'Mọi trạng thái' }, ...(Object.keys(STATUS_VIEW) as ProjectStatus[]).map((k) => ({ value: k, label: STATUS_VIEW[k].label }))]}
            sort={sort} onSort={setSort} sortOptions={[{ value: 'due', label: 'Sắp theo hạn gần nhất' }, { value: 'progress', label: 'Sắp theo tiến độ' }]}
          />
          <RowList heads={['Dự án', 'Ngày giao · Hạn', 'Tiến độ', 'Cảnh báo', 'PM phụ trách']} cols="minmax(0,2.1fr) minmax(0,1.5fr) minmax(0,1.3fr) minmax(0,0.9fr) minmax(0,1.6fr)" rows={listRows} emptyText="Không có dự án khớp bộ lọc." onClear={clear} resetKey={`${search}|${status}|${sort}`} />
        </ListCard>
      </div>
    </>
  )
}
