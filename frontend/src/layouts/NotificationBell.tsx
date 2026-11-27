import { AlertTriangle, Bell01, Check, CheckCircle, Clock, InfoCircle, XClose } from '@untitledui/icons'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { Badge } from '@/components/base/badges/badges'
import { useAuth } from '../features/auth/useAuth'
import { listAnnouncements, listProjectNotifications, markProjectNotificationsRead } from '../features/projects/api'
import type { NotificationCategory, ProjectSummary, UnifiedNotification } from '../features/projects/types'
import { useRequest } from '../shared/hooks/useRequest'
import { formatDateTime, formatRelative } from '../shared/utils/format'
import { cx } from '@/utils/cx'

const POLL_MS = 60_000

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
    // ignore storage restriction
  }
}

async function fetchNotifications(projects: ProjectSummary[], userId: number): Promise<UnifiedNotification[]> {
  if (!projects.length || !userId) return []
  if (projects.length === 1) {
    const feed = await listProjectNotifications(projects[0].id)
    const seenAt = readSeen(seenKey(userId, projects[0].id))
    return feed.items.map((item) => {
      if (item.source === 'announcement' && !item.is_pinned_pending && new Date(item.created_at).getTime() <= seenAt) {
        return { ...item, is_read: true }
      }
      return item
    })
  }
  const results = await Promise.allSettled(
    projects.map(async (p) => {
      const seenAt = readSeen(seenKey(userId, p.id))
      const list = await listAnnouncements(p.id)
      return list.map<UnifiedNotification>((a) => ({
        id: `ann-${p.id}-${a.id}`,
        notification_id: null,
        source: 'announcement',
        category: 'announcement',
        title: `${p.name} · ${a.sender?.full_name ?? 'Hệ thống'}`,
        body: a.content,
        job_id: null,
        action_url: `/projects/${p.id}/announcements`,
        is_read: a.sender?.id === userId || new Date(a.created_at).getTime() <= seenAt,
        is_pinned_pending: false,
        created_at: a.created_at,
      }))
    }),
  )
  return results
    .flatMap((r) => (r.status === 'fulfilled' ? r.value : []))
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
}

function CategoryIcon({ category }: { category: NotificationCategory }) {
  if (category === 'rework') {
    return (
      <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-warning-secondary">
        <span className="flex size-7 items-center justify-center rounded-full bg-warning-secondary text-fg-warning-primary">
          <AlertTriangle className="size-4" />
        </span>
      </span>
    )
  }
  if (category === 'deadline') {
    return (
      <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-warning-secondary">
        <span className="flex size-7 items-center justify-center rounded-full bg-warning-secondary text-fg-warning-primary">
          <Clock className="size-4" />
        </span>
      </span>
    )
  }
  if (category === 'dispute') {
    return (
      <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-brand-secondary">
        <span className="flex size-7 items-center justify-center rounded-full bg-brand-secondary text-brand-secondary">
          <InfoCircle className="size-4" />
        </span>
      </span>
    )
  }
  if (category === 'qc_pass') {
    return (
      <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-success-secondary">
        <span className="flex size-7 items-center justify-center rounded-full bg-success-secondary text-fg-success-primary">
          <CheckCircle className="size-4" />
        </span>
      </span>
    )
  }
  return (
    <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-brand-secondary">
      <span className="flex size-7 items-center justify-center rounded-full bg-brand-secondary text-brand-secondary">
        <Bell01 className="size-4" />
      </span>
    </span>
  )
}

/**
 * Chuông thông báo + Drawer trượt phải 440px (Tất cả / Chưa đọc, Đánh dấu đã đọc).
 */
