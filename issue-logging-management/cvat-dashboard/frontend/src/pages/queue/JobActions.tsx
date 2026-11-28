import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Dropdown, Modal, Popconfirm, Select, message } from 'antd'
import { ReworkDialog } from '../../components'
import { can } from '../../mock/policy'
import type { StoreValue } from '../../mock/store'
import { annotatorsOfTeam, dataTypeOfProject, isJobLocked, jobDeadline, qcCandidatesOfTeam, stepOfStage } from '../../mock/selectors'
import type { Job } from '../../mock/types'
import { JobDueModal, type JobDueTarget } from './DueModals'

interface AssignTarget { job: Job; mode: 'assign' | 'reassign' }

const AUDIT_STAGES: Job['stage'][] = ['qc2_pending', 'qc2_in_progress']

/**
 * Nút thao tác theo vai và bước cho một dòng job + modal đi kèm.
 * lead: Giao / Chuyển người / Đổi hạn · QC1 (lead hoặc isQc là qc1Id): Check · pm/admin: Đổi hạn, Audit · annotator: Nộp, Mở trên CVAT.
 */
export function useJobActions(s: StoreValue): { render: (job: Job) => ReactNode; holder: ReactNode } {
  const navigate = useNavigate()
  const [msg, ctx] = message.useMessage()
  const [assign, setAssign] = useState<AssignTarget | null>(null)
  const [anno, setAnno] = useState<string | undefined>()
  const [qc1, setQc1] = useState<string | undefined>()
  const [due, setDue] = useState<JobDueTarget | null>(null)
  const [ret, setRet] = useState<Job | null>(null)
  const me = s.currentUser

  const run = (fn: () => void, ok: string): boolean => {
    try { fn(); msg.success(ok); return true } catch (e) { msg.error(e instanceof Error ? e.message : 'Không thực hiện được'); return false }
  }
  const openAssign = (job: Job, mode: AssignTarget['mode']) => {
    setAssign({ job, mode }); setAnno(job.annotatorId ?? undefined); setQc1(job.qc1Id ?? undefined)
  }
  const openDue = (job: Job) => {
    const d = jobDeadline(s, job)
    const step = d?.step ?? stepOfStage(job.stage)
    if (!step) return
    setDue({ jobId: job.id, step, current: d?.dueAt ?? null, hasOverride: !!job.due?.[step] })
  }

  // Quyền giao job (assign): lead của team, PM của team hoặc admin (R8). Hỏi policy với người được chọn hiện tại/đại diện.
  const assignGranted = (job: Job): boolean => {
    if (job.teamId === null) return false
    const ann = job.annotatorId ?? annotatorsOfTeam(s, job.teamId)[0]?.id ?? ''
    const qc = job.qc1Id ?? qcCandidatesOfTeam(s, job.teamId)[0]?.id ?? ''
    if (!ann || !qc) return false
    return can(s, me, { kind: 'assignJob', jobId: job.id, annotatorId: ann, qc1Id: qc }).ok
  }
  // Quyền chuyển người (reassign): hỏi policy cho TỪNG trường được đổi ở stage đó
  // (đổi annotator ở anno_in_progress; đổi QC1 ở anno_in_progress|qc1_*).
  const canReassignField = (job: Job, field: 'anno' | 'qc1'): boolean => {
    if (field === 'anno') {
      if (job.annotatorId === null) return false
      return can(s, me, { kind: 'reassignJob', jobId: job.id, annotatorId: job.annotatorId, qc1Id: undefined }).ok
    }
    if (job.qc1Id === null) return false
    return can(s, me, { kind: 'reassignJob', jobId: job.id, annotatorId: undefined, qc1Id: job.qc1Id }).ok
  }
  const changeAnno = (job: Job): boolean => canReassignField(job, 'anno')
  const changeQc1 = (job: Job): boolean => canReassignField(job, 'qc1')
  const reassignGranted = (job: Job): boolean => (job.annotatorId !== null || job.qc1Id !== null) && (changeAnno(job) || changeQc1(job))

  const render = (job: Job): ReactNode => {
    const locked = isJobLocked(s, job.id)
    const items: ReactNode[] = []
    if (assignGranted(job) && job.stage === 'team_pool') {
      items.push(<Button key="assign" size="small" type="primary" shape="round" onClick={() => openAssign(job, 'assign')}>Giao</Button>)
    }
    if (reassignGranted(job)) {
      items.push(<Button key="re" size="small" shape="round" onClick={() => openAssign(job, 'reassign')}>Chuyển người</Button>)
    }
    if (can(s, me, { kind: 'jobDue', jobId: job.id }).ok && job.stage !== 'delivered' && stepOfStage(job.stage)) {
      items.push(<Button key="due" size="small" shape="round" onClick={() => openDue(job)}>Đổi hạn</Button>)
    }
    if (can(s, me, { kind: 'workJob', jobId: job.id, op: 'qc1Pass' }).ok) {
      items.push(
        <Dropdown
          key="qc1" trigger={['click']} disabled={locked}
          menu={{
            items: [{ key: 'pass', label: 'Đạt' }, { key: 'return', label: 'Trả về', danger: true }],
            onClick: ({ key }) => (key === 'pass' ? run(() => s.qc1Pass(job.id), `Job #${job.cvatJobId} đạt QC1`) : setRet(job)),
          }}
        >
          <Button size="small" type="primary" shape="round" disabled={locked}>Kiểm tra</Button>
        </Dropdown>,
      )
    }
    if (can(s, me, { kind: 'qc2', jobId: job.id }).ok && AUDIT_STAGES.includes(job.stage)) {
      items.push(<Button key="audit" size="small" shape="round" onClick={() => navigate('/audits')}>Audit</Button>)
    }
    if (can(s, me, { kind: 'workJob', jobId: job.id, op: 'submit' }).ok) {
      if (job.stage === 'anno_in_progress') {
        items.push(
          <Popconfirm key="submit" title={`Nộp job #${job.cvatJobId} sang QC1?`} okText="Nộp" cancelText="Huỷ" disabled={locked}
            onConfirm={() => run(() => s.submitJob(job.id), `Đã nộp job #${job.cvatJobId}`)}>
            <Button size="small" type="primary" shape="round" disabled={locked}>Nộp</Button>
          </Popconfirm>,
        )
      }
      items.push(<Button key="cvat" size="small" shape="round" onClick={() => msg.info(`Mở job #${job.cvatJobId} trên CVAT (giả lập)`)}>Mở trên CVAT</Button>)
    }
    return items.length > 0 ? <div className="aq-actions">{items}</div> : <span className="cvd-muted">—</span>
  }

  const team = assign?.job.teamId ?? ''
  const changed = !!assign && (anno !== (assign.job.annotatorId ?? undefined) || qc1 !== (assign.job.qc1Id ?? undefined))
  const saveAssign = () => {
    if (!assign || !anno || !qc1) return
    const { job, mode } = assign
    const ok = mode === 'assign'
      ? run(() => s.assignJob(job.id, anno, qc1), `Đã giao job #${job.cvatJobId}`)
      : run(() => s.reassignJob(job.id, {
        ...(anno !== job.annotatorId ? { annotatorId: anno } : {}),
        ...(qc1 !== job.qc1Id ? { qc1Id: qc1 } : {}),
      }), `Đã chuyển job #${job.cvatJobId}`)
    if (ok) setAssign(null)
  }

  const holder = (
    <>
      {ctx}
      <Modal
        className="cvd-modal" open={!!assign} destroyOnClose onCancel={() => setAssign(null)} cancelText="Huỷ"
        title={assign ? `${assign.mode === 'assign' ? 'Giao' : 'Chuyển người'} job #${assign.job.cvatJobId}` : ''}
        okText={assign?.mode === 'assign' ? 'Giao' : 'Chuyển'} okButtonProps={{
          disabled: !anno || !qc1 || anno === qc1 || (assign?.mode === 'reassign' && !changed),
          title: anno === qc1 ? 'QC1 không được là người gán nhãn' : undefined,
        }}
        onOk={saveAssign}
      >
        <div className="aq-form">
          {(assign?.mode === 'assign' || (assign && changeAnno(assign.job))) && (
            <div>
              <div className="aq-hint">Annotator</div>
              <Select style={{ width: '100%' }} placeholder="Chọn annotator" showSearch optionFilterProp="label" value={anno} onChange={setAnno}
                options={annotatorsOfTeam(s, team).map((u) => ({ value: u.id, label: u.name }))} />
            </div>
          )}
          {(assign?.mode === 'assign' || (assign && changeQc1(assign.job))) && (
            <div>
              <div className="aq-hint">QC1</div>
              <Select style={{ width: '100%' }} placeholder="Chọn QC1" showSearch optionFilterProp="label" value={qc1} onChange={setQc1}
                options={qcCandidatesOfTeam(s, team).map((u) => ({ value: u.id, label: `${u.name}${u.role === 'lead' ? ' (lead)' : ''}` }))} />
            </div>
          )}
        </div>
      </Modal>
      <JobDueModal
        target={due} onCancel={() => setDue(null)}
        onSave={(t, iso) => { if (run(() => s.setJobDue(t.jobId, t.step, iso), iso ? 'Đã lưu hạn riêng' : 'Đã bỏ hạn riêng')) setDue(null) }}
      />
      <ReworkDialog
        open={!!ret}
        title={ret ? `Trả về annotator — job #${ret.cvatJobId}` : undefined}
        errorCategories={ret ? dataTypeOfProject(s, ret.projectId)?.errorCategories ?? [] : []}
        onCancel={() => setRet(null)}
        onSubmit={({ reason, errorCategory }) => {
          if (ret && run(() => s.qc1Return(ret.id, reason, errorCategory), `Đã trả job #${ret.cvatJobId} về annotator`)) setRet(null)
        }}
      />
    </>
  )

  return { render, holder }
}
