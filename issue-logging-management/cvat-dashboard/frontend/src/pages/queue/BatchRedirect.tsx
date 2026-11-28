import { Navigate, useParams } from 'react-router-dom'
import { useStore } from '../../mock/store'
import { batchById } from '../../mock/selectors'
import { QUEUE_ROOT, queueBatchPath } from './queueShared'

/** `/batches/:batchId` cũ ⇒ cấp Job tương ứng của Hàng đợi (batch không tồn tại ⇒ `/queue`). */
export default function BatchRedirect() {
  const { batchId } = useParams()
  const batch = batchById(useStore(), batchId)
  return <Navigate to={batch ? queueBatchPath(batch) : QUEUE_ROOT} replace />
}
