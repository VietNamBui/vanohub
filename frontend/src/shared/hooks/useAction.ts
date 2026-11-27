import { useCallback, useState } from 'react'
import { getErrorMessage } from '../api/errors'
import { useToast } from './toastContext'

/**
 * Chạy một thao tác ghi (POST/PATCH...) và tự hiện thông báo thành công / lỗi.
 * Lỗi nghiệp vụ từ backend (vd. "Luật bốn mắt: ...") được hiện nguyên văn.
 */
export function useAction() {
  const toast = useToast()
  const [pending, setPending] = useState(false)

  const run = useCallback(
    async <T>(action: () => Promise<T>, successMessage?: string): Promise<T | undefined> => {
      setPending(true)
      try {
        const result = await action()
        if (successMessage) toast.success(successMessage)
        return result
      } catch (error) {
        toast.error(getErrorMessage(error))
        return undefined
      } finally {
        setPending(false)
      }
    },
    [toast],
  )

  return { run, pending }
}
