import { AlertOctagon, AlertTriangle, Bell01, Check, CheckCircle, ClipboardCheck, Clock, InfoCircle, UserCheck01, XClose } from '@untitledui/icons'
import { useEffect, useEffectEvent, useState } from 'react'
import { useNavigate } from 'react-router'
import { Tabs } from '@/components/application/tabs/tabs'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { FeaturedIcon } from '@/components/foundations/featured-icon/featured-icon'
import { useAuth } from '../features/auth/useAuth'
import { listProjectNotifications, markProjectNotificationsRead } from '../features/projects/api'
import type { NotificationCategory, ProjectSummary, UnifiedNotification } from '../features/projects/types'
import { formatDateTime, formatRelative } from '../shared/utils/format'
import { cx } from '@/utils/cx'

const POLL_MS = 60_000

interface ScopedNotification extends UnifiedNotification {
  projectId: number
  projectName: string
  scopedKey: string
}

interface FeedState {
  scope: string
  items: ScopedNotification[]
  error: unknown
}

async function fetchNotifications(projects: ProjectSummary[], userId: number): Promise<ScopedNotification[]> {
  if (!projects.length || !userId) return []
  if (projects.length === 1) {
    const project = projects[0]
    const feed = await listProjectNotifications(project.id)
    return feed.items.map((item) => ({
      ...item,
      projectId: project.id,
      projectName: project.name,
      scopedKey: `${project.id}:${item.id}`,
    }))
  }
  const results = await Promise.allSettled(
    projects.map(async (project) => {
      const feed = await listProjectNotifications(project.id)
      return feed.items.map<ScopedNotification>((item) => ({
        ...item,
        projectId: project.id,
        projectName: project.name,
        scopedKey: `${project.id}:${item.id}`,
      }))
    }),
  )
  const fulfilled = results.filter((r): r is PromiseFulfilledResult<ScopedNotification[]> => r.status === 'fulfilled')
  if (fulfilled.length === 0 && results.length > 0) {
    const firstRejected = results.find((r): r is PromiseRejectedResult => r.status === 'rejected')
    throw firstRejected?.reason ?? new Error('Không tải được thông báo.')
  }
  return fulfilled
    .flatMap((r) => r.value)
    .sort((a, b) => {
      if (a.is_pinned_pending !== b.is_pinned_pending) return a.is_pinned_pending ? -1 : 1
      return b.created_at.localeCompare(a.created_at)
    })
}

