import type { UserBrief } from '../api/types'

export default function UserName({ user, empty = '—' }: { user: UserBrief | null | undefined; empty?: string }) {
  if (!user) return <span style={{ color: 'rgba(0,0,0,.45)' }}>{empty}</span>
  return <span title={user.username}>{user.full_name}</span>
}
