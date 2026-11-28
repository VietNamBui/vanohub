import dayjs from 'dayjs'
import { useState } from 'react'
import { Badge, Popover } from 'antd'
import { BellOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { useStore } from '../mock/store'
import { notificationsFor } from '../mock/notifications'
function readIds(key: string): string[] {
  try { const value: unknown = JSON.parse(localStorage.getItem(key) ?? '[]'); return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [] } catch { return [] }
}
function UserBell({ userId }: { userId: string }) {
  const s = useStore()
  const key = `cvd-notifications-read:${userId}`
  const [read, setRead] = useState<string[]>(() => readIds(key))
  const [open, setOpen] = useState(false)
  const items = notificationsFor(s, userId)
  const unread = items.filter(n => !read.includes(n.id)).length
  const mark = (ids: string[]) => {
    const next = [...new Set([...read, ...ids])]
    setRead(next)
    try { localStorage.setItem(key, JSON.stringify(next)) } catch { /* In-memory read state remains usable. */ }
  }
  return <Popover trigger="click" placement="bottomRight" open={open} onOpenChange={setOpen} content={<div className="cvd-noti-panel">
    <div className="cvd-noti-head"><b>Thông báo</b><button type="button" onClick={() => mark(items.map(n => n.id))}>Đánh dấu đã đọc</button></div>
    {!items.length && <p>Không có thông báo</p>}
    {[true, false].map(today => {
      const group = items.filter(n => (dayjs(n.at).isSame(dayjs(s.now), 'day')) === today)
      return group.length ? <section key={String(today)}><h3>{today ? 'Hôm nay' : 'Trước đó'}</h3>{group.map(n => <Link className={read.includes(n.id) ? '' : 'cvd-noti-unread'} key={n.id} to={n.link} onClick={() => { mark([n.id]); setOpen(false) }}>{n.title}<time dateTime={n.at}>{dayjs(n.at).format('DD/MM HH:mm')}</time></Link>)}</section> : null
    })}
  </div>}><button type="button" className="cvd-noti-trigger" aria-label={`Thông báo, ${unread} chưa đọc`}><Badge count={unread}><BellOutlined /></Badge></button></Popover>
}
export function NotificationBell() { const { currentUser } = useStore(); return <UserBell key={currentUser.id} userId={currentUser.id} /> }
