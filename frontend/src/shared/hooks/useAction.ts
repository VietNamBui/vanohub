import { App } from 'antd'
import { useCallback, useState } from 'react'
import { getErrorMessage } from '../api/errors'

/**
 * Chạy một thao tác ghi (POST/PATCH...) và tự hiện thông báo thành công / lỗi.
 * Lỗi nghiệp vụ từ backend (vd. "Luật bốn mắt: ...") được hiện nguyên văn.
 */
export function useAction() {
  const { message } = App.useApp()
  const [pending, setPending] = useState(false)

  const run = useCallback(
    async <T>(action: () => Promise<T>, successMessage?: string): Promise<T | undefined> => {
      setPending(true)
      try {
        const result = await action()
        if (successMessage) message.success(successMessage)
        return result
      } catch (error) {
        message.error(getErrorMessage(error))
        return undefined
      } finally {
        setPending(false)
      }
    },
    [message],
  )

  return { run, pending }
}
