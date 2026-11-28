import { STAGE_LABEL } from '../mock/selectors'
import type { JobStage } from '../mock/types'
import { StripedBar } from '../design'

export const FUNNEL_STAGES: JobStage[] = [
  'team_pool', 'anno_in_progress', 'qc1_pending', 'qc1_in_progress', 'qc2_pending', 'qc2_in_progress', 'ready_to_deliver', 'delivered',
]

export interface StageFunnelProps {
  counts: Partial<Record<JobStage, number>>
  /** Mặc định: FUNNEL_STAGES (từ Kho team đến Đã giao). */
  stages?: JobStage[]
  onStageClick?: (stage: JobStage) => void
}

const TONE: Partial<Record<JobStage, 'blue' | 'green' | 'pink'>> = {
  ready_to_deliver: 'green', delivered: 'green', qc2_pending: 'pink', qc2_in_progress: 'pink',
}

export function StageFunnel({ counts, stages = FUNNEL_STAGES, onStageClick }: StageFunnelProps) {
  const max = Math.max(1, ...stages.map((s) => counts[s] ?? 0))
  return (
    <div className="cvd-funnel">
      {stages.map((s) => {
        const n = counts[s] ?? 0
        return (
          <div key={s} className={`cvd-funnel-row ${onStageClick ? 'clickable' : ''}`} onClick={onStageClick ? () => onStageClick(s) : undefined}>
            <span className="cvd-funnel-label">{STAGE_LABEL[s]}</span>
            <div className="cvd-funnel-track"><StripedBar value={n} max={max} tone={TONE[s] ?? 'blue'} /></div>
            <span className="cvd-funnel-count">{n}</span>
          </div>
        )
      })}
    </div>
  )
}
