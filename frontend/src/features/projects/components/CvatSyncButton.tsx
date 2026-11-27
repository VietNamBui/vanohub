import { RefreshCw01 } from '@untitledui/icons'
import { Button } from '@/components/base/buttons/button'
import { useAction } from '../../../shared/hooks/useAction'
import { useToast } from '../../../shared/hooks/toastContext'
import { syncProjectWithCvat } from '../api'
import { formatCvatSyncSummary } from '../projectHelpers'

/** Nút "Đồng bộ CVAT": kéo project / task / job mới của organization từ CVAT về, cập nhật trạng thái job. */
export default function CvatSyncButton({ projectId, onDone, size = 'md' }: { projectId: number; onDone: () => void; size?: 'sm' | 'md' }) {
  const { run, pending } = useAction()
  const toast = useToast()

  async function sync() {
    const r = await run(() => syncProjectWithCvat(projectId))
    if (!r) return
    toast.success(formatCvatSyncSummary(r))
    if (r.assignee_error) toast.warning(`Chưa đẩy được người giữ job sang CVAT: ${r.assignee_error}`, 8)
    else if (r.waiting_link) toast.info(`${r.waiting_link} job đang chờ người giữ liên kết CVAT.`)
    onDone()
  }

  return (
    <Button size={size} color="secondary" iconLeading={RefreshCw01} isLoading={pending} onPress={sync}>
      Đồng bộ CVAT
    </Button>
  )
}
