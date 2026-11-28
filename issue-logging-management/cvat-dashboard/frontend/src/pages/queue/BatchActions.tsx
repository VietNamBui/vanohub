import { useMemo, useState, type ReactNode } from 'react'
import { DatePicker, Drawer, Modal, Select, TimePicker, message } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { Tag } from '../../design'
import { ConfirmDanger, RowActionsMenu } from '../../components'
import { can } from '../../mock/policy'
import type { StoreValue } from '../../mock/store'
import { STEP_LABEL, batchHistory, jobsOfBatch, projectTeamIds, qcCandidatesOfTeam, teamById, userById } from '../../mock/selectors'
import type { Batch, BatchEventType, DashboardState, WorkStep } from '../../mock/types'
import { BatchDueModal } from './DueModals'

type TagTone = Parameters<typeof Tag>[0]['tone']
/** Nhãn sự kiện batch trong drawer lịch sử. */
export const EVENT_LABEL: Record<BatchEventType, [string, TagTone]> = {
  distribute: ['Chia job', 'blue'],
  reassign: ['Reassign', 'purple'],
  transfer: ['Chuyển team', 'purple'],
  release: ['Release', 'pink'],
  autolock_set: ['Đặt khoá', 'orange'],
  autolock_reset: ['Sửa khoá', 'orange'],
  audit_create: ['Tạo audit', 'blue'],
  audit_job_pass: ['Audit: job đạt', 'green'],
  audit_job_return: ['Audit: trả job', 'pink'],
  audit_pass: ['Audit đạt', 'green'],
  audit_fail: ['Audit trượt', 'pink'],
  due_set: ['Đặt hạn giao', 'blue'],
  due_clear: ['Bỏ hạn giao', 'gray'],
  priority_set: ['Đổi ưu tiên', 'orange'],
}

const fmtDateTime = (iso: string): string => dayjs(iso).format('DD/MM/YYYY HH:mm')

/** Bước hiện tại của batch = bước sớm nhất còn job chưa qua. */
export function currentStepOf(s: DashboardState, batchId: string): WorkStep {
  const jobs = jobsOfBatch(s, batchId)
  if (jobs.some((j) => ['unassigned_pool', 'team_pool', 'anno_in_progress'].includes(j.stage))) return 'annotate'
  if (jobs.some((j) => ['qc1_pending', 'qc1_in_progress'].includes(j.stage))) return 'qc1'
  return 'qc2'
}

/** Menu ⋯ của batch hiện khi user có quyền quản lý batch đó (R9 — `can({kind:'manageBatch'})`, phạm vi dự án đã lọc ở cấp trên). */
export const canManageBatch = (s: StoreValue, batch: Batch): boolean =>
  can(s, s.currentUser, { kind: 'manageBatch', batchId: batch.id, op: 'autoLock' }).ok
    || can(s, s.currentUser, { kind: 'manageBatch', batchId: batch.id, op: 'priority' }).ok

/**
 * Menu ⋯ của dòng batch + các modal/drawer đi kèm (Reassign, Release, hạn giao, khoá tự động, lịch sử).
 * `menu(batch)` đặt trong dòng; `holder` đặt một lần trong cây của cấp Batch.
 */
