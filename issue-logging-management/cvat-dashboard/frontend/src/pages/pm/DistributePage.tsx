import { Button, InputNumber, Select, message } from 'antd'
import { useMemo, useState } from 'react'
import dayjs from 'dayjs'
import { Link } from 'react-router-dom'
import { useStore } from '../../mock/store'
import { can } from '../../mock/policy'
import { defaultStepDue, jobById, projectTeamIds, teamById, visibleProjects } from '../../mock/selectors'
import { DueEditor } from '../../components'
import type { DistributionPreviewRow, WorkStep } from '../../mock/types'
import { Badge, Card, DashTable, fmt, PageTitle, StripedBar, Tag, Who } from '../../design'
import { NoData } from './shared'

const LAYOUT_CSS = `
.cvd-grid.pm-dist { grid-template-columns: 1fr 2fr; }
.cvd-grid.pm-dist > * { min-width: 0; }
@media (max-width: 1200px) { .cvd-grid.pm-dist { grid-template-columns: 1fr; } }
`

const STEP_SHORT: Record<WorkStep, string> = { annotate: 'Gán nhãn', qc1: 'QC1', qc2: 'QC2 · Audit' }

export default function DistributePage() {
  const s = useStore()
  const [taskId, setTaskId] = useState<string | undefined>()
  const [teamId, setTeamId] = useState<string | undefined>()
  const [doneMsg, setDoneMsg] = useState<string | null>(null)
  // Hạn giao + số ngày dành cho mỗi bước kiểm tra; lưu vào batch khi xác nhận chia (setBatchDue).
  const [dueAt, setDueAt] = useState<string | null>(null)
  const [buf, setBuf] = useState({ qc1: 2, qc2: 1 })

  const projects = visibleProjects(s, s.currentUser)
  const tasks = s.batches.filter((b) => b.status === 'pending' && projects.some((p) => p.id === b.projectId))
    .map((b) => ({ ...b, projectName: projects.find((p) => p.id === b.projectId)!.name }))
  const task = tasks.find((t) => t.id === taskId)
  const project = projects.find((p) => p.id === task?.projectId)

  // R3: chỉ giao cho team thuộc dự án (R1) và làm bước gán nhãn; option bị chặn bởi `can` thì disabled + reason.
  const teamOptions = useMemo(() => {
    if (!task) return []
    return projectTeamIds(s, task.projectId)
      .map((id) => ({ id, team: teamById(s, id)! }))
      .filter(({ team }) => team && team.allowedSteps.includes('annotate'))
      .map(({ id, team }) => {
        const v = can(s, s.currentUser, { kind: 'assignBatchTeam', batchId: task.id, teamId: id })
        return { value: id, label: team.name, disabled: !v.ok, title: v.ok ? undefined : v.reason }
      })
  }, [s, task])

  const preview = useMemo<DistributionPreviewRow[]>(() => {
    if (!taskId || !teamId) return []
    // Một batch = một team (plan 09 R2): xem trước toàn bộ job chưa chia của batch đi về team đã chọn.
    const pool = s.jobs.filter((j) => j.batchId === taskId && j.stage === 'unassigned_pool')
    return [{ teamId, jobIds: pool.map((j) => j.id), jobCount: pool.length, totalCuboids: pool.reduce((n, j) => n + j.prelabelCuboids, 0) }]
  }, [s, taskId, teamId])

  const jobsInTask = task ? s.jobs.filter((j) => j.batchId === task.id && j.stage === 'unassigned_pool').length : 0
  const b = preview[0]
  const cubs = b ? [b.totalCuboids] : []
  const maxCub = cubs.length ? Math.max(...cubs) : 0

  const confirm = () => {
    if (!taskId || !teamId) return
    try {
      // Lưu hạn trước khi chia; đặt lại đúng hạn đang có là no-op (không ghi sự kiện thừa).
      if (task && (dueAt !== null || task.dueAt !== null)) s.setBatchDue(taskId, dueAt, buf)
      s.assignBatchTeam(taskId, teamId)
      const teamName = teamById(s, teamId)?.name ?? teamId
      const text = `Đã chia ${jobsInTask} job của "${task?.name}" cho team ${teamName}`
        + (dueAt ? ` · hạn giao ${dayjs(dueAt).format('DD/MM/YYYY HH:mm')}` : '')
      message.success(text)
      setDoneMsg(text)
      setTaskId(undefined)
      setTeamId(undefined)
    } catch (e) {
      message.error(e instanceof Error ? e.message : 'Không thực hiện được')
    }
  }

  return (
    <>
      <style>{LAYOUT_CSS}</style>
      <PageTitle title="Chia job" />
      {doneMsg && (
        <div className="cvd-row-full">
          <Card title="Đã chia job" extra={<Link to="/pm">Xem tổng quan</Link>}>
            <Badge tone="up">{doneMsg}</Badge>
          </Card>
        </div>
      )}
      <div className="cvd-grid pm-dist">
        <Card title="1. Chọn task và team">
          <div className="cvd-progress-row" style={{ marginTop: 4 }}>
            <div><span>Task CVAT chưa chia</span></div>
            <Select
              style={{ width: '100%' }} placeholder="Chọn task" value={taskId} allowClear
              notFoundContent="Không còn task nào chưa chia"
              onChange={(v) => {
                setTaskId(v); setTeamId(undefined)
                const b = tasks.find((t) => t.id === v)
                setDueAt(b?.dueAt ?? null); setBuf(b ? { ...b.stepBufferDays } : { qc1: 2, qc2: 1 })
              }}
              options={tasks.map((t) => ({ value: t.id, label: `${t.name} (${t.projectName})` }))}
            />
          </div>
          <div className="cvd-progress-row">
            <div><span>Team nhận cả batch</span></div>
            <Select
              style={{ width: '100%' }} placeholder="Chọn team" value={teamId} onChange={setTeamId}
              disabled={!task} options={teamOptions} optionFilterProp="label" showSearch
              notFoundContent={task ? 'Không có team nào của dự án làm bước gán nhãn' : undefined}
            />
            {project && <div className="cvd-muted" style={{ fontSize: 13, marginTop: 6 }}>Team đang tham gia dự án: {projectTeamIds(s, project.id).map((id) => teamById(s, id)?.name).join(', ')}</div>}
            {teamOptions.some((o) => o.disabled) && (
              <div className="cvd-muted" style={{ fontSize: 13, marginTop: 6 }}>
                Team bị mờ là ngoài quyền giao của bạn (chỉ sếp tổng chuyển được sang team của PM khác).
              </div>
            )}
          </div>
          {task && (
            <>
              <div className="cvd-progress-row">
                <div><span>Hạn giao đối tác</span>{!dueAt && <Tag tone="orange">Chưa đặt</Tag>}</div>
                <DueEditor value={dueAt} onChange={setDueAt} allowClear />
              </div>
              <div className="cvd-progress-row">
                <div><span>Số ngày dành cho bước kiểm tra</span></div>
                <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
                  <span>QC1 <InputNumber min={0} max={30} value={buf.qc1} onChange={(v) => setBuf((b) => ({ ...b, qc1: v ?? 0 }))} style={{ width: 72 }} /> ngày</span>
                  <span>QC2 <InputNumber min={0} max={30} value={buf.qc2} onChange={(v) => setBuf((b) => ({ ...b, qc2: v ?? 0 }))} style={{ width: 72 }} /> ngày</span>
                </div>
              </div>
              {dueAt && (
                <div className="cvd-muted" style={{ fontSize: 13, marginTop: 10, lineHeight: 1.7 }}>
                  Hạn mặc định cho job:{' '}
                  {(['annotate', 'qc1', 'qc2'] as WorkStep[]).map((st) => {
                    const d = defaultStepDue({ ...task, dueAt, stepBufferDays: buf }, st)
                    return <span key={st} style={{ marginRight: 10 }}><b>{STEP_SHORT[st]}</b> {d ? dayjs(d).format('DD/MM HH:mm') : '—'}</span>
                  })}
                  <br />Team lead có thể đặt hạn riêng cho từng job sau khi giao.
                </div>
              )}
              <div style={{ marginTop: 16, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <Tag tone="blue">{jobsInTask} job chưa chia</Tag>
              </div>
            </>
          )}
        </Card>

        <Card
          title="2. Xem trước phân bổ"
          extra={<Button type="primary" shape="round" disabled={preview.length === 0} onClick={confirm}>Xác nhận chia job</Button>}
        >
          {preview.length === 0 ? <NoData text="Chọn task và một team để xem trước" /> : (
            <>
              <DashTable<DistributionPreviewRow>
                rowKey="teamId" dataSource={preview}
                columns={[
                  { title: 'Team', render: (_, r) => <Who name={teamById(s, r.teamId)?.name ?? r.teamId} /> },
                  {
                    title: 'Tổng cuboid',
                    render: (_, r) => <div className="cvd-cell-progress"><StripedBar value={r.totalCuboids} max={maxCub} tone="blue" /><b>{fmt(r.totalCuboids)}</b></div>,
                  },
                  { title: 'Số job', dataIndex: 'jobCount', align: 'right' },
                ]}
              />
              <div className="cvd-muted" style={{ marginTop: 16 }}>
                Nguyên batch về {b ? teamById(s, b.teamId)?.name : ''} (R2: một batch = một team).
              </div>
              <div className="cvd-muted" style={{ marginTop: 4, fontSize: 13 }}>
                Job mẫu: {b ? b.jobIds.slice(0, 3).map((id) => `#${jobById(s, id)?.cvatJobId}`).join(', ') : ''}…
              </div>
            </>
          )}
        </Card>
      </div>
      {tasks.length === 0 && !doneMsg && <Card><NoData text="Tất cả task đã được chia" /></Card>}
    </>
  )
}
