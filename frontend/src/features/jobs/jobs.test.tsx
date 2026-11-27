import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import type { UserBrief } from '../../shared/api/types'
import type { Member } from '../projects/types'
import AssigneeSelect from './components/AssigneeSelect'
import JobStatusTag from './components/JobStatusTag'
import { JOB_STATUS_LABELS } from './constants'
import {
  activeErrorRound,
  buildAssigneeOptions,
  buildAssignPayload,
  buildQueueJobsUrl,
  describeTimelineEvent,
  getJobLockReason,
  nextJobSortOrdering,
  parseJobUrlFilters,
  parseQueueUrlParams,
  serializeJobUrlFilters,
  splitActiveErrors,
  timelineDotColor,
} from './jobHelpers'
import type { JobDetail, JobStatus } from './types'

function makeUser(id: number, username: string, fullName: string): UserBrief {
  return { id, username, full_name: fullName }
}

function makeMember(
  id: number,
  username: string,
  fullName: string,
  roles: Member['roles'],
  cvatLinked: boolean,
): Member {
  return {
    user: makeUser(id, username, fullName),
    roles,
    direct_roles: roles,
    team: null,
    active_jobs: 1,
    cvat_linked: cvatLinked,
    cvat_username: cvatLinked ? username : null,
    has_initial_password: false,
  }
}

describe('jobs URL filters, sorting & lock helpers', () => {
  it('parses and serializes Jobs URL filters safely, ignoring invalid params', () => {
    const parsed = parseJobUrlFilters(
      new URLSearchParams(
        'stage=qc1&status=pending_qc1&dataset=12&batch=-4&assignee=abc&search=job_1&escalated=1&overdue=0&due_soon=true&unassigned=1',
      ),
    )
    expect(parsed).toEqual({
      stage: 'qc1',
      status: 'pending_qc1',
      dataset: 12,
      batch: undefined,
      assignee: undefined,
      search: 'job_1',
      escalated: true,
      overdue: false,
      due_soon: false,
      unassigned: true,
    })

    const badStage = parseJobUrlFilters(new URLSearchParams('stage=invalid&dataset=1.5&batch=0'))
    expect(badStage.stage).toBe('')
    expect(badStage.dataset).toBeUndefined()
    expect(badStage.batch).toBeUndefined()

    const serialized = serializeJobUrlFilters({
      stage: 'qc2',
      dataset: 5,
      search: '   frame 10  ',
      escalated: false,
      overdue: true,
      due_soon: false,
      unassigned: false,
    })
    expect(serialized.toString()).toBe('stage=qc2&dataset=5&search=frame+10&overdue=1')

    const whitespaceSearch = serializeJobUrlFilters({ stage: '', search: '   ' })
    expect(whitespaceSearch.toString()).toBe('')
  })

  it('cycles 3-state job sorting (asc -> desc -> unsorted) and resets on column change', () => {
    const s1 = nextJobSortOrdering(undefined, { column: 'deadline', direction: 'ascending' })
    expect(s1).toBe('deadline')
    const s2 = nextJobSortOrdering(s1, { column: 'deadline', direction: 'descending' })
    expect(s2).toBe('-deadline')
    const s3 = nextJobSortOrdering(s2, { column: 'deadline', direction: 'ascending' })
    expect(s3).toBeUndefined()

    const switched = nextJobSortOrdering('-deadline', { column: 'rework_round', direction: 'ascending' })
    expect(switched).toBe('rework_round')
  })

  it('evaluates job lock reason in strict permission -> locked -> delivered -> post-qc1 order', () => {
    expect(getJobLockReason(false, { is_locked: true, status: 'delivered' })).toBe('Bạn không có quyền giao job')
    expect(getJobLockReason(true, { is_locked: true, status: 'annotating' })).toBe('Job đang bị khoá')
    expect(getJobLockReason(true, { is_locked: false, status: 'delivered' })).toBe('Job đã bàn giao')
    expect(getJobLockReason(true, { is_locked: false, status: 'qc1_passed' })).toBe(
      'Không đổi người phụ trách sau khi job đã qua QC1',
    )
    expect(getJobLockReason(true, { is_locked: false, status: 'pending_qc2' })).toBe(
      'Không đổi người phụ trách sau khi job đã qua QC1',
    )
    expect(getJobLockReason(true, { is_locked: false, status: 'approved' })).toBe(
      'Không đổi người phụ trách sau khi job đã qua QC1',
    )
    expect(getJobLockReason(true, { is_locked: false, status: 'annotating' })).toBeNull()
  })

  it('computes active rework error round and splits active vs history errors across escalation resets', () => {
    expect(activeErrorRound({ rework_round: 0, total_rework_rounds: 0 })).toBeNull()
    expect(activeErrorRound({ rework_round: 2, total_rework_rounds: 2 })).toBe(1)
    expect(activeErrorRound({ rework_round: 1, total_rework_rounds: 4 })).toBe(3)

    const errors = [
      { id: 1, stage: 'qc1', rework_round: 0, category: 'Sai', severity: 'major', location: '', description: '', reported_by: null, created_at: '' },
      { id: 2, stage: 'qc1', rework_round: 3, category: 'Sai', severity: 'major', location: '', description: '', is_voided: false, reported_by: null, created_at: '' },
      { id: 3, stage: 'qc1', rework_round: 3, category: 'Sai', severity: 'minor', location: '', description: '', is_voided: true, reported_by: null, created_at: '' },
    ] as const
    const split = splitActiveErrors({ rework_round: 1, total_rework_rounds: 4 }, [...errors])
    expect(split.active.map((e) => e.id)).toEqual([2])
    expect(split.history.map((e) => e.id)).toEqual([1, 3])
  })

  it('parses Queue URL params and builds relative Jobs links cleanly', () => {
    expect(parseQueueUrlParams(new URLSearchParams('batch=7&stage=qc2'))).toEqual({ batch: 7, stage: 'qc2' })
    expect(parseQueueUrlParams(new URLSearchParams('batch=0&stage=done'))).toEqual({ batch: undefined, stage: '' })
    expect(buildQueueJobsUrl(7, { stage: 'qc1', status: 'pending_qc1', empty: '' })).toBe(
      '../jobs?batch=7&stage=qc1&status=pending_qc1',
    )
    expect(buildQueueJobsUrl(undefined, { status: undefined })).toBe('../jobs')
  })
})

