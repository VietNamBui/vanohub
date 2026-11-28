import { HelpCircle, RefreshCw01 } from '@untitledui/icons'
import { useState } from 'react'
import { Button } from '@/components/base/buttons/button'
import { Toggle } from '@/components/base/toggle/toggle'
import { Tooltip, TooltipTrigger } from '@/components/base/tooltip/tooltip'
import { useAction } from '../../../shared/hooks/useAction'
import { useToast } from '../../../shared/hooks/toastContext'
import { syncProjectWithCvat } from '../api'
import { formatCvatSyncSummary } from '../projectHelpers'

/** Nút "Đồng bộ CVAT": kéo project / task / job mới của organization từ CVAT về, cập nhật trạng thái job. */
export default function CvatSyncButton({
  projectId,
  onDone,
  size = 'md',
  disabled = false,
}: {
  projectId: number
  onDone: () => void
  size?: 'sm' | 'md'
  disabled?: boolean
}) {
  const { run, pending } = useAction()
  const toast = useToast()
  const [countObjects, setCountObjects] = useState(false)

  async function sync() {
    const r = await run(() => syncProjectWithCvat(projectId, countObjects))
    if (!r) return
    toast.success(formatCvatSyncSummary(r))
    if (r.assignee_error) toast.warning(`Chưa đẩy được người giữ job sang CVAT: ${r.assignee_error}`, 8)
    else if (r.waiting_link) toast.info(`${r.waiting_link} job đang chờ người giữ liên kết CVAT.`)
    onDone()
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex items-center gap-1.5">
        <Toggle
          size="sm"
          className="items-center"
          isSelected={countObjects}
          onChange={setCountObjects}
          isDisabled={disabled || pending}
          label="Đếm lại object"
        />
        <Tooltip
          title="Khi bật, hệ thống đếm lại số object từ CVAT cho các job đang mở (chậm hơn nếu nhiều job)."
          placement="top"
        >
          <TooltipTrigger className="text-fg-quaternary" aria-label="Giải thích đếm lại object">
            <HelpCircle className="size-4" />
          </TooltipTrigger>
        </Tooltip>
      </div>
      <Button
        size={size}
        color="secondary"
        iconLeading={RefreshCw01}
        isLoading={pending}
        isDisabled={disabled}
        onPress={sync}
      >
        Đồng bộ CVAT
      </Button>
    </div>
  )
}
