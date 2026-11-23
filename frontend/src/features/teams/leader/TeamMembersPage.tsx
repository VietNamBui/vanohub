import { SearchLg } from '@untitledui/icons'
import { useState } from 'react'
import { Input } from '@/components/base/input/input'
import { Toggle } from '@/components/base/toggle/toggle'
import { getErrorMessage } from '../../../shared/api/errors'
import RoleBadges from '../../../shared/components/RoleBadges'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import StatCard from '../../../shared/components/ui/StatCard'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDate } from '../../../shared/utils/format'
import { useProject } from '../../projects/projectContext'
import { grantQc1, listLeaderTeams, revokeQc1 } from './api'
import NoTeamNotice from './NoTeamNotice'
import type { LeaderMember, LeaderTeam } from './types'
import { cx } from '@/utils/cx'

/** TL-05 Thành viên team: thông tin, vai trò, KPI; Team Leader cấp / thu quyền QC1 cho thành viên. */
export default function TeamMembersPage() {
  const { projectId } = useProject()
  const [version, setVersion] = useState(0)
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<number | null>(null)
  const { data, error, isLoading, retry } = useRequest(`leader-teams:${projectId}:${version}`, () => listLeaderTeams(projectId))

  if (error != null) return <Shell><SectionCard><PageState kind="error" description={getErrorMessage(error)} onRetry={retry} /></SectionCard></Shell>
  if (isLoading || !data) return <Shell><SectionCard><PageState kind="loading" /></SectionCard></Shell>
  if (data.length === 0) return <Shell><NoTeamNotice /></Shell>

  const keyword = search.trim().toLowerCase()
  const entries = data.flatMap((team) => team.members.map((member) => ({ team, member })))
  const shown = entries.filter(({ member: m }) => !keyword || `${m.user.full_name} ${m.user.username}`.toLowerCase().includes(keyword))
  const current = entries.find((e) => e.member.user.id === selected) ?? shown[0]

  return (
    <Shell>
      <div className="grid items-start gap-5 lg:grid-cols-5">
        <SectionCard title="Danh sách thành viên" description={`${entries.length} người`} className="lg:col-span-2" bodyClassName="p-0">
          <div className="border-b border-secondary p-4">
            <Input size="sm" icon={SearchLg} aria-label="Tìm thành viên" placeholder="Tìm thành viên" value={search} onChange={setSearch} />
          </div>
          <ul className="max-h-[560px] overflow-y-auto">
            {shown.map(({ team, member: m }) => (
              <li key={m.user.id}>
                <button
                  type="button"
                  onClick={() => setSelected(m.user.id)}
                  className={cx('flex w-full items-center gap-3 border-b border-secondary px-4 py-3 text-left hover:bg-primary_hover',
                    current?.member.user.id === m.user.id && 'bg-brand-primary_alt')}
                >
                  <Avatar name={m.user.full_name} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-primary">{m.user.full_name}</span>
                    <span className="block truncate text-xs text-tertiary">{m.user.username}{data.length > 1 ? ` · ${team.name}` : ''}</span>
                  </span>
                  <RoleBadges roles={m.roles} short />
                </button>
              </li>
            ))}
            {shown.length === 0 && <li className="px-4 py-8 text-center text-sm text-tertiary">Không có ai khớp tìm kiếm</li>}
          </ul>
        </SectionCard>

        <div className="lg:col-span-3">
          {current && <MemberDetail key={current.member.user.id} projectId={projectId} team={current.team} member={current.member} onChanged={() => setVersion((v) => v + 1)} />}
        </div>
      </div>
    </Shell>
  )
}

