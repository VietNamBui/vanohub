import { InfoCircle, SearchLg } from '@untitledui/icons'
import { useState } from 'react'
import { Table } from '@/components/application/table/table'
import { Tabs } from '@/components/application/tabs/tabs'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { Input } from '@/components/base/input/input'
import { ProgressBarBase } from '@/components/base/progress-indicators/progress-indicators'
import { getErrorMessage } from '../../../shared/api/errors'
import EmptyRow from '../../../shared/components/ui/EmptyRow'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatNumber, formatPercent } from '../../../shared/utils/format'
import { getMemberPerformance, getTeamRanking } from '../api'
import { useProject } from '../projectContext'

type TabKey = 'teams' | 'members'
const PAGE_SIZE = 20

/** Xếp hạng team & hiệu suất thành viên trong organization. */
export default function TeamRankingPage() {
  const { project, projectId } = useProject()
  const [tab, setTab] = useState<TabKey>('teams')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const ranking = useRequest(`ranking:${projectId}`, () => getTeamRanking(projectId))
  const members = useRequest(`member-perf:${projectId}`, () => getMemberPerformance(projectId))

  const teamRows = (ranking.data?.rows ?? []).map((r) => ({ ...r, id: r.team.id }))
  const maxObjects = Math.max(1, ...teamRows.map((r) => r.objects_done))

  const keyword = search.trim().toLowerCase()
  const filteredMembers = (members.data ?? [])
    .filter((m) => !keyword || m.user.full_name.toLowerCase().includes(keyword) || m.user.username.toLowerCase().includes(keyword))
    .map((m) => ({ ...m, id: m.user.id }))
  const totalPages = Math.max(1, Math.ceil(filteredMembers.length / PAGE_SIZE))
  const safePage = Math.min(page, totalPages)
  const pagedMembers = filteredMembers.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE)

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 md:p-6">
      <header>
        <h1 className="text-display-xs font-semibold text-primary">Xếp hạng team</h1>
        <p className="mt-1 text-sm text-tertiary">
          So sánh năng suất và chất lượng giữa các team trong organization <span className="font-medium text-secondary">{project.name}</span>.
        </p>
      </header>

      {ranking.data && (
        <div className="flex items-start gap-3 rounded-xl bg-brand-primary_alt p-4 ring-1 ring-brand ring-inset">
          <InfoCircle className="mt-0.5 size-5 shrink-0 text-fg-brand-primary" />
          <p className="text-sm text-secondary">
            <span className="font-semibold">KPI tạm tính:</span> {ranking.data.formula}
          </p>
        </div>
      )}

      <Tabs selectedKey={tab} onSelectionChange={(k) => setTab(k as TabKey)}>
        <Tabs.List type="button-gray" size="sm" aria-label="Chế độ xem xếp hạng">
          <Tabs.Item id="teams" label="Bảng xếp hạng team" badge={teamRows.length || undefined} />
          <Tabs.Item id="members" label="Hiệu suất annotator" badge={members.data?.length || undefined} />
        </Tabs.List>

        <Tabs.Panel id="teams" className="mt-4">
          {ranking.error != null ? (
            <SectionCard>
              <PageState kind="error" description={getErrorMessage(ranking.error)} onRetry={ranking.retry} />
            </SectionCard>
          ) : (
            <div className="grid grid-cols-1 gap-5 xl:grid-cols-12">
              <SectionCard title="Bảng xếp hạng team" className="xl:col-span-8" bodyClassName="p-0">
                <Table aria-label="Bảng xếp hạng team" size="sm">
                  <Table.Header>
                    <Table.Head id="rank" label="Hạng" />
                    <Table.Head id="team" label="Team" isRowHeader />
                    <Table.Head id="members" label="Thành viên" />
                    <Table.Head id="done" label="Job xong" />
                    <Table.Head id="objects" label="Object xong" />
                    <Table.Head id="rework" label="Rework" />
                    <Table.Head id="qc2_errors" label="Lỗi QC2" />
                  </Table.Header>
                  <Table.Body
                    items={teamRows}
                    renderEmptyState={() => <EmptyRow text={ranking.isLoading ? 'Đang tải…' : 'Chưa có team trong organization'} />}
                  >
                    {(r) => (
                      <Table.Row id={r.id}>
                        <Table.Cell>
                          <Badge
                            type="pill-color"
                            size="sm"
                            color={r.rank === 1 ? 'brand' : r.rank <= 3 ? 'blue' : 'gray'}
                          >
                            #{r.rank}
                          </Badge>
                        </Table.Cell>
                        <Table.Cell className="font-medium text-primary">{r.team.name}</Table.Cell>
                        <Table.Cell className="tabular-nums">{r.members}</Table.Cell>
                        <Table.Cell className="tabular-nums">{r.done}/{r.jobs}</Table.Cell>
                        <Table.Cell className="font-medium text-primary tabular-nums">{formatNumber(r.objects_done)}</Table.Cell>
                        <Table.Cell className="tabular-nums">{formatPercent(r.rework_rate)}</Table.Cell>
                        <Table.Cell>
                          {r.qc2_errors > 0 ? (
                            <Badge type="pill-color" size="sm" color="error">{r.qc2_errors}</Badge>
                          ) : (
                            <span className="text-quaternary">0</span>
                          )}
                        </Table.Cell>
                      </Table.Row>
                    )}
                  </Table.Body>
                </Table>
              </SectionCard>

              <SectionCard title="So sánh object đã hoàn thành" className="xl:col-span-4">
                {ranking.isLoading && !ranking.data ? (
                  <PageState kind="loading" />
                ) : teamRows.length === 0 ? (
                  <PageState kind="empty" title="Chưa có dữ liệu team" />
                ) : (
                  <ul className="flex flex-col gap-4">
                    {teamRows.map((r) => (
                      <li key={r.id}>
                        <div className="mb-1.5 flex items-center justify-between gap-2 text-sm">
                          <span className="truncate font-medium text-secondary">{r.team.name}</span>
                          <span className="shrink-0 text-xs font-medium text-primary tabular-nums">
                            {formatNumber(r.objects_done)}
                          </span>
                        </div>
                        <ProgressBarBase value={Math.round((r.objects_done * 100) / maxObjects)} />
                      </li>
                    ))}
                  </ul>
                )}
              </SectionCard>
            </div>
          )}
        </Tabs.Panel>

        <Tabs.Panel id="members" className="mt-4">
          <SectionCard title="Hiệu suất annotator" bodyClassName="p-0">
            <div className="border-b border-secondary p-4">
              <Input
                className="max-w-sm"
                size="sm"
                icon={SearchLg}
                aria-label="Tìm annotator"
                placeholder="Tìm theo tên hoặc tài khoản…"
                value={search}
                onChange={(v) => {
                  setSearch(v)
                  setPage(1)
                }}
              />
            </div>

            {members.error != null ? (
              <PageState kind="error" description={getErrorMessage(members.error)} onRetry={members.retry} />
            ) : (
              <>
                <Table aria-label="Hiệu suất annotator" size="sm">
                  <Table.Header>
                    <Table.Head id="annotator" label="Annotator" isRowHeader />
                    <Table.Head id="jobs" label="Job được giao" />
                    <Table.Head id="done" label="Job xong" />
                    <Table.Head id="objects" label="Object xong" />
                    <Table.Head id="rework" label="Rework" />
                  </Table.Header>
                  <Table.Body
                    items={pagedMembers}
                    renderEmptyState={() => <EmptyRow text={members.isLoading ? 'Đang tải…' : 'Chưa có dữ liệu annotator'} />}
                  >
                    {(r) => (
                      <Table.Row id={r.id}>
                        <Table.Cell>
                          <div className="font-medium text-primary">{r.user.full_name}</div>
                          <div className="font-mono text-xs text-tertiary">{r.user.username}</div>
                        </Table.Cell>
                        <Table.Cell className="tabular-nums">{r.jobs}</Table.Cell>
                        <Table.Cell className="tabular-nums">{r.done}</Table.Cell>
                        <Table.Cell className="font-medium text-primary tabular-nums">{formatNumber(r.objects_done)}</Table.Cell>
                        <Table.Cell className="tabular-nums">{formatPercent(r.rework_rate)}</Table.Cell>
                      </Table.Row>
                    )}
                  </Table.Body>
                </Table>

                {filteredMembers.length > PAGE_SIZE && (
                  <div className="flex items-center justify-between border-t border-secondary px-5 py-3 text-sm text-tertiary">
                    <span>
                      Trang {safePage} / {totalPages} · {filteredMembers.length} annotator
                    </span>
                    <div className="flex gap-2">
                      <Button size="xs" color="secondary" isDisabled={safePage <= 1} onPress={() => setPage((p) => p - 1)}>
                        Trước
                      </Button>
                      <Button size="xs" color="secondary" isDisabled={safePage >= totalPages} onPress={() => setPage((p) => p + 1)}>
                        Sau
                      </Button>
                    </div>
                  </div>
                )}
              </>
            )}
          </SectionCard>
        </Tabs.Panel>
      </Tabs>
    </div>
  )
}
