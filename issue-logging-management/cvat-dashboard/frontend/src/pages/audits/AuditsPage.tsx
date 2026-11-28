import { Button, Checkbox, InputNumber, Modal, Tooltip, message } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { RowList, stopRow, type ListRow, type RowTone } from '../../components'
import { Card, fmt, PageTitle, Pill, StatCard, StripedBar, Tag, Who } from '../../design'
import { useStore } from '../../mock/store'
import { can } from '../../mock/policy'
import { auditableBatches, batchById, canAudit, datasetById, nextAuditLevel, projectById, userById, visibleProjects } from '../../mock/selectors'
import type { Audit } from '../../mock/types'
import { auditCounts, fmtTime, LevelText, StatusTag } from './shared'
import './audits.scss'

export default function AuditsPage() {
  const s = useStore()
  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  const [picked, setPicked] = useState<string[]>([])
  /** % người dùng tự nhập; null = theo mức gợi ý. */
  const [customPct, setCustomPct] = useState<number | null>(null)
  const user = s.currentUser

  if (!canAudit(s, user)) {
    return (
      <>
        <PageTitle title="QC2 · Audit" />
        <div className="cvd-row-full">
          <Card><div className="au-denied"><h3>Không có quyền</h3><p className="cvd-muted">Chỉ Admin, PM và team được phép audit mới mở được trang này.</p></div></Card>
        </div>
      </>
    )
  }

  const projects = visibleProjects(s, user)
  // R4: QC2/Audit do policy quyết — `can({kind:'audit'})` cho phép admin, PM của team giữ batch, và thành viên team canQa cùng PM.
  const isAuditOwner = (batchId: string): boolean => can(s, user, { kind: 'audit', batchIds: [batchId] }).ok
  const audits = s.audits
    .filter((a) => a.batchIds.some(isAuditOwner))
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))

  const eligible = auditableBatches(s, user).filter((b) => isAuditOwner(b.id))
  const mainProject = projects[0]
  const next = mainProject ? nextAuditLevel(s, mainProject.id) : { index: 0, percent: 100 }
  const openCount = audits.filter((a) => a.status === 'open').length
  const closed = audits.filter((a) => a.status !== 'open')
  const passRate = closed.length ? Math.round((closed.filter((a) => a.status === 'passed').length / closed.length) * 100) : 0
  const pendingJobs = s.jobs.filter((j) => j.stage === 'qc2_pending' && can(s, user, { kind: 'audit', batchIds: [j.batchId] }).ok).length

  const pendingOf = (batchId: string) => s.jobs.filter((j) => j.batchId === batchId && j.stage === 'qc2_pending').length
  const pickedBatches = eligible.filter((b) => picked.includes(b.id))
  const pickedProject = pickedBatches[0]?.projectId
  const level = pickedProject ? nextAuditLevel(s, pickedProject) : null
  const eligibleJobs = pickedBatches.reduce((n, b) => n + pendingOf(b.id), 0)
  const percent = customPct ?? level?.percent ?? 0
  const sample = level ? Math.ceil((percent / 100) * eligibleJobs) : 0

  const toggle = (id: string, on: boolean) => setPicked((p) => (on ? [...p, id] : p.filter((x) => x !== id)))

  const create = () => {
    // id audit mới do store sinh theo `au{số audit + 1}`
    const newId = `au${s.audits.length + 1}`
    try {
      s.createAudit(picked, percent)
    } catch (e) {
      message.error((e as Error).message)
      return
    }
    message.success('Đã tạo audit')
    setOpen(false)
    setPicked([])
    setCustomPct(null)
    nav(`/audits/${newId}`)
  }

  // Vạch màu: Đạt xanh · Trượt hồng · Đang mở cam.
  const toneOf = (a: Audit): RowTone => (a.status === 'passed' ? 'ok' : a.status === 'failed' ? 'bad' : 'warn')
  const rows: ListRow[] = audits.map((a) => {
    const c = auditCounts(a)
    const batches = a.batchIds.map((id) => batchById(s, id))
    const datasets = [...new Set(batches.map((b) => datasetById(s, b?.datasetId)?.name ?? b?.datasetId ?? '?'))].join(', ')
    return {
      key: a.id, tone: toneOf(a), label: `Mở audit ${a.id}`, onOpen: () => nav(`/audits/${a.id}`),
      cells: [
        <div className="au-name"><b>{a.id}</b><span className="cvd-muted">{fmtTime(a.createdAt)}</span></div>,
        <div className="au-name"><b>{batches.map((b, i) => b?.name ?? a.batchIds[i]).join(', ')}</b><span className="cvd-muted">{datasets}</span></div>,
        <LevelText audit={a} />,
        <div className="au-sample-cell">
          <div>{c.passed} đạt · {c.returned} trả về · {c.pending} chờ <span className="cvd-muted">/ {c.total}</span></div>
          <StripedBar value={c.passed} max={Math.max(1, c.total)} tone={c.returned ? 'pink' : 'green'} thin />
        </div>,
        <Who name={userById(s, a.createdBy)?.name ?? a.createdBy} />,
        <span className="cvd-rowlist-inline">
          <StatusTag status={a.status} />
          {a.status === 'passed' && (
            <Button size="small" type="primary" ghost onClick={(e) => { stopRow(e); message.info('Đã tạo giao hàng (giả lập)') }}>Tạo giao hàng</Button>
          )}
        </span>,
      ],
    }
  })

  return (
    <>
      <PageTitle title="QC2 · Audit" controls={<Pill onClick={() => setOpen(true)}>Tạo audit</Pill>} />
      <div className="cvd-grid cvd-row-stats">
        <StatCard label="Audit đang mở" value={fmt(openCount)} />
        <StatCard label="Tỷ lệ đạt" value={closed.length ? passRate : '—'} suffix={closed.length ? '%' : undefined} foot={`${closed.length} audit đã kết luận`} />
        <StatCard label="Mức lấy mẫu kế tiếp" value={<span className="cvd-big">{next.percent}%</span>}
          foot={(
            <span title="Audit đạt thì giảm mức; audit trượt thì quay lại 100%">
              {[100, 30, 10].map((l, i) => (
                <span key={l}>
                  {i > 0 && ' → '}
                  <span className={`au-level-on-wrap ${i === next.index ? 'on' : ''}`}>{l}%</span>
                </span>
              ))}
              {mainProject ? ` · ${mainProject.name}` : ''}
            </span>
          )}
        />
        <StatCard label="Job chờ audit" value={fmt(pendingJobs)} foot="Đang chờ ở QC2 · Audit" />
      </div>
      <div className="cvd-row-full">
        <Card title="Danh sách audit">
          <RowList
            heads={['Audit', 'Batch · Dataset', 'Tỷ lệ', 'Job mẫu', 'Người tạo', 'Trạng thái']}
            cols="minmax(0,1fr) minmax(0,1.5fr) 64px minmax(0,1.7fr) minmax(0,1.2fr) minmax(0,1.4fr)"
            rows={rows} emptyText="Chưa có audit." emptyHint="Bấm Tạo audit để lấy mẫu job chờ QC2 · Audit."
          />
        </Card>
      </div>
      <Modal
        className="cvd-modal" open={open} title="Tạo audit" okText="Tạo audit" cancelText="Huỷ"
        onCancel={() => { setOpen(false); setCustomPct(null) }} onOk={create} okButtonProps={{ disabled: picked.length === 0 }}
      >
        {eligible.length === 0 ? (
          <div className="cvd-empty">Không có batch nào có job chờ QC2 · Audit.</div>
        ) : (
          <div style={{ display: 'grid', gap: 8 }}>
            {eligible.map((b) => {
              const diffProject = !!pickedProject && b.projectId !== pickedProject
              return (
                <Tooltip key={b.id} title={diffProject ? 'Khác dự án với batch đã chọn' : ''}>
                  <label style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                    <Checkbox checked={picked.includes(b.id)} disabled={diffProject} onChange={(e) => toggle(b.id, e.target.checked)} />
                    <span>{b.name}</span>
                    <Tag tone="blue">{pendingOf(b.id)} job chờ</Tag>
                    <span className="cvd-muted">{projectById(s, b.projectId)?.name}</span>
                    <span className="cvd-muted">{b.dueAt ? `Hạn giao ${dayjs(b.dueAt).format('DD/MM/YYYY')}` : 'Chưa đặt hạn'}</span>
                  </label>
                </Tooltip>
              )
            })}
          </div>
        )}
        {level && (
          <div className="au-banner info" style={{ marginTop: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
              <span>Tỷ lệ audit</span>
              <InputNumber
                min={1} max={100} precision={0} value={percent} addonAfter="%" style={{ width: 120 }}
                onChange={(v) => setCustomPct(v ?? null)} aria-label="Tỷ lệ audit (%)"
              />
              {[100, 30, 10].map((p) => (
                <Pill key={p} className={p === percent ? 'au-pct-on' : undefined} onClick={() => setCustomPct(p)}>{p}%</Pill>
              ))}
              {customPct !== null && customPct !== level.percent && (
                <Button type="link" size="small" onClick={() => setCustomPct(null)}>{`Về mức gợi ý ${level.percent}%`}</Button>
              )}
            </div>
            {fmt(eligibleJobs)} job đủ điều kiện → <b>{fmt(sample)}</b> job mẫu
          </div>
        )}
      </Modal>
    </>
  )
}