describe('assignee, modal payload & timeline helpers + component regressions', () => {
  it('applies four-eyes blockedIds, retains removed current assignee, and flags unlinked CVAT user', () => {
    const m1 = makeMember(1, 'ann1', 'Nguyễn An', ['annotator'], true)
    const m2 = makeMember(2, 'ann2', 'Trần Bình', ['annotator', 'qc1'], false)
    const former = makeUser(9, 'old_user', 'Người Cũ')

    const res = buildAssigneeOptions([m1, m2], former, [1])
    expect(res.selectedUnlinked).toBe(false)
    expect(res.items.map((i) => ({ id: i.id, isDisabled: i.isDisabled }))).toEqual([
      { id: 9, isDisabled: true },
      { id: 1, isDisabled: true },
      { id: 2, isDisabled: false },
    ])

    const unlinkedRes = buildAssigneeOptions([m1, m2], m2.user, [])
    expect(unlinkedRes.selectedUnlinked).toBe(true)

    const unlinkedHtml = renderToStaticMarkup(
      <AssigneeSelect value={m2.user} options={[m1, m2]} onChange={vi.fn()} />,
    )
    expect(unlinkedHtml).toContain('Trần Bình')
    expect(unlinkedHtml).toContain('aria-label="Chưa liên kết CVAT"')

    const linkedHtml = renderToStaticMarkup(
      <AssigneeSelect value={m1.user} options={[m1, m2]} onChange={vi.fn()} />,
    )
    expect(linkedHtml).not.toContain('aria-label="Chưa liên kết CVAT"')

    const disabledHtml = renderToStaticMarkup(
      <AssigneeSelect value={null} options={[m1]} onChange={vi.fn()} disabled />,
    )
    expect(disabledHtml).toBe('<span class="text-sm text-tertiary">Chưa giao</span>')
  })

  it('builds partial assign payload only for touched fields and skips when untouched', () => {
    expect(
      buildAssignPayload({ touchedAnnotator: false, touchedQc1: false, annotator: 1, qc1Reviewer: 2, note: 'x' }),
    ).toBeNull()
    expect(
      buildAssignPayload({ touchedAnnotator: true, touchedQc1: false, annotator: null, qc1Reviewer: 2, note: 'unassign' }),
    ).toEqual({ note: 'unassign', annotator: null })
    expect(
      buildAssignPayload({ touchedAnnotator: true, touchedQc1: true, annotator: 5, qc1Reviewer: 8, note: '' }),
    ).toEqual({ note: '', annotator: 5, qc1_reviewer: 8 })
  })

  it('describes timeline events in Asia/Ho_Chi_Minh UTC+7 and maps dot colors', () => {
    const baseEvent: JobDetail['timeline'][number] = {
      id: 1,
      actor: null,
      action: 'job.status',
      target_type: 'job',
      target_id: 1,
      target_label: 'Job 1',
      job: 1,
      before: null,
      after: { status: 'qc1_passed' },
      note: '',
      created_at: '2026-11-26T18:30:00Z',
    }
    expect(describeTimelineEvent(baseEvent)).toBe(`→ ${JOB_STATUS_LABELS.qc1_passed}`)
    expect(describeTimelineEvent({ ...baseEvent, action: 'qc2.pass', after: { status: 'approved' } })).toBe(
      `→ ${JOB_STATUS_LABELS.approved}`,
    )
    expect(
      describeTimelineEvent({ ...baseEvent, action: 'job.deadline', after: { deadline: '2026-11-26T18:30:00Z' } }),
    ).toBe('→ 27/11/2026 01:30')
    expect(describeTimelineEvent({ ...baseEvent, action: 'job.deadline', after: { deadline: null } })).toBe(
      '→ không có deadline',
    )
    expect(describeTimelineEvent({ ...baseEvent, action: 'job.assign', after: {} })).toBe('')

    expect(timelineDotColor('qc2.reject')).toBe('bg-fg-error-primary')
    expect(timelineDotColor('qc2.pass')).toBe('bg-fg-success-primary')
    expect(timelineDotColor('job.status')).toBe('bg-brand-solid')
  })

  it('renders JobStatusTag for all 9 statuses and secondary flags', () => {
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
      const html = renderToStaticMarkup(<JobStatusTag status={status} />)
      expect(html).toContain(JOB_STATUS_LABELS[status])
    }

    const flaggedHtml = renderToStaticMarkup(
      <JobStatusTag status="rework" escalated overdue sourceMissing locked />,
    )
    expect(flaggedHtml).toContain('Escalated')
    expect(flaggedHtml).toContain('Quá hạn')
    expect(flaggedHtml).toContain('Thiếu nguồn CVAT')
    expect(flaggedHtml).toContain('Khoá')
  })
})
