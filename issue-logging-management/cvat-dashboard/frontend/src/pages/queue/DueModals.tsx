import { useEffect, useState } from 'react'
import { InputNumber, Modal } from 'antd'
import dayjs from 'dayjs'
import { DueEditor } from '../../components'
import type { Batch, WorkStep } from '../../mock/types'

const num = (v: number | null): number => (v === null || Number.isNaN(v) ? 0 : v)

export interface BatchDueModalProps {
  batch: Batch | null
  onCancel: () => void
  onSave: (batchId: string, dueAt: string, buffer: { qc1: number; qc2: number }) => void
}

/** Đặt / sửa hạn giao của batch + số ngày dành cho QC1, QC2. */
export function BatchDueModal({ batch, onCancel, onSave }: BatchDueModalProps) {
  const [due, setDue] = useState<string | null>(null)
  const [qc1, setQc1] = useState(2)
  const [qc2, setQc2] = useState(1)
  useEffect(() => {
    if (!batch) return
    setDue(batch.dueAt); setQc1(batch.stepBufferDays.qc1); setQc2(batch.stepBufferDays.qc2)
  }, [batch])
  return (
    <Modal
      className="cvd-modal" open={!!batch} title={`${batch?.dueAt ? 'Sửa' : 'Đặt'} hạn giao ${batch?.name ?? ''}`}
      okText="Lưu" cancelText="Huỷ" destroyOnClose okButtonProps={{ disabled: !due }} onCancel={onCancel}
      onOk={() => { if (batch && due) onSave(batch.id, due, { qc1: num(qc1), qc2: num(qc2) }) }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div>
          <div className="aq-hint">Hạn giao đối tác</div>
          <DueEditor value={due} onChange={setDue} />
        </div>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          <div>
            <div className="aq-hint">Số ngày cho QC1</div>
            <InputNumber min={0} value={qc1} onChange={(v) => setQc1(num(v))} addonAfter="ngày" style={{ width: 130 }} />
          </div>
          <div>
            <div className="aq-hint">Số ngày cho QC2</div>
            <InputNumber min={0} value={qc2} onChange={(v) => setQc2(num(v))} addonAfter="ngày" style={{ width: 130 }} />
          </div>
        </div>
        <p className="aq-hint" style={{ margin: 0 }}>Hạn mặc định của từng bước được tính lùi từ hạn giao. Hạn giao không ảnh hưởng khoá tự động.</p>
      </div>
    </Modal>
  )
}

export interface JobDueTarget { jobId: string; step: WorkStep; current: string | null; hasOverride: boolean }

export interface JobDueModalProps {
  target: JobDueTarget | null
  onCancel: () => void
  onSave: (t: JobDueTarget, dueAt: string | null) => void
}

const STEP_NAME: Record<WorkStep, string> = { annotate: 'Gán nhãn', qc1: 'QC1', qc2: 'QC2 · Audit' }

/** Sửa hạn riêng của một job cho bước hiện tại; có "Bỏ hạn riêng". */
export function JobDueModal({ target, onCancel, onSave }: JobDueModalProps) {
  const [due, setDue] = useState<string | null>(null)
  useEffect(() => { setDue(target?.current ?? null) }, [target])
  return (
    <Modal
      className="cvd-modal" open={!!target} destroyOnClose onCancel={onCancel}
      title={target ? `Hạn ${STEP_NAME[target.step]} của ${target.jobId}` : ''}
      okText="Lưu" cancelText="Huỷ" okButtonProps={{ disabled: !due }}
      onOk={() => { if (target && due) onSave(target, due) }}
      footer={(_, { OkBtn, CancelBtn }) => (
        <>
          {target?.hasOverride && (
            <a style={{ float: 'left', lineHeight: '32px' }} onClick={() => { if (target) onSave(target, null) }}>Bỏ hạn riêng</a>
          )}
          <CancelBtn /><OkBtn />
        </>
      )}
    >
      <DueEditor value={due} onChange={setDue} />
      {target?.current && <p className="aq-hint" style={{ marginTop: 12 }}>Hiện tại: {dayjs(target.current).format('DD/MM/YYYY HH:mm')}</p>}
    </Modal>
  )
}