function CategoryIcon({ category }: { category: NotificationCategory }) {
  if (category === 'escalated') {
    return <FeaturedIcon icon={AlertOctagon} color="error" theme="light" size="md" />
  }
  if (category === 'rework') {
    return <FeaturedIcon icon={AlertTriangle} color="warning" theme="light" size="md" />
  }
  if (category === 'deadline') {
    return <FeaturedIcon icon={Clock} color="warning" theme="light" size="md" />
  }
  if (category === 'assigned') {
    return <FeaturedIcon icon={UserCheck01} color="brand" theme="light" size="md" />
  }
  if (category === 'review_needed') {
    return <FeaturedIcon icon={ClipboardCheck} color="brand" theme="light" size="md" />
  }
  if (category === 'dispute') {
    return <FeaturedIcon icon={InfoCircle} color="brand" theme="light" size="md" />
  }
  if (category === 'qc_pass') {
    return <FeaturedIcon icon={CheckCircle} color="success" theme="light" size="md" />
  }
  return <FeaturedIcon icon={Bell01} color="brand" theme="light" size="md" />
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
  const [refreshTick, setRefreshTick] = useState(0)
  const [feed, setFeed] = useState<FeedState>({ scope: '', items: [], error: null })
  const scopeKey = projects.map((p) => p.id).join(',')
  const fullScope = `${scopeKey}:${userId}`
  const multiProject = projects.length > 1

  const loadFeed = useEffectEvent(() => fetchNotifications(projects, userId))

  useEffect(() => {
    let ignore = false
    loadFeed().then(
      (items) => {
        if (!ignore) setFeed({ scope: fullScope, items, error: null })
      },
      (error: unknown) => {
        if (!ignore) {
          setFeed((prev) =>
            prev.scope === fullScope ? { ...prev, error } : { scope: fullScope, items: [], error },
          )
        }
      },
    )
    return () => {
      ignore = true
    }
  }, [fullScope, refreshTick])

  useEffect(() => {
    const timer = setInterval(() => setRefreshTick((t) => t + 1), POLL_MS)
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

  const isLoading = feed.scope !== fullScope
  const error = feed.scope === fullScope ? feed.error : null
  const items = feed.scope === fullScope ? feed.items : []
  const unreadCount = items.filter((i) => !i.is_read).length
  const visible = tab === 'unread' ? items.filter((i) => !i.is_read) : items

  async function markAllRead() {
    setFeed((prev) => ({
      ...prev,
      items: prev.items.map((item) => (item.is_pinned_pending ? item : { ...item, is_read: true })),
    }))
    try {
      await Promise.allSettled(projects.map((p) => markProjectNotificationsRead(p.id)))
    } catch {
      // ignore optimistic failure
    }
  }

  async function handleItemClick(item: ScopedNotification) {
    if (!item.is_pinned_pending && !item.is_read) {
      setFeed((prev) => ({
        ...prev,
        items: prev.items.map((it) => (it.scopedKey === item.scopedKey ? { ...it, is_read: true } : it)),
      }))
      try {
        await markProjectNotificationsRead(item.projectId, item.id)
      } catch {
        // ignore optimistic failure
      }
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
          setRefreshTick((t) => t + 1)
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
              <h2 className="text-xl font-semibold text-primary">Thông báo</h2>
              <div className="flex items-center gap-2">
                <Button
                  color="link-color"
                  size="sm"
                  iconLeading={Check}
                  onPress={() => void markAllRead()}
                >
                  Đánh dấu đã đọc
                </Button>
                <Button
                  color="tertiary"
                  size="xs"
                  iconLeading={XClose}
                  aria-label="Đóng thông báo"
                  onPress={() => setOpen(false)}
                />
              </div>
            </div>

            <Tabs selectedKey={tab} onSelectionChange={(key) => setTab(key as 'all' | 'unread')}>
              <Tabs.List type="underline" size="sm" aria-label="Bộ lọc thông báo" className="gap-6 px-6">
                <Tabs.Item id="all">
                  {({ isSelected }) => (
                    <>
                      Tất cả
                      <Badge size="sm" type="pill-color" color={isSelected ? 'brand' : 'gray'}>
                        {items.length}
                      </Badge>
                    </>
                  )}
                </Tabs.Item>
                <Tabs.Item id="unread">
                  {({ isSelected }) => (
                    <>
                      Chưa đọc
                      <Badge size="sm" type="pill-color" color={isSelected ? 'brand' : 'gray'}>
                        {unreadCount}
                      </Badge>
                    </>
                  )}
                </Tabs.Item>
              </Tabs.List>
            </Tabs>

            <div className="flex-1 overflow-y-auto py-2">
              {error != null && items.length === 0 ? (
                <p className="px-6 py-12 text-center text-sm text-error-primary">Không tải được thông báo.</p>
              ) : isLoading && items.length === 0 ? (
                <p className="px-6 py-12 text-center text-sm text-tertiary">Đang tải…</p>
              ) : visible.length === 0 ? (
                <div className="flex flex-col items-center gap-2 px-6 py-14 text-center">
                  <FeaturedIcon icon={Bell01} color="gray" theme="light" size="md" />
                  <p className="text-sm font-semibold text-secondary">
                    {tab === 'unread' ? 'Không có thông báo chưa đọc' : 'Chưa có thông báo nào'}
                  </p>
                  <p className="text-xs text-tertiary">Các thông báo của organization về rework, hạn nộp và phản hồi sẽ hiện ở đây.</p>
                </div>
              ) : (
                <ul className="divide-y divide-secondary">
                  {visible.map((item) => (
                    <li key={item.scopedKey}>
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
                            <p className="text-sm font-semibold text-primary">
                              {multiProject ? `${item.projectName} · ${item.title}` : item.title}
                            </p>
                            {item.is_pinned_pending && (
                              <Badge size="sm" type="pill-color" color={item.category === 'escalated' ? 'error' : 'warning'}>
                                {item.category === 'escalated' ? 'Escalated' : 'Cần xử lý'}
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
