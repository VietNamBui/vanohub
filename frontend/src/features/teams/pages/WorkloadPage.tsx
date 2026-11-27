import { InfoCircle } from '@untitledui/icons'
import { useState } from 'react'
import { Link } from 'react-router'
import { Table } from '@/components/application/table/table'
import { Badge } from '@/components/base/badges/badges'
import { ProgressBarBase } from '@/components/base/progress-indicators/progress-indicators'
import { Select } from '@/components/base/select/select'
import { getErrorMessage } from '../../../shared/api/errors'
import RoleBadges from '../../../shared/components/RoleBadges'
import EmptyRow from '../../../shared/components/ui/EmptyRow'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import StatCard from '../../../shared/components/ui/StatCard'
import { useRequest } from '../../../shared/hooks/useRequest'
import { useProject } from '../../projects/projectContext'
import { getWorkload, listTeams } from '../api'
import type { Workload } from '../types'

const ALL_TEAMS = 0

type WorkloadRow = Workload & { overdue?: number }

/** Tải công việc từng thành viên trong organization. Xếp theo tải thấp nhất trước để chọn người nhận khi giao lại. */
export default function WorkloadPage() {
  const { projectId } = useProject()
  const [team, setTeam] = useState<number>(ALL_TEAMS)
  const { data, error, isLoading, retry } = useRequest(`workload:${projectId}:${team}`, () =>
    getWorkload(projectId, team === ALL_TEAMS ? undefined : team),
  )
  const { data: teams } = useRequest(`teams:${projectId}`, () => listTeams(projectId))

  const rows: WorkloadRow[] = data ?? []
  const overloaded = rows.filter((r) => r.holding > r.capacity).length
  const totalOverdue = rows.reduce((sum, r) => sum + (r.overdue ?? 0), 0)
  const totalEscalated = rows.reduce((sum, r) => sum + r.escalated, 0)
  const loadingInitial = isLoading && !data

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Tải công việc</h1>
          <p className="mt-1 text-sm text-tertiary">
            Số job đang giữ so với sức chứa. Người có mức tải thấp nhất được xếp ở trên cùng.
          </p>
        </div>
        <Select
          className="w-56"
          size="sm"
          aria-label="Lọc theo team"
          items={[{ id: ALL_TEAMS, label: 'Tất cả team' }, ...(teams ?? []).map((t) => ({ id: t.id, label: t.name }))]}
          selectedKey={team}
          onSelectionChange={(k) => setTeam(Number(k))}
        >
          {(item) => <Select.Item id={item.id} label={item.label} />}
        </Select>
      </header>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard value={loadingInitial ? '–' : rows.length} label="Thành viên trong team" />
        <StatCard value={loadingInitial ? '–' : overloaded} label="Quá tải" tone={overloaded > 0 ? 'error' : undefined} />
        <StatCard value={loadingInitial ? '–' : totalOverdue} label="Job quá hạn" tone={totalOverdue > 0 ? 'error' : undefined} />
        <StatCard value={loadingInitial ? '–' : totalEscalated} label="Escalated" tone={totalEscalated > 0 ? 'error' : undefined} />
      </div>

      <div className="flex items-start gap-3 rounded-xl bg-brand-primary_alt p-4 ring-1 ring-brand ring-inset">
        <InfoCircle className="mt-0.5 size-5 shrink-0 text-fg-brand-primary" />
        <p className="text-sm text-secondary">
          Chỉ tính thành viên đã được phân vào team. Giao lại job ở trang Jobs (chọn nhiều job → Giao lại).
        </p>
      </div>

      <SectionCard bodyClassName="p-0">
        {error != null ? (
          <PageState kind="error" description={getErrorMessage(error)} onRetry={retry} />
        ) : (
          <Table aria-label="Bảng tải công việc" size="sm">
            <Table.Header>
              <Table.Head id="member" label="Thành viên" isRowHeader />
              <Table.Head id="team" label="Team" />
              <Table.Head id="roles" label="Vai trò" />
              <Table.Head id="capacity" label="% sức chứa" tooltip="Số job đang annotate / sức chứa tối đa." />
              <Table.Head id="qc1" label="Đang QC1" />
              <Table.Head id="overdue" label="Quá hạn" />
              <Table.Head id="due_soon" label="Sắp hạn (24h)" />
              <Table.Head id="escalated" label="Escalated" />
              <Table.Head id="actions" />
            </Table.Header>
            <Table.Body
              items={rows.map((r) => ({ ...r, id: r.user.id }))}
              renderEmptyState={() => <EmptyRow text={isLoading ? 'Đang tải…' : 'Chưa có thành viên trong team'} />}
            >
              {(r) => {
                const percent = Math.round((r.holding * 100) / Math.max(r.capacity, 1))
                const isOver = r.holding > r.capacity
                const overdue = r.overdue ?? 0
                return (
                  <Table.Row id={r.id}>
                    <Table.Cell>
                      <div className="font-medium text-primary">{r.user.full_name}</div>
                      <div className="font-mono text-xs text-tertiary">{r.user.username}</div>
                    </Table.Cell>
                    <Table.Cell>{r.team.name}</Table.Cell>
                    <Table.Cell><RoleBadges roles={r.roles} /></Table.Cell>
                    <Table.Cell>
                      <div className="flex w-48 items-center gap-3">
                        <ProgressBarBase
                          value={Math.min(100, percent)}
                          progressClassName={isOver ? 'bg-fg-error-primary' : undefined}
                        />
                        <span className={`w-20 shrink-0 text-right text-xs tabular-nums ${isOver ? 'font-semibold text-error-primary' : 'text-tertiary'}`}>
                          {r.holding}/{r.capacity} ({percent}%)
                        </span>
                      </div>
                    </Table.Cell>
                    <Table.Cell className="tabular-nums">{r.qc1_holding}</Table.Cell>
                    <Table.Cell>
                      {overdue > 0 ? (
                        <Badge type="pill-color" size="sm" color="error">{overdue}</Badge>
                      ) : (
                        <span className="text-quaternary">0</span>
                      )}
                    </Table.Cell>
                    <Table.Cell>
                      {r.due_soon > 0 ? (
                        <Badge type="pill-color" size="sm" color="warning">{r.due_soon}</Badge>
                      ) : (
                        <span className="text-quaternary">0</span>
                      )}
                    </Table.Cell>
                    <Table.Cell>
                      {r.escalated > 0 ? (
                        <Badge type="pill-color" size="sm" color="error">{r.escalated}</Badge>
                      ) : (
                        <span className="text-quaternary">0</span>
                      )}
                    </Table.Cell>
                    <Table.Cell className="text-right">
                      <Link
                        to={`../jobs?assignee=${r.user.id}`}
                        relative="path"
                        className="text-sm font-medium text-brand-secondary hover:underline"
                      >
                        Xem job
                      </Link>
                    </Table.Cell>
                  </Table.Row>
                )
              }}
            </Table.Body>
          </Table>
        )}
      </SectionCard>
    </div>
  )
}
