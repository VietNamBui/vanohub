import { STAGE_LABEL } from '../mock/selectors'
import type { JobStage } from '../mock/types'
import { Tag, type Tone } from '../design'

/** Tông pill của từng stage. `solid` = nền đặc (Đã giao). */
export const STAGE_COLOR: Record<JobStage, Tone> = {
  unassigned_pool: 'gray',
  team_pool: 'gray',
  anno_in_progress: 'blue',
  qc1_pending: 'orange',
  qc1_in_progress: 'orange',
  qc2_pending: 'purple',
  qc2_in_progress: 'purple',
  ready_to_deliver: 'green',
  delivered: 'green',
}

export interface StageTagProps { stage: JobStage }

export function StageTag({ stage }: StageTagProps) {
  return <Tag tone={STAGE_COLOR[stage]} solid={stage === 'delivered'}>{STAGE_LABEL[stage]}</Tag>
}
