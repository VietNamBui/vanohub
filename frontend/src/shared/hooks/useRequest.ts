import { useEffect, useEffectEvent, useState } from 'react'

type Result<T> = { key: string; data: T | null; error: unknown }

/**
 * Gọi một hàm bất đồng bộ (thường là API) và theo dõi trạng thái loading / data / error.
 *
 * `key` đại diện cho "dữ liệu nào đang cần": khi key đổi (vd. đổi projectId), hook gọi lại.
 * Kết quả cũ của key khác không bị hiển thị nhầm vì `isLoading` so sánh key.
 */
export function useRequest<T>(key: string, request: () => Promise<T>) {
  const [result, setResult] = useState<Result<T> | null>(null)
  const [attempt, setAttempt] = useState(0)
  const requestKey = `${key}#${attempt}`

  // useEffectEvent: luôn dùng `request` mới nhất mà không phải đưa vào dependency của effect.
  const run = useEffectEvent(() => request())

  useEffect(() => {
    let ignore = false // bỏ kết quả nếu key đã đổi trước khi request cũ trả về
    run().then(
      (data) => !ignore && setResult({ key: requestKey, data, error: null }),
      (error: unknown) => !ignore && setResult({ key: requestKey, data: null, error }),
    )
    return () => {
      ignore = true
    }
  }, [requestKey])

  const current = result?.key === requestKey ? result : null
  return {
    isLoading: current === null,
    data: current?.data ?? null,
    error: current?.error ?? null,
    retry: () => setAttempt((n) => n + 1),
  }
}
