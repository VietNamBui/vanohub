import { describe, expect, it } from 'vitest'
import { ACTION_LABELS, formatDeadlineCountdown, JOB_STATUS_COLORS, JOB_STATUS_LABELS, STAGE_LABELS } from './constants'
import type { JobStatus } from './types'

describe('jobs constants & countdown helper', () => {
  it('covers all 9 lifecycle statuses including qc1_passed', () => {
    const statuses: JobStatus[] = [
      'pending_annotation',
      'annotating',
      'pending_qc1',
      'qc1_reviewing',
      'qc1_passed',
      'rework',
      'pending_qc2',
      'approved',
      'delivered',
    ]
    for (const status of statuses) {
      expect(JOB_STATUS_LABELS[status]).toBeTruthy()
      expect(JOB_STATUS_COLORS[status]).toBeTruthy()
    }
    expect(Object.keys(STAGE_LABELS)).toEqual(['annotation', 'qc1', 'qc2', 'done'])
  })

  it('includes Hybrid A2 confirm-qc2 action and uses Project/Task terminology', () => {
    expect(ACTION_LABELS['batch.confirm_qc2']).toBe('Xác nhận chuyển QC2')
    expect(ACTION_LABELS['dataset.create']).toBe('Tạo project')
    expect(ACTION_LABELS['batch.deliver']).toBe('Bàn giao task')
  })

  it('formats deadline countdown tones accurately', () => {
    expect(formatDeadlineCountdown(null)).toBeNull()
    expect(formatDeadlineCountdown(-3.4)).toEqual({ text: 'Quá hạn 3 giờ', tone: 'error' })
    expect(formatDeadlineCountdown(8.2)).toEqual({ text: 'Còn 8 giờ', tone: 'warning' })
    expect(formatDeadlineCountdown(48)).toEqual({ text: 'Còn 48 giờ', tone: 'gray' })
  })
})
