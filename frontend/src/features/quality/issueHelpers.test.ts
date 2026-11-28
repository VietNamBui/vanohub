import { describe, expect, it } from 'vitest'
import {
  buildRejectPrefillFromIssue,
  formatIssueFrameLabel,
  formatIssueObjectLabel,
  formatRulingAttributes,
  getAnnotatorAddressBlockReason,
  getAnnotatorDisputeBlockReason,
  getSelectForRejectBlockReason,
  isAcceptanceBlockingIssue,
  isSubmitBlockingIssue,
  matchCategoryForIssue,
  parseRulingAttributes,
} from './issueHelpers'
import type { ErrorCategory, JobIssue } from './types'

const CATS: ErrorCategory[] = [
  {
    id: 1,
    code: 'EXI-MISS',
    primary_category: 'E1',
    name: 'Thiếu đối tượng',
    description: '',
    severity: 'critical',
    applies_to: 'both',
    is_active: true,
  },
  {
    id: 2,
    code: 'CLS-WRONG',
    primary_category: 'E2',
    name: 'Sai nhãn lớp',
    description: '',
    severity: 'major',
    applies_to: 'both',
    is_active: true,
  },
]

const baseIssue: JobIssue = {
  id: 10,
  job: 1,
  job_name: 'Job 1',
  cvat_issue_id: 501,
  first_comment_id: 100,
  defect_code: 'EXI-MISS',
  primary_category: 'E1',
  severity: 'critical',
  source: 'manual',
  is_clarification: false,
  frame_number: 12,
  frame_start: null,
  frame_end: null,
  track_id: null,
  shape_id: null,
  position: [],
  message: 'Thiếu xe tải phía sau',
  author: null,
  author_cvat_id: 7,
  author_stage: 'qc1',
  authority_status: 'valid',
  status: 'open',
  cvat_resolved: false,
  cvat_last_comment_id: 100,
  cvat_synced_at: null,
  source_missing: false,
  tampered: false,
  tamper_reason: '',
  cvat_reopen_drift: false,
  is_disputed: false,
  dispute_reason: '',
  ruling_label: '',
  ruling_attributes: {},
  ruling_note: '',
  ruled_by: null,
  ruled_at: null,
  created_at: '2026-11-28T00:00:00Z',
  updated_at: '2026-11-28T00:00:00Z',
}

describe('issueHelpers', () => {
  it('matches error category by defect_code first, then primary_category', () => {
    expect(matchCategoryForIssue({ defect_code: 'EXI-MISS', primary_category: 'E2' }, CATS)?.id).toBe(1)
    expect(matchCategoryForIssue({ defect_code: 'UNKNOWN', primary_category: 'E2' }, CATS)?.id).toBe(2)
    expect(matchCategoryForIssue({ defect_code: 'UNKNOWN', primary_category: '' }, CATS)).toBeNull()
  })

  it('builds reject prefill for EXI-MISS vs object-bound issue', () => {
    const miss = buildRejectPrefillFromIssue(baseIssue, CATS)
    expect(miss.is_missing_object).toBe(true)
    expect(miss.cvat_object_id).toBe('')
    expect(miss.category).toBe(1)
    expect(miss.frame_number).toBe('12')

    const obj = buildRejectPrefillFromIssue(
      { ...baseIssue, defect_code: 'CLS-WRONG', primary_category: 'E2', track_id: 42 },
      CATS,
    )
    expect(obj.is_missing_object).toBe(false)
    expect(obj.cvat_object_id).toBe('42')
    expect(obj.category).toBe(2)
  })

  it('enforces annotator address & dispute block reasons including escalation block', () => {
    expect(getAnnotatorAddressBlockReason(baseIssue, 'annotating', false, false)).toBeNull()
    expect(getAnnotatorAddressBlockReason(baseIssue, 'annotating', true, false)).toBeTruthy()
    expect(getAnnotatorAddressBlockReason(baseIssue, 'annotating', false, true)).toBeTruthy()
    expect(getAnnotatorAddressBlockReason({ ...baseIssue, is_clarification: true, ruled_at: null }, 'annotating')).toBeTruthy()
    expect(getAnnotatorDisputeBlockReason(baseIssue, 'rework', false)).toBeNull()
    expect(getAnnotatorDisputeBlockReason({ ...baseIssue, is_disputed: true }, 'rework', false)).toBeTruthy()
    expect(getAnnotatorDisputeBlockReason(baseIssue, 'approved', false)).toBeTruthy()
  })

  it('blocks unruled clarifications and cross-stage/out-of-frame issues from Reject selection', () => {
    expect(getSelectForRejectBlockReason(baseIssue, 'qc1')).toBeNull()
    expect(getSelectForRejectBlockReason({ ...baseIssue, is_clarification: true, ruled_at: null }, 'qc1')).toBeTruthy()
    expect(getSelectForRejectBlockReason(baseIssue, 'qc2', [12])).toBeTruthy() // qc1 author_stage blocked in qc2
    expect(getSelectForRejectBlockReason({ ...baseIssue, author_stage: 'qc2' }, 'qc2', [10, 11])).toBeTruthy()
    expect(getSelectForRejectBlockReason({ ...baseIssue, author_stage: 'qc2' }, 'qc2', [12])).toBeNull()
  })

  it('computes submit and acceptance gate blocking accurately', () => {
    expect(isSubmitBlockingIssue(baseIssue)).toBe(true)
    expect(isSubmitBlockingIssue({ ...baseIssue, status: 'unclear' })).toBe(false)
    expect(isAcceptanceBlockingIssue({ ...baseIssue, status: 'unclear' })).toBe(true)
    expect(isAcceptanceBlockingIssue({ ...baseIssue, severity: 'minor', ruled_at: null })).toBe(false)
    expect(isAcceptanceBlockingIssue({ ...baseIssue, severity: 'minor', ruled_at: '2026-11-28T01:00:00Z' })).toBe(true)
  })

  it('formats labels and round-trips ruling attributes', () => {
    expect(formatIssueFrameLabel({ frame_number: 5, frame_start: 1, frame_end: 9 })).toContain('1–9')
    expect(formatIssueObjectLabel({ track_id: 7, shape_id: 3 })).toBe('Track #7')
    expect(formatRulingAttributes({ occluded: true, score: 2 })).toBe('occluded=true\nscore=2')
    const parsed = parseRulingAttributes('occluded=true\nscore=2\nnote=ok\nempty=')
    expect(parsed.valid).toBe(true)
    expect(parsed.value).toEqual({ occluded: true, score: 2, note: 'ok', empty: null })
    expect(parseRulingAttributes('invalid_line').valid).toBe(false)
  })
})
