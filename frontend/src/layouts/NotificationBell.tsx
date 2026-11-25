import { AlertTriangle, Bell01, Check, CheckCircle, Clock, InfoCircle, XClose } from '@untitledui/icons'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { Badge } from '@/components/base/badges/badges'
import { useAuth } from '../features/auth/useAuth'
import { listAnnouncements, listProjectNotifications, markProjectNotificationsRead } from '../features/projects/api'
import type { NotificationCategory, ProjectSummary, UnifiedNotification } from '../features/projects/types'
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
  if (projects.length === 1) {
    const feed = await listProjectNotifications(projects[0].id)
    const seenAt = readSeen(seenKey(userId, projects[0].id))
    return feed.items.map((item) => {
      if (item.source === 'announcement' && new Date(item.created_at).getTime() <= seenAt) {
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
      <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-[#FFFAEB]">
        <span className="flex size-7 items-center justify-center rounded-full bg-[#FEDF89] text-[#B54708]">
          <AlertTriangle className="size-4" />
        </span>
      </span>
    )
  }
  if (category === 'deadline') {
    return (
      <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-[#FFFAEB]">
        <span className="flex size-7 items-center justify-center rounded-full bg-[#FEDF89] text-[#B54708]">
          <Clock className="size-4" />
        </span>
      </span>
    )
  }
  if (category === 'dispute') {
    return (
      <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-[#EFF8FF]">
        <span className="flex size-7 items-center justify-center rounded-full bg-[#B2DDFF] text-[#175CD3]">
          <InfoCircle className="size-4" />
        </span>
      </span>
    )
  }
  if (category === 'qc_pass') {
    return (
      <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-[#ECFDF3]">
        <span className="flex size-7 items-center justify-center rounded-full bg-[#ABEFC6] text-[#067647]">
          <CheckCircle className="size-4" />
        </span>
      </span>
    )
  }
  return (
    <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-[#F9F5FF]">
      <span className="flex size-7 items-center justify-center rounded-full bg-[#E9D7FE] text-[#6941C6]">
        <Bell01 className="size-4" />
      </span>
    </span>
  )
}

/**
 * Chuông thông báo + Drawer trượt phải 440px (Tất cả / Chưa đọc, Đánh dấu đã đọc, TB03).
 */
export default function NotificationBell({ projects }: { projects: ProjectSummary[] }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const userId = user?.id ?? 0
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<'all' | 'unread'>('all')
  const [items, setItems] = useState<UnifiedNotification[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const scopeKey = projects.map((p) => p.id).join(',')

  const load = useCallback(async () => {
    if (!projects.length || !userId) return
    setLoading(true)
    setError(null)
    try {
      const next = await fetchNotifications(projects, userId)
      setItems(next)
    } catch {
      setError('Không tải được thông báo.')
    } finally {
      setLoading(false)
    }
  }, [projects, userId])

  useEffect(() => {
    void load()
    const timer = setInterval(() => void load(), POLL_MS)
    return () => clearInterval(timer)
  }, [scopeKey, load])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  const unreadCount = items.filter((i) => !i.is_read).length
  const visible = tab === 'unread' ? items.filter((i) => !i.is_read) : items

  async function markAllRead() {
    const nowMs = Date.now()
    for (const p of projects) {
      writeSeen(seenKey(userId, p.id), nowMs)
    }
    if (projects.length === 1) {
      try {
        await markProjectNotificationsRead(projects[0].id)
      } catch {
        // fallback optimistic
      }
    }
    setItems((prev) => prev.map((it) => ({ ...it, is_read: true })))
  }

  async function handleItemClick(item: UnifiedNotification) {
    if (!item.is_read && item.notification_id && projects.length === 1) {
      try {
        await markProjectNotificationsRead(projects[0].id, item.notification_id)
      } catch {
        // ignore
      }
    }
    if (item.source === 'announcement' && projects.length === 1) {
      writeSeen(seenKey(userId, projects[0].id), Date.now())
    }
    setItems((prev) => prev.map((it) => (it.id === item.id ? { ...it, is_read: true } : it)))
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
          void load()
        }}
        aria-label={unreadCount ? `Thông báo, ${unreadCount} chưa đọc` : 'Thông báo'}
        className="relative flex size-10 cursor-pointer items-center justify-center rounded-lg text-[#667085] transition hover:bg-[#F9FAFB] hover:text-[#344054]"
      >
        <Bell01 className="size-5" />
        {unreadCount > 0 && (
          <span className="absolute top-1.5 right-1.5 size-2.5 rounded-full bg-[#F04438] ring-2 ring-white" />
        )}
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label="Thông báo">
          <div className="fixed inset-0 bg-[#0C111D]/70 backdrop-blur-[2px]" onClick={() => setOpen(false)} />

          <aside className="relative z-10 flex h-full w-full max-w-[440px] flex-col border-l border-[#EAECF0] bg-white shadow-2xl">
            <div className="flex items-center justify-between px-6 pt-6 pb-4">
              <h2 className="text-xl font-bold text-[#101828]">Thông báo</h2>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={markAllRead}
                  className="inline-flex cursor-pointer items-center gap-1.5 text-sm font-semibold text-[#6941C6] hover:text-[#53389E]"
                >
                  <Check className="size-4" />
                  Đánh dấu đã đọc
                </button>
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  aria-label="Đóng thông báo"
                  className="flex size-8 cursor-pointer items-center justify-center rounded-lg text-[#98A2B3] hover:bg-[#F9FAFB] hover:text-[#475467]"
                >
                  <XClose className="size-5" />
                </button>
              </div>
            </div>

            <div className="flex items-center gap-6 border-b border-[#EAECF0] px-6">
              <button
                type="button"
                onClick={() => setTab('all')}
                className={cx(
                  'relative flex cursor-pointer items-center gap-2 pb-3 text-sm font-semibold transition',
                  tab === 'all' ? 'text-[#6941C6]' : 'text-[#667085] hover:text-[#344054]',
                )}
              >
                Tất cả
                <Badge size="sm" type="pill-color" color={tab === 'all' ? 'brand' : 'gray'}>
                  {items.length}
                </Badge>
                {tab === 'all' && <span className="absolute inset-x-0 bottom-0 h-0.5 bg-[#7F56D9]" />}
              </button>
              <button
                type="button"
                onClick={() => setTab('unread')}
                className={cx(
                  'relative flex cursor-pointer items-center gap-2 pb-3 text-sm font-semibold transition',
                  tab === 'unread' ? 'text-[#6941C6]' : 'text-[#667085] hover:text-[#344054]',
                )}
              >
                Chưa đọc
                <Badge size="sm" type="pill-color" color={tab === 'unread' ? 'brand' : 'gray'}>
                  {unreadCount}
                </Badge>
                {tab === 'unread' && <span className="absolute inset-x-0 bottom-0 h-0.5 bg-[#7F56D9]" />}
              </button>
            </div>

            <div className="flex-1 overflow-y-auto py-2">
              {error && items.length === 0 ? (
                <p className="px-6 py-12 text-center text-sm text-[#B42318]">{error}</p>
              ) : loading && items.length === 0 ? (
                <p className="px-6 py-12 text-center text-sm text-[#667085]">Đang tải…</p>
              ) : visible.length === 0 ? (
                <div className="flex flex-col items-center gap-2 px-6 py-14 text-center">
                  <span className="flex size-10 items-center justify-center rounded-full bg-[#F2F4F7] text-[#667085]">
                    <Bell01 className="size-5" />
                  </span>
                  <p className="text-sm font-semibold text-[#344054]">
                    {tab === 'unread' ? 'Không có thông báo chưa đọc' : 'Chưa có thông báo nào'}
                  </p>
                  <p className="text-xs text-[#667085]">Các thông báo về rework, hạn nộp và phản hồi sẽ hiện ở đây.</p>
                </div>
              ) : (
                <ul className="divide-y divide-[#F2F4F7]">
                  {visible.map((item) => (
                    <li key={item.id}>
                      <button
                        type="button"
                        onClick={() => void handleItemClick(item)}
                        className={cx(
                          'relative flex w-full cursor-pointer gap-3 px-6 py-4 text-left transition hover:bg-[#F9FAFB]',
                          !item.is_read && 'bg-[#FCFAFF]',
                        )}
                      >
                        {!item.is_read && (
                          <span className="absolute top-7 left-2.5 size-2 rounded-full bg-[#7F56D9]" aria-label="Chưa đọc" />
                        )}
                        <CategoryIcon category={item.category} />
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-semibold text-[#101828]">{item.title}</p>
                          {item.body && (
                            <p className="mt-0.5 line-clamp-2 text-sm text-[#475467]">{item.body}</p>
                          )}
                          <time
                            className="mt-1.5 block text-xs text-[#667085]"
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

            <footer className="border-t border-[#EAECF0] px-6 py-4 text-xs text-[#667085]">
              Thông báo chưa xử lý được treo cho tới khi xử lý (TB03).
            </footer>
          </aside>
        </div>
      )}
    </>
  )
}