export default function NotificationBell({ projects }: { projects: ProjectSummary[] }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const userId = user?.id ?? 0
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<'all' | 'unread'>('all')
  const [tick, setTick] = useState(0)
  const [readIds, setReadIds] = useState<Record<string, boolean>>({})
  const scopeKey = projects.map((p) => p.id).join(',')

  const { data, error, isLoading } = useRequest(
    `notif-drawer:${scopeKey}:${userId}:${tick}`,
    () => fetchNotifications(projects, userId),
  )

  useEffect(() => {
    const timer = setInterval(() => setTick((t) => t + 1), POLL_MS)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  const items = (data ?? []).map((item) =>
    !item.is_pinned_pending && readIds[item.id] ? { ...item, is_read: true } : item,
  )
  const unreadCount = items.filter((i) => !i.is_read).length
  const visible = tab === 'unread' ? items.filter((i) => !i.is_read) : items

  async function markAllRead() {
    const nowMs = new Date().getTime()
    for (const p of projects) {
      writeSeen(seenKey(userId, p.id), nowMs)
    }
    const nextRead: Record<string, boolean> = {}
    for (const item of items) {
      if (!item.is_pinned_pending) nextRead[item.id] = true
    }
    setReadIds((prev) => ({ ...prev, ...nextRead }))
    if (projects.length === 1) {
      try {
        await markProjectNotificationsRead(projects[0].id)
      } catch {
        // ignore optimistic failure
      }
    }
  }

  async function handleItemClick(item: UnifiedNotification) {
    if (!item.is_pinned_pending) {
      setReadIds((prev) => ({ ...prev, [item.id]: true }))
    }
    if (!item.is_read && item.notification_id && projects.length === 1) {
      try {
        await markProjectNotificationsRead(projects[0].id, item.notification_id)
      } catch {
        // ignore
      }
    }
    if (item.source === 'announcement' && projects.length === 1) {
      writeSeen(seenKey(userId, projects[0].id), new Date().getTime())
    }
    setOpen(false)
    if (item.action_url) {
      navigate(item.action_url)
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => {
          setOpen(true)
          setTick((t) => t + 1)
        }}
        aria-label={unreadCount ? `Thông báo, ${unreadCount} chưa đọc` : 'Thông báo'}
        className="relative flex size-10 cursor-pointer items-center justify-center rounded-lg text-tertiary transition hover:bg-primary_hover hover:text-secondary"
      >
        <Bell01 className="size-5" />
        {unreadCount > 0 && (
          <span className="absolute top-1.5 right-1.5 size-2.5 rounded-full bg-fg-error-secondary ring-2 ring-white" />
        )}
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label="Thông báo">
          <div className="fixed inset-0 bg-overlay/70 backdrop-blur-[2px]" onClick={() => setOpen(false)} />

          <aside className="relative z-10 flex h-full w-full max-w-[440px] flex-col border-l border-secondary bg-primary shadow-2xl">
            <div className="flex items-center justify-between px-6 pt-6 pb-4">
              <h2 className="text-xl font-bold text-primary">Thông báo</h2>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={markAllRead}
                  className="inline-flex cursor-pointer items-center gap-1.5 text-sm font-semibold text-brand-secondary hover:text-brand-secondary_hover"
                >
                  <Check className="size-4" />
                  Đánh dấu đã đọc
                </button>
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  aria-label="Đóng thông báo"
                  className="flex size-8 cursor-pointer items-center justify-center rounded-lg text-quaternary hover:bg-primary_hover hover:text-tertiary"
                >
                  <XClose className="size-5" />
                </button>
              </div>
            </div>

            <div className="flex items-center gap-6 border-b border-secondary px-6">
              <button
                type="button"
                onClick={() => setTab('all')}
                className={cx(
                  'relative flex cursor-pointer items-center gap-2 pb-3 text-sm font-semibold transition',
                  tab === 'all' ? 'text-brand-secondary' : 'text-tertiary hover:text-secondary',
                )}
              >
                Tất cả
                <Badge size="sm" type="pill-color" color={tab === 'all' ? 'brand' : 'gray'}>
                  {items.length}
                </Badge>
                {tab === 'all' && <span className="absolute inset-x-0 bottom-0 h-0.5 bg-brand-solid" />}
              </button>
              <button
                type="button"
                onClick={() => setTab('unread')}
                className={cx(
                  'relative flex cursor-pointer items-center gap-2 pb-3 text-sm font-semibold transition',
                  tab === 'unread' ? 'text-brand-secondary' : 'text-tertiary hover:text-secondary',
                )}
              >
                Chưa đọc
                <Badge size="sm" type="pill-color" color={tab === 'unread' ? 'brand' : 'gray'}>
                  {unreadCount}
                </Badge>
                {tab === 'unread' && <span className="absolute inset-x-0 bottom-0 h-0.5 bg-brand-solid" />}
              </button>
            </div>

            <div className="flex-1 overflow-y-auto py-2">
              {error != null && items.length === 0 ? (
                <p className="px-6 py-12 text-center text-sm text-error-primary">Không tải được thông báo.</p>
              ) : isLoading && items.length === 0 ? (
                <p className="px-6 py-12 text-center text-sm text-tertiary">Đang tải…</p>
              ) : visible.length === 0 ? (
                <div className="flex flex-col items-center gap-2 px-6 py-14 text-center">
                  <span className="flex size-10 items-center justify-center rounded-full bg-secondary text-tertiary">
                    <Bell01 className="size-5" />
                  </span>
                  <p className="text-sm font-semibold text-secondary">
                    {tab === 'unread' ? 'Không có thông báo chưa đọc' : 'Chưa có thông báo nào'}
                  </p>
                  <p className="text-xs text-tertiary">Các thông báo của organization về rework, hạn nộp và phản hồi sẽ hiện ở đây.</p>
                </div>
              ) : (
                <ul className="divide-y divide-secondary">
                  {visible.map((item) => (
                    <li key={item.id}>
                      <button
                        type="button"
                        onClick={() => void handleItemClick(item)}
                        className={cx(
                          'relative flex w-full cursor-pointer gap-3 px-6 py-4 text-left transition hover:bg-primary_hover',
                          !item.is_read && 'bg-brand-primary_alt',
                        )}
                      >
                        {!item.is_read && (
                          <span className="absolute top-7 left-2.5 size-2 rounded-full bg-brand-solid" aria-label="Chưa đọc" />
                        )}
                        <CategoryIcon category={item.category} />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <p className="text-sm font-semibold text-primary">{item.title}</p>
                            {item.is_pinned_pending && (
                              <Badge size="sm" type="pill-color" color="warning">
                                Cần xử lý
                              </Badge>
                            )}
                          </div>
                          {item.body && (
                            <p className="mt-0.5 line-clamp-2 text-sm text-tertiary">{item.body}</p>
                          )}
                          <time
                            className="mt-1.5 block text-xs text-quaternary"
                            title={formatDateTime(item.created_at)}
                          >
                            {formatRelative(item.created_at)}
                          </time>
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <footer className="border-t border-secondary px-6 py-4 text-xs text-tertiary">
              Các thông báo cần xử lý sẽ được giữ nổi bật cho tới khi hoàn tất.
            </footer>
          </aside>
        </div>
      )}
    </>
  )
}
