import { SearchLg } from '@untitledui/icons'
import { useState } from 'react'
import { Link } from 'react-router'
import { Input } from '@/components/base/input/input'
import { getErrorMessage } from '../../../shared/api/errors'
import RoleBadges from '../../../shared/components/RoleBadges'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useRequest } from '../../../shared/hooks/useRequest'
import { useProject } from '../../projects/projectContext'
import { listLeaderTeams } from './api'
import NoTeamNotice from './NoTeamNotice'
import { cx } from '@/utils/cx'

/** TL-09 Tải công việc theo thành viên. Giao lại job ở Danh sách job (hộp thoại gợi ý người tải thấp nhất). */
export default function TeamWorkloadPage() {
  const { projectId } = useProject()
  const [search, setSearch] = useState('')
  const { data, error, isLoading, retry } = useRequest(`leader-teams:${projectId}`, () => listLeaderTeams(projectId))

  const keyword = search.trim().toLowerCase()
  const rows = (data ?? [])
    .flatMap((team) => team.members.map((m) => ({ team, m })))
    .filter(({ m }) => !keyword || `${m.user.full_name} ${m.user.username}`.toLowerCase().includes(keyword))
    .sort((a, b) => b.m.holding / Math.max(b.m.capacity, 1) - a.m.holding / Math.max(a.m.capacity, 1))

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Tải công việc</h1>
          <p className="mt-1 text-sm text-tertiary">Người tải cao nhất ở trên. Muốn san tải: vào Danh sách job → Giao lại.</p>
        </div>
        <Link to={`/projects/${projectId}/leader/jobs`} className="text-sm font-semibold text-brand-secondary hover:underline">Đi tới Danh sách job →</Link>
      </header>

      {error != null ? (
        <SectionCard><PageState kind="error" description={getErrorMessage(error)} onRetry={retry} /></SectionCard>
      ) : isLoading || !data ? (
        <SectionCard><PageState kind="loading" /></SectionCard>
      ) : data.length === 0 ? (
        <NoTeamNotice />
      ) : (
        <SectionCard title="Tải công việc theo thành viên" bodyClassName="p-0"
          actions={<Input size="sm" className="w-60" icon={SearchLg} aria-label="Tìm kiếm" placeholder="Tìm kiếm" value={search} onChange={setSearch} />}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-secondary text-xs font-semibold text-quaternary">
                <tr>
                  <th className="px-5 py-2.5 text-left">Thành viên</th>
                  <th className="px-3 py-2.5 text-left">Vai trò</th>
                  <th className="w-64 px-3 py-2.5 text-left">Đang giữ / sức chứa</th>
                  <th className="px-3 py-2.5 text-right">Job QC1</th>
                  <th className="px-3 py-2.5 text-right">Sắp deadline</th>
                  <th className="px-5 py-2.5 text-right">Escalated</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ team, m }) => {
                  const percent = Math.round((m.holding * 100) / Math.max(m.capacity, 1))
                  return (
                    <tr key={`${team.id}-${m.user.id}`} className="border-t border-secondary">
                      <td className="px-5 py-3">
                        <div className="font-medium text-primary">{m.user.full_name}</div>
                        <div className="text-xs text-tertiary">{m.user.username}{data.length > 1 ? ` · ${team.name}` : ''}</div>
                      </td>
                      <td className="px-3 py-3"><RoleBadges roles={m.roles} short /></td>
                      <td className="px-3 py-3">
                        <div className="flex items-center gap-3">
                          <div className="h-2 flex-1 rounded-full bg-secondary">
                            <div className={cx('h-full rounded-full', percent > 100 ? 'bg-error-solid' : 'bg-brand-solid')} style={{ width: `${Math.min(percent, 100)}%` }} />
                          </div>
                          <span className={cx('w-12 text-right tabular-nums', percent > 100 ? 'font-semibold text-error-primary' : 'text-secondary')}>{m.holding}/{m.capacity}</span>
                        </div>
                      </td>
                      <td className="px-3 py-3 text-right text-secondary tabular-nums">{m.qc1_holding}</td>
                      <td className={cx('px-3 py-3 text-right tabular-nums', m.due_soon ? 'font-semibold text-warning-primary' : 'text-secondary')}>{m.due_soon}</td>
                      <td className={cx('px-5 py-3 text-right tabular-nums', m.escalated ? 'font-semibold text-error-primary' : 'text-secondary')}>{m.escalated}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </SectionCard>
      )}
    </div>
  )
}
