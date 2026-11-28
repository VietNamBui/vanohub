import { App, Button, Result } from 'antd'
import { useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import dayjs from 'dayjs'
import { DeadlineTag, DueEditor, JobTimeline, ReworkDialog, StageTag, type ReworkResult } from '../../components'
import { useStore } from '../../mock/store'
import { can } from '../../mock/policy'
import { batchById, dataTypeOfProject, deadlineStatus, eventsOfJob, hoursLeft, jobById, projectById, stepDue, stepOfStage, teamById, userById } from '../../mock/selectors'
import { Badge, Card, PageTitle, StatCard, Tag, fmt } from '../../design'
import type { JobEvent, WorkStep } from '../../mock/types'

type Ret = 'qc1' | 'qc2'

const STEPS: { step: WorkStep; label: string }[] = [
  { step: 'annotate', label: 'Gán nhãn' },
  { step: 'qc1', label: 'QC1' },
  { step: 'qc2', label: 'QC2 · Audit' },
]

/** Thời điểm hoàn thành bước (bảng D hợp đồng deadline). */
const completedAt = (evs: JobEvent[], step: WorkStep): string | null => {
  if (step === 'annotate') return evs.find((e) => e.type === 'submit')?.at ?? null
  const type = step === 'qc1' ? 'qc1_pass' : 'qc2_pass'
  return [...evs].reverse().find((e) => e.type === type)?.at ?? null
}

const lateText = (hours: number) => (hours < 24 ? `${Math.max(1, Math.floor(hours))} giờ` : `${Math.floor(hours / 24)} ngày`)

export default function JobDetailPage() {
  const { jobId } = useParams()
  const s = useStore()
  const { message } = App.useApp()
  const [ret, setRet] = useState<Ret | null>(null)
  const job = jobById(s, jobId)
  if (!job) return <Result status="404" title="Không tìm thấy job" extra={<Link to="/">Về trang chủ</Link>} />

  const me = s.currentUser
  const project = projectById(s, job.projectId)
  const cats = dataTypeOfProject(s, job.projectId)?.errorCategories ?? []
  const name = (id: string | null) => userById(s, id)?.name ?? '—'

  const run = (fn: () => void, ok: string) => {
    try { fn(); message.success(ok) } catch (e) { message.error((e as Error).message) }
  }

  // Quyền làm việc trên job đều hỏi policy (R8/R9): nộp/QC1 qua `workJob`, QC2 qua `qc2`, đổi hạn qua `jobDue`, giao qua `deliver`.
  const work = (op: 'submit' | 'startQc1' | 'qc1Pass' | 'qc1Return') => can(s, me, { kind: 'workJob', jobId: job.id, op }).ok
  const canQc2 = can(s, me, { kind: 'qc2', jobId: job.id }).ok
  const canDeliver = can(s, me, { kind: 'deliver', jobIds: [job.id] }).ok
  const currentStep = stepOfStage(job.stage)
  const evs = eventsOfJob(s, job.id)
  const changeDue = (step: WorkStep, iso: string | null) => run(() => s.setJobDue(job.id, step, iso), iso ? 'Đã đặt hạn riêng' : 'Đã bỏ hạn riêng')

  const onReturn = (r: ReworkResult) => {
    if (ret === 'qc1') run(() => s.qc1Return(job.id, r.reason, r.errorCategory), 'Đã trả về annotator')
    else if (r.target === 'annotator') run(() => s.qc2ReturnToAnno(job.id, r.reason, r.errorCategory), 'Đã trả thẳng annotator')
    else run(() => s.qc2ReturnToQc1(job.id, r.reason, r.errorCategory), 'Đã trả về QC1')
    setRet(null)
  }

  const buttons: ReactNode[] = []
  const st = job.stage
  if (st === 'anno_in_progress' && work('submit'))
    buttons.push(<Button key="sub" type="primary" onClick={() => run(() => s.submitJob(job.id), job.firstSubmittedAt ? 'Đã nộp lại (không cộng KPI)' : 'Đã nộp, KPI đã được cộng')}>{job.reworkCount ? 'Nộp lại' : 'Nộp'}</Button>)
  if (work('startQc1') && st === 'qc1_pending') buttons.push(<Button key="s1" onClick={() => run(() => s.startQc1(job.id), 'Bắt đầu QC1')}>Bắt đầu QC1</Button>)
  if (work('qc1Pass') && (st === 'qc1_pending' || st === 'qc1_in_progress')) {
    buttons.push(<Button key="p1" type="primary" onClick={() => run(() => s.qc1Pass(job.id), 'QC1 đạt')}>QC1 đạt</Button>)
    buttons.push(<Button key="r1" danger onClick={() => setRet('qc1')}>Trả về annotator</Button>)
  }
  if (canQc2 && st === 'qc2_pending') buttons.push(<Button key="s2" onClick={() => run(() => s.startQc2(job.id), 'Bắt đầu QC2')}>Bắt đầu QC2</Button>)
  if (canQc2 && (st === 'qc2_pending' || st === 'qc2_in_progress')) {
    buttons.push(<Button key="p2" type="primary" onClick={() => run(() => s.qc2Pass(job.id), 'QC2 đạt')}>QC2 đạt</Button>)
    buttons.push(<Button key="r2" danger onClick={() => setRet('qc2')}>Trả về...</Button>)
  }
  if (canDeliver && st === 'ready_to_deliver') buttons.push(<Button key="d" type="primary" onClick={() => run(() => s.markDelivered([job.id]), 'Đã đánh dấu đã giao')}>Đã giao</Button>)

  const info: [string, ReactNode][] = [
    ['Job ID', job.id],
    ['CVAT job', `#${job.cvatJobId}`],
    ['Batch', batchById(s, job.batchId)?.name ?? job.batchId],
    ['Dự án', project?.name ?? '—'],
    ['Team', job.teamId ? teamById(s, job.teamId)?.name ?? '—' : '—'],
    ['Trạng thái', <StageTag key="st" stage={job.stage} />],
    ['Annotator', name(job.annotatorId)],
    ['QC1', name(job.qc1Id)],
    ['QC2', name(job.qc2Id)],
  ]

  return (
    <>
      <PageTitle
        title={(
          <span style={{ display: 'inline-flex', flexWrap: 'wrap', alignItems: 'center', gap: 16 }}>
            {`Job #${job.cvatJobId}`}
            <StageTag stage={job.stage} />
            {job.reworkCount > 0 && <Badge tone="down">{`Làm lại x${job.reworkCount}`}</Badge>}
          </span>
        )}
      />

      {job.cvatDrift && (
        <Card title="Job lệch với CVAT">
          <div style={{ borderLeft: '4px solid #f0438a', paddingLeft: 16, overflowWrap: 'anywhere' }}>{job.cvatDrift}</div>
        </Card>
      )}

      <div className="cvd-grid cvd-row-stats" style={{ marginTop: job.cvatDrift ? 20 : 0 }}>
        <StatCard label="Số frame" value={fmt(job.frames)} />
        <StatCard label="Prelabel cuboid" value={fmt(job.prelabelCuboids)} />
        <StatCard
          label="Cuboid đã sửa" value={fmt(job.editedCuboids)} suffix={`/ ${fmt(job.prelabelCuboids)}`}
          progress={{ value: job.editedCuboids, max: job.prelabelCuboids, tone: 'green' }}
        />
        <StatCard label="Số lần rework" value={job.reworkCount} />
      </div>

      <div className="cvd-stack">
        <Card title="Thông tin">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '20px 24px' }}>
            {info.map(([k, v]) => (
              <div key={k} style={{ minWidth: 0 }}>
                <div className="cvd-muted" style={{ fontSize: 13, marginBottom: 4 }}>{k}</div>
                <div style={{ fontSize: 16, overflowWrap: 'anywhere' }}>{v}</div>
              </div>
            ))}
          </div>
        </Card>
        <Card title="Hạn">
          <div style={{ display: 'grid', gap: 16 }}>
            {STEPS.map(({ step, label }) => {
              const due = stepDue(s, job, step)
              const done = step !== currentStep ? completedAt(evs, step) : null
              return (
                <div key={step} style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12 }}>
                  <b style={{ width: 80 }}>{label}</b>
                  <span style={{ flex: '1 1 200px', minWidth: 0 }}>
                    {due ? dayjs(due.dueAt).format('DD/MM/YYYY HH:mm') : <span className="cvd-muted">Chưa đặt hạn</span>}
                    {due && <span className="cvd-muted">{due.source === 'job' ? ' · hạn riêng của job' : ' · theo hạn batch'}</span>}
                  </span>
                  <span style={{ flex: '1 1 220px', minWidth: 0 }}>
                    {step === currentStep && due && (
                      <DeadlineTag status={deadlineStatus(s, job)} dueAt={due.dueAt} hoursLeft={hoursLeft(s, job)} source={due.source} />
                    )}
                    {step === currentStep && !due && <Tag tone="gray">Bước hiện tại</Tag>}
                    {done && (
                      <span>
                        {`Hoàn thành lúc ${dayjs(done).format('DD/MM/YYYY HH:mm')}`}
                        {due && (dayjs(done).isAfter(due.dueAt)
                          ? <b className="cvd-danger">{` — trễ ${lateText(dayjs(done).diff(due.dueAt, 'hour', true))}`}</b>
                          : <b style={{ color: '#1a9d5a' }}> — đúng hạn</b>)}
                      </span>
                    )}
                    {!done && step !== currentStep && <span className="cvd-muted">Chưa tới bước này</span>}
                  </span>
                  {can(s, me, { kind: 'jobDue', jobId: job.id }).ok && job.stage !== 'delivered' && (
                    <span style={{ display: 'inline-flex', gap: 8, flexWrap: 'wrap' }}>
                      <DueEditor value={job.due?.[step] ?? null} onChange={(iso) => changeDue(step, iso)} allowClear />
                    </span>
                  )}
                </div>
              )
            })}
          </div>
          {!can(s, me, { kind: 'jobDue', jobId: job.id }).ok && <div className="cvd-muted" style={{ marginTop: 12 }}>Hạn do team lead, PM hoặc admin đặt.</div>}
        </Card>
        <Card title="Thao tác">
          {buttons.length
            ? <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>{buttons}</div>
            : <span className="cvd-muted">Không có thao tác nào dành cho bạn ở bước này.</span>}
        </Card>
        <Card title="Lịch sử">
          <JobTimeline events={eventsOfJob(s, job.id)} reverse />
        </Card>
      </div>

      <ReworkDialog
        open={ret !== null} onCancel={() => setRet(null)} onSubmit={onReturn} errorCategories={cats}
        showReturnTarget={ret === 'qc2'} title={ret === 'qc2' ? 'QC2 trả về' : 'Trả về annotator'}
      />
    </>
  )
}
