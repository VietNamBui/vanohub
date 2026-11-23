import { HelpCircle } from '@untitledui/icons'
import { Tooltip, TooltipTrigger } from '@/components/base/tooltip/tooltip'

export interface Metric {
  value: number | null
  status: 'ok' | 'provisional' | 'pending_definition'
  formula: string
}

/**
 * Ô chỉ số có công thức (rê vào dấu ?) và trạng thái: "Tạm tính" hoặc "Chưa chốt công thức".
 * Chỉ số chưa chốt hiện "—" — không bịa số.
 */
export default function MetricCard({ metric, label, suffix = '' }: { metric: Metric; label: string; suffix?: string }) {
  const pending = metric.status === 'pending_definition' || metric.value == null
  return (
    <div className="flex flex-col gap-1 rounded-xl bg-primary p-4 shadow-xs ring-1 ring-secondary">
      <span className={`text-display-xs font-semibold ${pending ? 'text-quaternary' : 'text-primary'}`}>
        {metric.value == null ? '—' : `${metric.value}${suffix}`}
      </span>
      <span className="flex items-center gap-1 text-sm text-tertiary">
        {label}
        <Tooltip title={metric.formula} placement="top">
          <TooltipTrigger className="text-fg-quaternary" aria-label="Công thức"><HelpCircle className="size-4" /></TooltipTrigger>
        </Tooltip>
      </span>
      {metric.status === 'pending_definition' && <span className="w-max rounded-md bg-secondary px-1.5 py-0.5 text-xs text-tertiary">Chưa chốt công thức</span>}
      {metric.status === 'provisional' && <span className="w-max rounded-md bg-brand-primary_alt px-1.5 py-0.5 text-xs text-brand-secondary">Tạm tính</span>}
    </div>
  )
}
