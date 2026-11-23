import { Bell01 } from '@untitledui/icons'
import { useEffect, useState } from 'react'
import { Button as AriaButton, Dialog as AriaDialog, DialogTrigger, Popover } from 'react-aria-components'
import { Link } from 'react-router'
import { useAuth } from '../features/auth/useAuth'
import { listAnnouncements } from '../features/projects/api'
import type { Announcement, ProjectSummary } from '../features/projects/types'
import { useRequest } from '../shared/hooks/useRequest'
import { ROLE_SHORT_LABELS } from '../shared/types/roles'
import { formatDateTime, formatRelative } from '../shared/utils/format'
import { cx } from '@/utils/cx'

const POLL_MS = 60_000

type Item = Announcement & { projectId: number; projectName: string }

/** Mốc "đã xem đến" lưu trên trình duyệt, theo từng user + dự án. */
const seenKey = (userId: number, projectId: number) => `vanohub:notifSeen:${userId}:${projectId}`
function readSeen(key: string): number {
  try {
    return Number(localStorage.getItem(key)) || 0
  } catch {
    return 0
  }
}
function writeSeen(key: string, value: number) {
  try {
    localStorage.setItem(key, String(value))
  } catch {
    // Trình duyệt chặn localStorage → chỉ mất trạng thái đã đọc.
  }
}

/** Lấy thông báo của nhiều dự án; dự án nào lỗi thì bỏ qua để các dự án khác vẫn hiện. */
async function loadItems(projects: ProjectSummary[]): Promise<Item[]> {
  const results = await Promise.allSettled(
    projects.map(async (p) => (await listAnnouncements(p.id)).map((a) => ({ ...a, projectId: p.id, projectName: p.name }))),
  )
  if (results.length > 0 && results.every((r) => r.status === 'rejected')) throw (results[0] as PromiseRejectedResult).reason
  return results
    .flatMap((r) => (r.status === 'fulfilled' ? r.value : []))
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
}

/**
 * Chuông thông báo trên thanh trên cùng. Nguồn: Thông báo dự án dành cho vai trò/team của mình (backend lọc).
 * - Trong một dự án: chỉ thông báo của dự án đó.
 * - Ngoài dự án (trang chọn dự án): gộp thông báo của mọi dự án mình tham gia, có ghi tên dự án.
 *
 * "Chưa đọc" = mới hơn lần cuối mở chuông, không tính thông báo do chính mình gửi.
 * Trạng thái này lưu trên trình duyệt (chưa có backend lưu đã đọc). Tự tải lại mỗi phút.
 */