export function useBatchActions(s: StoreValue): { menu: (b: Batch) => ReactNode; holder: ReactNode } {
  const [msg, ctx] = message.useMessage()
  const [reassign, setReassign] = useState<Batch | null>(null)
  const [reStep, setReStep] = useState<WorkStep>('annotate')
  const [rePic, setRePic] = useState<string | undefined>()
  const [release, setRelease] = useState<Batch | null>(null)
  const [transfer, setTransfer] = useState<Batch | null>(null)
  const [transferTeam, setTransferTeam] = useState<string | undefined>()
  const [history, setHistory] = useState<Batch | null>(null)
  const [lock, setLock] = useState<Batch | null>(null)
  const [dueBatch, setDueBatch] = useState<Batch | null>(null)
  const [lockDate, setLockDate] = useState<Dayjs | null>(null)
  const [lockTime, setLockTime] = useState<Dayjs | null>(null)

  const run = (fn: () => void, ok: string) => {
    try { fn(); msg.success(ok) } catch (e) { msg.error(e instanceof Error ? e.message : 'Không thực hiện được') }
  }

  const openReassign = (b: Batch) => { setReassign(b); setReStep('qc1'); setRePic(undefined) }
  const openLock = (b: Batch) => {
    const d = b.autoLockAt ? dayjs(b.autoLockAt) : dayjs(s.now).add(7, 'day')
    setLock(b); setLockDate(d); setLockTime(d)
  }
  // Reassign chỉ còn bước QC1 (WP5): ứng viên = thành viên team của batch đủ điều kiện QC1, mỗi người hỏi policy `batchQc1`.
  const picOptions = (b: Batch) => {
    const team = teamById(s, b.teamId)
    if (!team) return []
    return qcCandidatesOfTeam(s, team.id).map((u) => {
      const v = can(s, s.currentUser, { kind: 'batchQc1', batchId: b.id, picId: u.id })
      return { value: u.id, label: `${u.name} (ID ${u.employeeId})`, disabled: !v.ok, title: v.ok ? undefined : v.reason }
    })
  }
  const currentPic = (b: Batch): string => {
    const id = b.stepPic.qc1
    return id ? userById(s, id)?.name ?? id : 'Chưa có'
  }

  // R3: số job đi theo sang team mới = job chưa qua QC1 (về team_pool; annotator/qc1 bị gỡ).
  const jobsNotPastQc1 = (batchId: string): number =>
    jobsOfBatch(s, batchId).filter((j) => ['unassigned_pool', 'team_pool', 'anno_in_progress', 'qc1_pending', 'qc1_in_progress'].includes(j.stage)).length

  const transferOptions = useMemo(() => {
    if (!transfer) return []
    return projectTeamIds(s, transfer.projectId)
      .map((id) => ({ id, team: teamById(s, id)! }))
      .filter(({ team }) => team && team.allowedSteps.includes('annotate') && team.id !== transfer.teamId)
      .map(({ id, team }) => {
        const v = can(s, s.currentUser, { kind: 'assignBatchTeam', batchId: transfer.id, teamId: id })
        return { value: id, label: team.name, disabled: !v.ok, title: v.ok ? undefined : v.reason }
      })
  }, [s, transfer])

  const menu = (b: Batch) => {
    const released = b.status === 'released'
    const closed = released || b.status === 'delivered'
    const mg = (op: 'release' | 'autoLock' | 'due') => can(s, s.currentUser, { kind: 'manageBatch', batchId: b.id, op }).ok
    return (
      <RowActionsMenu items={[
        'Thao tác batch',
        { key: 'transfer', label: b.status === 'pending' ? 'Giao cho team' : 'Chuyển team', disabled: closed, onClick: () => { setTransfer(b); setTransferTeam(undefined) } },
        { key: 'reassign', label: 'Reassign', disabled: released || b.status === 'pending', onClick: () => openReassign(b) },
        { key: 'release', label: 'Release', danger: true, disabled: released || b.status === 'in_audit' || b.status === 'delivered' || !mg('release'), onClick: () => setRelease(b) },
        { key: 'history', label: 'Xem lịch sử', onClick: () => setHistory(b) },
        'Hạn giao',
        { key: 'due', label: b.dueAt ? 'Sửa hạn giao' : 'Đặt hạn giao', disabled: closed || !mg('due'), onClick: () => setDueBatch(b) },
        { key: 'undue', label: 'Bỏ hạn giao', disabled: closed || !b.dueAt || !mg('due'), onClick: () => run(() => s.setBatchDue(b.id, null), 'Đã bỏ hạn giao') },
        'Khoá tự động',
        { key: 'lock', label: b.autoLockAt ? 'Sửa khoá tự động' : 'Đặt khoá tự động', disabled: released || !mg('autoLock'), onClick: () => openLock(b) },
        { key: 'unlock', label: 'Gỡ khoá tự động', disabled: released || !b.autoLockAt || !mg('autoLock'), onClick: () => run(() => s.setAutoLock(b.id, null), 'Đã gỡ khoá tự động') },
      ]}
      />
    )
  }

  const hist = history ? batchHistory(s, history.id) : []

  const holder = (
    <>
      {ctx}
      <Modal
        className="cvd-modal" open={!!reassign} title={`Reassign ${reassign?.name ?? ''}`} okText="Đổi người phụ trách" cancelText="Huỷ" destroyOnClose
        okButtonProps={{ disabled: !rePic }} onCancel={() => setReassign(null)}
        onOk={() => {
          if (!reassign || !rePic) return
          run(() => { s.reassignBatch(reassign.id, reStep, rePic); setReassign(null) }, 'Đã đổi người phụ trách')
        }}
      >
        {reassign && (
          <div className="aq-form">
            <div>Bước hiện tại: <Tag tone="blue">{STEP_LABEL[currentStepOf(s, reassign.id)]}</Tag></div>
            <div className="aq-hint">Chỉ đổi người phụ trách QC1 (reassignBatch còn bước qc1).</div>
            <div className="aq-hint">Hiện tại: {currentPic(reassign)}</div>
            <div>
              <div className="aq-hint">QC1 mới</div>
              <Select
                showSearch optionFilterProp="label" style={{ width: '100%' }} placeholder="Chọn" value={rePic} onChange={setRePic}
                options={picOptions(reassign)}
              />
            </div>
          </div>
        )}
      </Modal>

      <Modal
        className="cvd-modal" open={!!transfer}
        title={transfer?.status === 'pending' ? `Giao ${transfer?.name ?? ''} cho team` : `Chuyển team: ${transfer?.name ?? ''}`}
        okText={transfer?.status === 'pending' ? 'Giao cho team' : 'Chuyển'}
        cancelText="Huỷ" destroyOnClose
        okButtonProps={{ disabled: !transferTeam }} onCancel={() => setTransfer(null)}
        onOk={() => {
          if (transfer && transferTeam) {
            const isPending = transfer.status === 'pending'
            run(() => { s.assignBatchTeam(transfer.id, transferTeam); setTransfer(null) },
              isPending
                ? `Đã giao ${transfer.name} cho ${teamById(s, transferTeam)?.name ?? transferTeam}`
                : `Đã chuyển ${transfer.name} sang ${teamById(s, transferTeam)?.name ?? transferTeam}`)
          }
        }}
      >
        {transfer && (
          <div className="aq-form">
            <div>
              <div className="aq-hint">
                {transfer.teamId
                  ? `Đang ở team: ${teamById(s, transfer.teamId)?.name ?? transfer.teamId}`
                  : 'Trạng thái: Chưa chia (kho chờ của Admin/PM)'}
              </div>
              <Select showSearch optionFilterProp="label" style={{ width: '100%' }} placeholder="Chọn team nhận" value={transferTeam} onChange={setTransferTeam}
                options={transferOptions} notFoundContent="Không có team hợp lệ" />
            </div>
            <p className="aq-hint" style={{ marginTop: 12 }}>
              {transfer.status === 'pending'
                ? `Toàn bộ ${jobsNotPastQc1(transfer.id)} job của batch sẽ được đưa vào kho chờ (team_pool) của team được chọn.`
                : `${jobsNotPastQc1(transfer.id)} job chưa qua QC1 sẽ về hàng chờ team mới, người làm (annotator/QC1) bị gỡ.`}
            </p>
          </div>
        )}
      </Modal>

      <ConfirmDanger
        open={!!release} title={`Release ${release?.name ?? ''}`} okText="Release"
        onCancel={() => setRelease(null)}
        onOk={() => { if (release) run(() => { s.releaseBatch(release.id); setRelease(null) }, 'Đã release batch') }}
      >
        Thao tác này xoá batch và annotation, chuyển dữ liệu thô về kho. Không thể hoàn tác.
      </ConfirmDanger>

      <Modal
        className="cvd-modal" open={!!lock} title={`Khoá tự động ${lock?.name ?? ''}`} okText="Lưu" cancelText="Huỷ" destroyOnClose
        okButtonProps={{ disabled: !lockDate || !lockTime }} onCancel={() => setLock(null)}
        onOk={() => {
          if (!lock || !lockDate || !lockTime) return
          const at = lockDate.hour(lockTime.hour()).minute(lockTime.minute()).second(0).millisecond(0)
          run(() => { s.setAutoLock(lock.id, at.toISOString()); setLock(null) }, 'Đã đặt khoá tự động')
        }}
      >
        <div className="aq-actions">
          <DatePicker value={lockDate} onChange={setLockDate} format="DD/MM/YYYY" allowClear={false} />
          <TimePicker value={lockTime} onChange={setLockTime} format="HH:mm" allowClear={false} />
        </div>
        <p className="aq-hint" style={{ marginTop: 12 }}>Quá hạn, annotator/QC không mở được job của batch.</p>
      </Modal>

      <BatchDueModal
        batch={dueBatch} onCancel={() => setDueBatch(null)}
        onSave={(id, due, buf) => run(() => { s.setBatchDue(id, due, buf); setDueBatch(null) }, 'Đã lưu hạn giao')}
      />

      <Drawer title={`Lịch sử ${history?.name ?? ''}`} open={!!history} onClose={() => setHistory(null)} width={420}>
        {hist.length === 0 && <div className="cvd-empty">Chưa có sự kiện</div>}
        {hist.map((e) => (
          <div key={e.id} className="aq-hist">
            <div className="aq-hint">{fmtDateTime(e.at)} · {userById(s, e.actorId)?.name ?? e.actorId}</div>
            <div><Tag tone={EVENT_LABEL[e.type][1]}>{EVENT_LABEL[e.type][0]}</Tag></div>
            <div>{e.detail}</div>
          </div>
        ))}
      </Drawer>
    </>
  )

  return { menu, holder }
}
