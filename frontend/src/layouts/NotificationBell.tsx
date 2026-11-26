import { AlertTriangle, Bell01, Check, CheckCircle, Clock, InfoCircle, XClose } from '@untitledui/icons'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { Badge } from '@/components/base/badges/badges'
import { useAuth } from '../features/auth/useAuth'
import { listProjectNotifications, markProjectNotificationsRead } from '../features/projects/api'
import type { NotificationCategory, ProjectSummary, UnifiedNotification } from '../features/projects/types'
import { useRequest } from '../shared/hooks/useRequest'
import { formatDateTime, formatRelative } from '../shared/utils/format'
import { cx } from '@/utils/cx'

const POLL_MS = 60_000

const seenKey = (userId: number, projectId: number) => `vanohub:notifSeen:${userId}:${projectId}`
const readMapKey = (userId: number) => `vanohub:notifReadIds:${userId}`

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
function readStoredIds(userId: number): Record<string, boolean> {
  if (!userId) return {}
  try {
    const raw = localStorage.getItem(readMapKey(userId))
    const parsed = raw ? (JSON.parse(raw) as unknown) : null
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, boolean>) : {}
  } catch {
    return {}
  }
}
function writeStoredIds(userId: number, map: Record<string, boolean>) {
  if (!userId) return
  try {
    const entries = Object.entries(map).slice(-200)
    localStorage.setItem(readMapKey(userId), JSON.stringify(Object.fromEntries(entries)))
  } catch {
    // ignore storage restriction
  }
}

type ScopedNotification = UnifiedNotification & { _projectId: number }

async function fetchNotifications(projects: ProjectSummary[], userId: number): Promise<ScopedNotification[]> {
  if (!projects.length || !userId) return []
  const multi = projects.length > 1
  const results = await Promise.allSettled(
    projects.map(async (p) => {
      const seenAt = readSeen(seenKey(userId, p.id))
      const feed = await listProjectNotifications(p.id)
      return feed.items.map<ScopedNotification>((item) => {
        const isAnnouncementRead =
          item.source === 'announcement' && new Date(item.created_at).getTime() <= seenAt
        return {
          ...item,
          id: multi ? `${p.id}:${item.id}` : item.id,
          title: multi ? `${p.name} · ${item.title}` : item.title,
          is_read: item.is_read || isAnnouncementRead,
          _projectId: p.id,
        }
      })
    }),
  )
  return results
    .flatMap((r) => (r.status === 'fulfilled' ? r.value : []))
    .sort((a, b) => {
      const ap = !a.is_read && a.is_pinned_pending ? 0 : 1
      const bp = !b.is_read && b.is_pinned_pending ? 0 : 1
      if (ap !== bp) return ap - bp
      return b.created_at.localeCompare(a.created_at)
    })
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
  const [readState, setReadState] = useState<{ userId: number; ids: Record<string, boolean> }>(() => ({
    userId,
    ids: readStoredIds(userId),
  }))
  const readIds = readState.userId === userId ? readState.ids : readStoredIds(userId)
  const scopeKey = projects.map((p) => p.id).join(',')

  const { data, error, isLoading, retry } = useRequest(
    `notif-drawer:${scopeKey}:${userId}`,
    () => fetchNotifications(projects, userId),
  )

  useEffect(() => {
    const timer = setInterval(() => retry(), POLL_MS)
    return () => clearInterval(timer)
  }, [retry])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  const items = (data ?? []).map((item) => (readIds[item.id] ? { ...item, is_read: true } : item))
  const unreadCount = items.filter((i) => !i.is_read).length
  const visible = tab === 'unread' ? items.filter((i) => !i.is_read) : items

  function persistReadIds(next: Record<string, boolean>) {
    setReadState({ userId, ids: next })
    writeStoredIds(userId, next)
  }

  async function markAllRead() {
    const nowMs = new Date().getTime()
    for (const p of projects) {
      writeSeen(seenKey(userId, p.id), nowMs)
    }
    const nextRead: Record<string, boolean> = { ...readIds }
    for (const item of items) nextRead[item.id] = true
    persistReadIds(nextRead)
    await Promise.allSettled(projects.map((p) => markProjectNotificationsRead(p.id)))
  }

  async function handleItemClick(item: ScopedNotification) {
    persistReadIds({ ...readIds, [item.id]: true })
    if (!item.is_read && item.notification_id) {
      try {
        await markProjectNotificationsRead(item._projectId, item.notification_id)
      } catch {
        // ignore
      }
    }
    if (item.source === 'announcement') {
      writeSeen(seenKey(userId, item._projectId), new Date().getTime())
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
          retry()
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
              {error != null && items.length === 0 ? (
                <p className="px-6 py-12 text-center text-sm text-[#B42318]">Không tải được thông báo.</p>
              ) : isLoading && items.length === 0 ? (
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