export default function NotificationBell({ projects }: { projects: ProjectSummary[] }) {
  const { user } = useAuth()
  const userId = user?.id ?? 0
  const [tick, setTick] = useState(0)
  const scopeKey = projects.map((p) => p.id).join(',')
  const { data, isLoading, error } = useRequest(`notif:${scopeKey}:${tick}`, () => loadItems(projects))
  // Giữ danh sách cũ trong lúc tải lại định kỳ để popup không nhấp nháy.
  const [items, setItems] = useState<Item[]>([])
  const [itemsFor, setItemsFor] = useState(scopeKey)
  // Mốc đã xem vừa ghi trong phiên này (dự án chưa có ở đây thì đọc từ localStorage).
  const [seenMap, setSeenMap] = useState<Record<number, number>>({})
  const seenOf = (projectId: number) => seenMap[projectId] ?? readSeen(seenKey(userId, projectId))

  if (itemsFor !== scopeKey) {
    setItemsFor(scopeKey)
    setItems([])
  }
  if (data && data !== items && !isLoading) setItems(data)

  useEffect(() => {
    const timer = setInterval(() => setTick((t) => t + 1), POLL_MS)
    return () => clearInterval(timer)
  }, [])

  const isUnread = (a: Item) => new Date(a.created_at).getTime() > seenOf(a.projectId) && a.sender?.id !== userId
  const unread = items.filter(isUnread).length
  const multiProject = projects.length > 1

  function handleOpenChange(open: boolean) {
    if (open) {
      setTick((t) => t + 1) // mở ra thì lấy bản mới nhất
      return
    }
    // Đóng popup → coi như đã xem hết những gì vừa hiện (theo từng dự án).
    const next: Record<number, number> = {}
    for (const p of projects) {
      next[p.id] = Math.max(seenOf(p.id), ...items.filter((a) => a.projectId === p.id).map((a) => new Date(a.created_at).getTime()))
      writeSeen(seenKey(userId, p.id), next[p.id])
    }
    setSeenMap((current) => ({ ...current, ...next }))
  }

  return (
    <DialogTrigger onOpenChange={handleOpenChange}>
      <AriaButton
        aria-label={unread ? `Thông báo, ${unread} chưa đọc` : 'Thông báo'}
        className={({ isHovered, isPressed, isFocusVisible }) => cx(
          'relative flex size-9 cursor-pointer items-center justify-center rounded-lg text-fg-quaternary outline-focus-ring transition duration-100',
          (isHovered || isPressed) && 'bg-primary_hover text-fg-quaternary_hover',
          isFocusVisible && 'outline-2 outline-offset-2',
        )}
      >
        <Bell01 className="size-5" />
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex h-4.5 min-w-4.5 items-center justify-center rounded-full bg-error-solid px-1 text-[11px] leading-none font-semibold text-white ring-2 ring-white">
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </AriaButton>

      <Popover
        placement="bottom end"
        offset={8}
        className={({ isEntering, isExiting }) => cx(
          'w-[min(380px,calc(100vw-24px))] overflow-hidden rounded-xl bg-primary shadow-xl ring-1 ring-secondary_alt',
          isEntering && 'duration-150 ease-out animate-in fade-in slide-in-from-top-1',
          isExiting && 'duration-100 ease-in animate-out fade-out',
        )}
      >
        <AriaDialog aria-label="Thông báo" className="outline-hidden">
          {({ close }) => (
            <>
              <div className="flex items-center justify-between border-b border-secondary px-4 py-3">
                <h2 className="text-md font-semibold text-primary">Thông báo</h2>
                {unread > 0 && <span className="text-xs font-medium text-brand-secondary">{unread} chưa đọc</span>}
              </div>

              <div className="max-h-[420px] overflow-y-auto">
                {error != null && items.length === 0 ? (
                  <p className="px-4 py-10 text-center text-sm text-error-primary">Không tải được thông báo.</p>
                ) : isLoading && items.length === 0 ? (
                  <p className="px-4 py-10 text-center text-sm text-tertiary">Đang tải…</p>
                ) : items.length === 0 ? (
                  <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
                    <span className="flex size-10 items-center justify-center rounded-full bg-secondary text-fg-quaternary"><Bell01 className="size-5" /></span>
                    <p className="text-sm font-medium text-secondary">Chưa có thông báo nào</p>
                    <p className="text-xs text-tertiary">Thông báo của dự án sẽ hiện ở đây.</p>
                  </div>
                ) : (
                  <ul>
                    {items.slice(0, 20).map((a) => (
                      <li key={`${a.projectId}-${a.id}`} className={cx('border-b border-secondary last:border-0', isUnread(a) && 'bg-brand-primary_alt')}>
                        <Link to={`/projects/${a.projectId}/announcements`} onClick={close} className="flex gap-3 px-4 py-3 hover:bg-primary_hover">
                          <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-brand-secondary text-xs font-semibold text-brand-secondary">
                            {(a.sender?.full_name || a.sender?.username || '?').slice(0, 1).toUpperCase()}
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-baseline justify-between gap-2">
                              <p className="truncate text-sm font-semibold text-secondary">{a.sender?.full_name ?? 'Hệ thống'}</p>
                              <time className="shrink-0 text-xs text-quaternary" title={formatDateTime(a.created_at)}>{formatRelative(a.created_at)}</time>
                            </div>
                            {multiProject && <p className="truncate text-xs font-medium text-brand-secondary">{a.projectName}</p>}
                            <p className="mt-0.5 line-clamp-3 text-sm whitespace-pre-line text-tertiary">{a.content}</p>
                            {(a.target_roles.length > 0 || a.target_team_name) && (
                              <p className="mt-1 text-xs text-quaternary">
                                Gửi tới: {[...a.target_roles.map((r) => ROLE_SHORT_LABELS[r]), a.target_team_name].filter(Boolean).join(', ')}
                              </p>
                            )}
                          </div>
                          {isUnread(a) && <span aria-label="Chưa đọc" className="mt-1.5 size-2 shrink-0 rounded-full bg-brand-solid" />}
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {!multiProject && projects[0] && (
                <Link
                  to={`/projects/${projects[0].id}/announcements`}
                  onClick={close}
                  className="block border-t border-secondary px-4 py-3 text-center text-sm font-semibold text-brand-secondary hover:bg-primary_hover"
                >
                  Xem tất cả thông báo
                </Link>
              )}
            </>
          )}
        </AriaDialog>
      </Popover>
    </DialogTrigger>
  )
}
