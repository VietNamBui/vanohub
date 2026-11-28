import { Button, Tooltip, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { DeadlineTag, ReworkDialog, type ReworkResult } from '../../components'
import { Card, DashTable, PageTitle, StatCard, TabCard, Tag, Who } from '../../design'
import { useStore } from '../../mock/store'
import {
  auditById, batchById, canAudit, dataTypeOfProject, deadlineStatus, hoursLeft, isJobLocked, jobById, stepDue, userById,
} from '../../mock/selectors'
import type { Job } from '../../mock/types'
import { auditCounts, fmtTime, LevelText, StatusTag } from './shared'
import './audits.scss'

export default function AuditDetailPage() {
  const s = useStore()
  const { auditId } = useParams()
  const [target, setTarget] = useState<Job | null>(null)
  const audit = auditById(s, auditId)

  if (!canAudit(s, s.currentUser)) {
    return (
      <>
        <PageTitle title="Chi tiết audit" />
        <div className="cvd-row-full"><Card><div className="au-denied"><h3>Không có quyền</h3></div></Card></div>
      </>
    )
  }
  if (!audit) {
    return (
      <>
        <PageTitle title="Chi tiết audit" />
        <div className="cvd-row-full"><Card><div className="cvd-empty">Không tìm thấy audit. <Link to="/audits">Về danh sách</Link></div></Card></div>
      </>
    )
  }

  const c = auditCounts(audit)
  const open = audit.status === 'open'
  const jobs = audit.sampledJobIds.map((id) => jobById(s, id)).filter((j): j is Job => !!j)
  const batchNames = audit.batchIds.map((id) => batchById(s, id)?.name ?? id)
  const dataType = dataTypeOfProject(s, audit.projectId)
  const run = (fn: () => void, ok: string) => {
    try { fn(); message.success(ok) } catch (e) { message.error((e as Error).message) }
  }

  const onReturn = (r: ReworkResult) => {
    if (!target) return
    const job = target
    setTarget(null)
    run(() => s.auditJobReturn(audit.id, job.id, r.target === 'annotator' ? 'anno' : 'qc1', r.reason, r.errorCategory), 'Đã trả job về')
  }

  const events = s.batchEvents
    .filter((e) => audit.batchIds.includes(e.batchId) && /audit/i.test(e.type) && new RegExp(`audit ${audit.id}\\b`, 'i').test(e.detail))
    .sort((a, b) => b.at.localeCompare(a.at) || b.id.localeCompare(a.id))

  const timeline = events.length === 0 ? (
    <div className="cvd-empty">Chưa có sự kiện</div>
  ) : (
    <div className="cvd-timeline">
      {events.map((e) => (
        <div key={e.id} className={`cvd-timeline-item ${e.type === 'audit_job_return' || e.type === 'audit_fail' ? 'rework' : e.type === 'audit_pass' ? 'done' : ''}`}>
          <div className="cvd-timeline-head">
            <strong>{userById(s, e.actorId)?.name ?? e.actorId}</strong>
            <span className="cvd-muted">{fmtTime(e.at)}</span>
          </div>
          <div className="cvd-timeline-body">{e.detail}</div>
        </div>
      ))}
    </div>
  )

  const columns: ColumnsType<Job> = [
    { title: 'Job', render: (_, j) => <Link to={`/jobs/${j.id}`}>#{j.cvatJobId}</Link> },
    { title: 'Batch', render: (_, j) => batchById(s, j.batchId)?.name ?? j.batchId },
    { title: 'Annotator', render: (_, j) => (j.annotatorId ? <Who name={userById(s, j.annotatorId)?.name ?? '—'} /> : '—') },
    { title: 'QC1', render: (_, j) => (j.qc1Id ? <Who name={userById(s, j.qc1Id)?.name ?? '—'} /> : '—') },
    { title: 'Cuboid', align: 'right', render: (_, j) => j.editedCuboids },
    {
      title: 'Hạn QC2',
      render: (_, j) => {
        const d = stepDue(s, j, 'qc2')
        if (!d) return <span className="cvd-muted">—</span>
        return <DeadlineTag status={deadlineStatus(s, j)} dueAt={d.dueAt} hoursLeft={hoursLeft(s, j)} source={d.source} compact />
      },
    },
    { title: 'Làm lại', align: 'right', render: (_, j) => (j.reworkCount ? <Tag tone="pink">{j.reworkCount}</Tag> : <span className="cvd-muted">0</span>) },
    {
      title: 'Kết quả',
      render: (_, j) => {
        const r = audit.results[j.id]
        return r === 'passed' ? <Tag tone="green">Đạt</Tag> : r === 'returned' ? <Tag tone="pink">Đã trả về</Tag> : <Tag tone="gray">Chờ chấm</Tag>
      },
    },
    {
      title: 'Thao tác', align: 'right',
      render: (_, j) => {
        if (audit.results[j.id] || !open) return null
        const locked = isJobLocked(s, j.id)
        const btns = (
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
            <Button size="small" type="primary" disabled={locked} onClick={() => run(() => s.auditJobPass(audit.id, j.id), 'Job đạt')}>Đạt</Button>
            <Button size="small" danger disabled={locked} onClick={() => setTarget(j)}>Trả về</Button>
          </div>
        )
        return locked ? <Tooltip title="Batch đã bị khoá">{btns}</Tooltip> : btns
      },
    },
  ]

  return (
    <>
      <PageTitle
        title={`Audit ${audit.id}`}
        controls={
          <Tooltip title={c.pending > 0 ? 'Còn job mẫu chưa chấm' : ''}>
            <span>
              <Button type="primary" shape="round" disabled={!open || c.pending > 0} onClick={() => run(() => s.closeAudit(audit.id), 'Đã kết luận audit')}>
                Kết luận audit
              </Button>
            </span>
          </Tooltip>
        }
      />
      <div className="cvd-row-full">
        <Card>
          <div className="au-meta">
            <StatusTag status={audit.status} />
            <span>Tỷ lệ <LevelText audit={audit} /></span>
            <span className="cvd-muted">Tạo {fmtTime(audit.createdAt)} bởi {userById(s, audit.createdBy)?.name ?? audit.createdBy}</span>
            <span>Batch: {batchNames.join(', ')}</span>
            <Link to="/audits">← Danh sách</Link>
          </div>
        </Card>
      </div>
      <div className="cvd-grid cvd-row-stats">
        <StatCard label="Job mẫu" value={c.total} />
        <StatCard label="Đã đạt" value={c.passed} progress={{ value: c.passed, max: Math.max(1, c.total), tone: 'green' }} />
        <StatCard label="Đã trả về" value={c.returned} progress={{ value: c.returned, max: Math.max(1, c.total), tone: 'pink' }} />
        <StatCard label="Còn lại" value={c.pending} />
      </div>
      {audit.status !== 'open' && (
        <div className="cvd-row-full">
          <div className={`au-banner ${audit.status === 'passed' ? 'ok' : 'bad'}`}>
            {audit.status === 'passed'
              ? `Audit đạt: ${c.passed} job mẫu đạt, các job chờ QC2 của batch chuyển Sẵn sàng giao`
              : 'Audit trượt: batch quay lại chờ audit sau khi sửa'}
          </div>
        </div>
      )}
      <TabCard
        title="Chi tiết audit"
        tabs={[
          {
            key: 'jobs', label: `Job mẫu (${jobs.length})`,
            content: <DashTable<Job> className="cvd-rowlist-table" sticky rowKey="id" columns={columns} dataSource={jobs} locale={{ emptyText: 'Không có job mẫu' }} pagination={{ pageSize: 10, hideOnSinglePage: true, showSizeChanger: false }} />,
          },
          { key: 'timeline', label: `Dòng thời gian (${events.length})`, content: timeline },
        ]}
      />
      <ReworkDialog
        open={!!target} onCancel={() => setTarget(null)} onSubmit={onReturn}
        errorCategories={dataType?.errorCategories ?? []} showReturnTarget title="Trả job audit về"
      />
    </>
  )
}