function MemberDetail({ projectId, team, member: m, onChanged }: { projectId: number; team: LeaderTeam; member: LeaderMember; onChanged: () => void }) {
  const { run, pending } = useAction()
  const hasQc1 = m.roles.includes('qc1')
  const qc1Direct = m.direct_roles.includes('qc1')
  const qc1Implied = hasQc1 && !qc1Direct
  const percent = Math.round((m.holding * 100) / Math.max(m.capacity, 1))

  async function toggleQc1(on: boolean) {
    const ok = on
      ? await run(() => grantQc1(projectId, team.id, m.user.id), `Đã cấp quyền QC1 cho ${m.user.full_name}`)
      : await run(() => revokeQc1(projectId, team.id, m.user.id), `Đã thu quyền QC1 của ${m.user.full_name}`)
    if (ok) onChanged()
  }

  return (
    <div className="flex flex-col gap-5">
      <SectionCard>
        <div className="flex flex-wrap items-center gap-4">
          <Avatar name={m.user.full_name} large />
          <div className="flex-1">
            <h2 className="text-lg font-semibold text-primary">{m.user.full_name}</h2>
            <p className="text-sm text-tertiary">{m.user.username}</p>
          </div>
          <RoleBadges roles={m.roles} />
        </div>
      </SectionCard>

      <SectionCard title="KPI thành viên">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard value={`${m.jobs_done}/${m.jobs_total}`} label="Job xong / tổng" />
          <StatCard value={m.rework_rate == null ? '—' : `${m.rework_rate}%`} label="Tỷ lệ rework" />
          <StatCard value={`${m.holding}/${m.capacity}`} label="Đang giữ / sức chứa" tone={percent > 100 ? 'error' : undefined} />
          <StatCard value={m.due_soon} label="Sắp deadline (24h)" tone={m.due_soon ? 'error' : undefined} />
        </div>
        <p className="mt-3 text-xs text-tertiary">KPI khoán và tỷ lệ job đúng hạn chưa có công thức — sẽ bổ sung khi chốt.</p>
      </SectionCard>

      <SectionCard title="Thông tin">
        <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
          <Info label="Email" value={m.email || '—'} />
          <Info label="Team" value={team.name} />
          <Info label="Ngày vào team" value={formatDate(m.joined_at)} />
          <Info label="Job QC1 đang giữ" value={String(m.qc1_holding)} />
        </dl>
      </SectionCard>

      <SectionCard title="Quyền QC1" description="Team Leader cấp / thu quyền kiểm tra QC1 cho thành viên trong team.">
        <div className="flex items-start justify-between gap-4">
          <div className="text-sm">
            <p className="font-medium text-secondary">{hasQc1 ? 'Đang có quyền QC1' : 'Chưa có quyền QC1'}</p>
            <p className="mt-0.5 text-tertiary">
              {qc1Implied ? 'QC1 đi kèm vai trò Team Leader — không thu riêng được.'
                : hasQc1 && m.qc1_holding ? `Đang giữ ${m.qc1_holding} job QC1 — nếu còn job chưa QC xong thì phải giao lại trước khi thu quyền.`
                  : 'Bật để người này được nhận job QC1.'}
            </p>
          </div>
          <Toggle aria-label="Quyền QC1" isSelected={hasQc1} isDisabled={pending || qc1Implied} onChange={toggleQc1} />
        </div>
      </SectionCard>

      <div className="rounded-xl border border-dashed border-secondary p-4 text-sm text-tertiary">
        <span className="font-medium text-secondary">Đánh giá thành viên</span> — chưa mở trong phiên bản này.
      </div>
    </div>
  )
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 md:p-6">
      <header>
        <h1 className="text-display-xs font-semibold text-primary">Thành viên team</h1>
        <p className="mt-1 text-sm text-tertiary">Thông tin, vai trò và KPI của thành viên; cấp / thu quyền QC1.</p>
      </header>
      {children}
    </div>
  )
}

function Avatar({ name, large }: { name: string; large?: boolean }) {
  return (
    <span className={cx('flex shrink-0 items-center justify-center rounded-full bg-brand-secondary font-semibold text-brand-secondary', large ? 'size-14 text-lg' : 'size-9 text-xs')}>
      {name.slice(0, 1).toUpperCase()}
    </span>
  )
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-quaternary">{label}</dt>
      <dd className="font-medium text-secondary">{value}</dd>
    </div>
  )
}
