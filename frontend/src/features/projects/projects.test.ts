import { describe, expect, it } from 'vitest'
import {
  ACTIVITY_ACTION_LABELS,
  canMarkNotificationRead,
  computeDeliveryDh07Summary,
  formatActivityChangeSummary,
  formatCvatSyncSummary,
  parseGuidelineSections,
  sortUnifiedNotifications,
  validateDeliveryUpdateInput,
  validateGuidelineDraft,
  validateProjectSettingsDraft,
} from './projectHelpers'
import type { ProjectSyncResult } from './types'

describe('projects helpers', () => {
  it('parses markdown guidelines into sections and normalizes bullet lists', () => {
    expect(parseGuidelineSections('')).toEqual([])
    expect(parseGuidelineSections('  \n\n  ')).toEqual([])

    const md = [
      'Đọc kỹ trước khi làm',
      '',
      '# Quy tắc chung',
      '- Kiểm tra 3 góc chiếu',
      '* Không xoá track pre-label',
      '## Kiểm tra cuối',
      'Bấm Save trước khi nộp',
    ].join('\n')

    expect(parseGuidelineSections(md)).toEqual([
      { title: 'Nội dung hướng dẫn', body: 'Đọc kỹ trước khi làm' },
      { title: 'Quy tắc chung', body: '• Kiểm tra 3 góc chiếu\n• Không xoá track pre-label' },
      { title: 'Kiểm tra cuối', body: 'Bấm Save trước khi nộp' },
    ])
  })

  it('validates guideline draft title and content after trimming', () => {
    expect(validateGuidelineDraft('   ', '  ')).toEqual({
      titleError: 'Vui lòng nhập tiêu đề.',
      contentError: 'Vui lòng nhập nội dung hướng dẫn.',
      trimmedTitle: '',
      trimmedContent: '',
      valid: false,
    })

    expect(validateGuidelineDraft('Quy tắc v2', '   ')).toEqual({
      titleError: null,
      contentError: 'Vui lòng nhập nội dung hướng dẫn.',
      trimmedTitle: 'Quy tắc v2',
      trimmedContent: '',
      valid: false,
    })

    expect(validateGuidelineDraft('  Quy tắc v2  ', '  ## Mục 1\nChi tiết  ')).toEqual({
      titleError: null,
      contentError: null,
      trimmedTitle: 'Quy tắc v2',
      trimmedContent: '## Mục 1\nChi tiết',
      valid: true,
    })
  })

  it('formats CVAT sync summary omitting zero creation/update deltas', () => {
    const base: ProjectSyncResult = {
      projects: 2,
      projects_created: 0,
      tasks: 5,
      tasks_created: 0,
      jobs_created: 0,
      jobs_updated: 0,
      assignees_pushed: 0,
      waiting_link: 0,
    }
    expect(formatCvatSyncSummary(base)).toBe('Đã đồng bộ CVAT: 2 project, 5 task.')

    expect(
      formatCvatSyncSummary({
        ...base,
        projects_created: 1,
        tasks_created: 2,
        jobs_created: 8,
        jobs_updated: 3,
      }),
    ).toBe('Đã đồng bộ CVAT: 2 project, 5 task, 1 project mới, 2 task mới, 8 job mới, 3 job cập nhật.')
  })

  it('excludes ephemeral deadline (due-*) and pinned notifications from mark-read', () => {
    expect(
      canMarkNotificationRead({ id: 'due-1-42', source: 'deadline', is_read: false, is_pinned_pending: true }),
    ).toBe(false)
    expect(
      canMarkNotificationRead({ id: 'due-1-42', source: 'deadline', is_read: false, is_pinned_pending: false }),
    ).toBe(false)
    expect(
      canMarkNotificationRead({ id: 'sys-10', source: 'system', is_read: false, is_pinned_pending: true }),
    ).toBe(false)
    expect(
      canMarkNotificationRead({ id: 'sys-11', source: 'system', is_read: true, is_pinned_pending: false }),
    ).toBe(false)
    expect(
      canMarkNotificationRead({ id: 'sys-12', source: 'system', is_read: false, is_pinned_pending: false }),
    ).toBe(true)
    expect(
      canMarkNotificationRead({ id: 'ann-5', source: 'announcement', is_read: false, is_pinned_pending: false }),
    ).toBe(true)
  })

  it('sorts notifications with unread pinned items first, then newest created_at descending', () => {
    const sorted = sortUnifiedNotifications([
      { id: '1', is_read: true, is_pinned_pending: true, created_at: '2026-11-27T10:00:00Z' },
      { id: '2', is_read: false, is_pinned_pending: false, created_at: '2026-11-27T11:00:00Z' },
      { id: '3', is_read: false, is_pinned_pending: true, created_at: '2026-11-27T09:00:00Z' },
      { id: '4', is_read: false, is_pinned_pending: true, created_at: '2026-11-27T12:00:00Z' },
    ])
    expect(sorted.map((item) => item.id)).toEqual(['4', '3', '2', '1'])
  })

  it('validates all ProjectSettings fields including issue_gate_enabled and formats decimal thresholds', () => {
    const ok = validateProjectSettingsDraft({
      max_rework_rounds: 3,
      escalation_policy: 'warn_only',
      annotator_wip_limit: 5,
      sampling_rate: 25,
      issue_gate_enabled: true,
      quality_cl_threshold: '95.5',
      defect_rate_threshold: '',
      kpi_annotation_target: '200',
      kpi_qc1_target: '',
      kpi_qc2_target: '15',
    })
    expect(ok).toEqual({
      valid: true,
      errors: {},
      payload: {
        max_rework_rounds: 3,
        escalation_policy: 'warn_only',
        annotator_wip_limit: 5,
        sampling_rate: 25,
        issue_gate_enabled: true,
        quality_cl_threshold: '95.50',
        defect_rate_threshold: null,
        kpi_annotation_target: 200,
        kpi_qc1_target: null,
        kpi_qc2_target: 15,
      },
    })

    const bad = validateProjectSettingsDraft({
      max_rework_rounds: 0,
      escalation_policy: 'block',
      annotator_wip_limit: 51,
      sampling_rate: 101,
      issue_gate_enabled: false,
      quality_cl_threshold: '120',
      defect_rate_threshold: 'abc',
      kpi_annotation_target: '0',
      kpi_qc1_target: '-5',
      kpi_qc2_target: '1.5',
    })
    expect(bad.valid).toBe(false)
    expect(bad.payload).toBeNull()
    expect(Object.keys(bad.errors).sort()).toEqual([
      'annotator_wip_limit',
      'defect_rate_threshold',
      'kpi_annotation_target',
      'kpi_qc1_target',
      'kpi_qc2_target',
      'max_rework_rounds',
      'quality_cl_threshold',
      'sampling_rate',
    ])
  })

  it('validates delivery update recipient/output_path and computes DH07 summary', () => {
    expect(
      validateDeliveryUpdateInput({ recipient: '   ', output_path: '  ', note: 'n', client_feedback: 'ok' }),
    ).toEqual({
      valid: false,
      recipientError: 'Người nhận bàn giao không được để trống.',
      outputPathError: 'Đường dẫn đầu ra không được để trống.',
      payload: null,
    })

    expect(
      validateDeliveryUpdateInput({
        recipient: '  Client A ',
        output_path: ' s3://bucket/out ',
        note: '  done ',
        client_feedback: '  LGTM ',
      }),
    ).toEqual({
      valid: true,
      recipientError: null,
      outputPathError: null,
      payload: {
        recipient: 'Client A',
        output_path: 's3://bucket/out',
        note: 'done',
        client_feedback: 'LGTM',
      },
    })

    expect(
      computeDeliveryDh07Summary(
        [
          { deadline: '2026-11-20T00:00:00Z', is_on_time: true },
          { deadline: '2026-11-21T00:00:00Z', is_on_time: false },
          { deadline: null, is_on_time: null },
        ],
        [{ is_overdue: true }, { is_overdue: false }],
      ),
    ).toEqual({
      onTimeCount: 1,
      lateCount: 1,
      overdueUndeliveredCount: 1,
      dueCount: 3,
      rate: 33.3,
    })
  })

  it('formats activity log diffs and maps known activity action labels', () => {
    expect(ACTIVITY_ACTION_LABELS['project.settings']).toBe('Đổi cấu hình organization')
    expect(
      formatActivityChangeSummary({
        before: { sampling_rate: 20 },
        after: { sampling_rate: 30, escalation_policy: 'warn_only' },
      }),
    ).toBe('Trước: sampling_rate: 20 → Sau: sampling_rate: 30, escalation_policy: warn_only')
  })
})

