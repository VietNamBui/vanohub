import { AlertCircle, AlertTriangle, CheckCircle, InfoCircle, XClose } from '@untitledui/icons'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Button } from '@/components/base/buttons/button'
import { cx } from '@/utils/cx'
import { ToastContext, type ToastApi, type ToastKind } from '../../hooks/toastContext'

interface ToastItem {
  id: number
  kind: ToastKind
  text: string
}

const KIND_STYLES: Record<ToastKind, { ring: string; bg: string; iconClass: string; Icon: typeof CheckCircle }> = {
  success: { ring: 'ring-success_subtle', bg: 'bg-primary', iconClass: 'text-fg-success-primary', Icon: CheckCircle },
  error: { ring: 'ring-error_subtle', bg: 'bg-error-primary', iconClass: 'text-fg-error-primary', Icon: AlertCircle },
  warning: { ring: 'ring-utility-yellow-200', bg: 'bg-warning-primary', iconClass: 'text-fg-warning-primary', Icon: AlertTriangle },
  info: { ring: 'ring-brand', bg: 'bg-brand-primary_alt', iconClass: 'text-fg-brand-primary', Icon: InfoCircle },
}

/** Hệ thống thông báo nổi dùng chung (thay thế Ant Design message/App.useApp). */
export default function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const nextIdRef = useRef(1)
  const timersRef = useRef<Map<number, number>>(new Map())

  const dismiss = useCallback((id: number) => {
    const timer = timersRef.current.get(id)
    if (timer !== undefined) {
      window.clearTimeout(timer)
      timersRef.current.delete(id)
    }
    setItems((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const push = useCallback(
    (kind: ToastKind, text: string, durationSec?: number) => {
      const id = nextIdRef.current++
      const ms = Math.round((durationSec ?? (kind === 'error' ? 5 : 3.5)) * 1000)
      setItems((prev) => [...prev.slice(-4), { id, kind, text }])
      const timer = window.setTimeout(() => dismiss(id), ms)
      timersRef.current.set(id, timer)
    },
    [dismiss],
  )

  useEffect(() => {
    const timers = timersRef.current
    return () => {
      for (const timer of timers.values()) window.clearTimeout(timer)
      timers.clear()
    }
  }, [])

  const api = useMemo<ToastApi>(
    () => ({
      success: (text, durationSec) => push('success', text, durationSec),
      error: (text, durationSec) => push('error', text, durationSec),
      warning: (text, durationSec) => push('warning', text, durationSec),
      info: (text, durationSec) => push('info', text, durationSec),
    }),
    [push],
  )

  return (
    <ToastContext.Provider value={api}>
      {children}
      {items.length > 0 && (
        <div
          aria-live="polite"
          aria-label="Thông báo hệ thống"
          className="pointer-events-none fixed top-4 left-1/2 z-[60] flex w-full max-w-md -translate-x-1/2 flex-col items-center gap-2 px-4"
        >
          {items.map((item) => {
            const { ring, bg, iconClass, Icon } = KIND_STYLES[item.kind]
            return (
              <div
                key={item.id}
                role={item.kind === 'error' ? 'alert' : 'status'}
                className={cx(
                  'pointer-events-auto flex w-full items-start gap-2.5 rounded-xl px-4 py-3 text-sm font-medium text-primary shadow-lg ring-1 ring-inset',
                  bg,
                  ring,
                )}
              >
                <Icon className={cx('mt-0.5 size-4.5 shrink-0', iconClass)} aria-hidden="true" />
                <span className="min-w-0 flex-1 break-words">{item.text}</span>
                <Button
                  size="xs"
                  color="tertiary"
                  iconLeading={XClose}
                  aria-label="Đóng thông báo"
                  className="-mr-1 -mt-0.5 shrink-0"
                  onPress={() => dismiss(item.id)}
                />
              </div>
            )
          })}
        </div>
      )}
    </ToastContext.Provider>
  )
}
