import type { Severity } from './types'

export const SEVERITY_LABELS: Record<Severity, string> = { minor: 'Nhẹ', major: 'Nặng', critical: 'Nghiêm trọng' }
export const SEVERITY_COLORS: Record<Severity, string> = { minor: 'default', major: 'orange', critical: 'red' }
export const RESULT_LABELS = { pending: 'Chờ audit', pass: 'Pass', reject: 'Reject' } as const
export const RESULT_COLORS = { pending: 'default', pass: 'success', reject: 'error' } as const
export const METHOD_LABELS = { random: 'Random', stratified: 'Stratified' } as const
export const STRATIFY_LABELS = { annotator: 'Annotator', qc1_reviewer: 'Người QC1', dataset: 'Dataset', '': '' } as const
