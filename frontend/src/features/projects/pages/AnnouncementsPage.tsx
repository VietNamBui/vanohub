import { Send01 } from '@untitledui/icons'
import { useState } from 'react'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { Checkbox } from '@/components/base/checkbox/checkbox'
import { Select } from '@/components/base/select/select'
import { TextArea } from '@/components/base/textarea/textarea'
import { getErrorMessage } from '../../../shared/api/errors'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { ROLE_LABELS, type Role } from '../../../shared/types/roles'
import { formatDateTime } from '../../../shared/utils/format'
import { listTeams } from '../../teams/api'
import { listAnnouncements, sendAnnouncement } from '../api'
import { useProject } from '../projectContext'

const TARGET_ROLES: Role[] = ['project_manager', 'qc2', 'qc1', 'annotator']
const ALL_TEAMS = 0

/** Thông báo của organization: PM có thể soạn gửi theo vai trò/team, thành viên xem lịch sử. */
export default function AnnouncementsPage() {
  const { projectId, can } = useProject()
  const [version, setVersion] = useState(0)
  const [content, setContent] = useState('')
  const [contentError, setContentError] = useState<string | null>(null)
  const [targetRoles, setTargetRoles] = useState<Role[]>([])
  const [targetTeam, setTargetTeam] = useState<number>(ALL_TEAMS)
  const { run, pending } = useAction()
  const { data, error, isLoading, retry } = useRequest(`announcements:${projectId}:${version}`, () =>
    listAnnouncements(projectId),
  )
  const canSend = can('send_announcement')
  const { data: teams } = useRequest(`ann-teams:${projectId}:${canSend ? 1 : 0}`, () =>
    canSend ? listTeams(projectId) : Promise.resolve([]),
  )

  function toggleRole(role: Role, selected: boolean) {
    setTargetRoles((prev) => (selected ? [...new Set([...prev, role])] : prev.filter((r) => r !== role)))
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    const trimmed = content.trim()
    if (!trimmed) {
      setContentError('Nhập nội dung thông báo.')
      return
    }
    const ok = await run(
      () =>
        sendAnnouncement(projectId, {
          content: trimmed,
          target_roles: targetRoles,
          target_team: targetTeam === ALL_TEAMS ? null : targetTeam,
        }),
      'Đã gửi thông báo',
    )
    if (ok) {
      setContent('')
      setContentError(null)
      setTargetRoles([])
      setTargetTeam(ALL_TEAMS)
      setVersion((v) => v + 1)
    }
  }

  const rows = data ?? []

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-5 p-4 md:p-6">
      <header>
        <h1 className="text-display-xs font-semibold text-primary">Thông báo organization</h1>
        <p className="mt-1 text-sm text-tertiary">
          Gửi và theo dõi thông báo theo vai trò hoặc team trong organization.
        </p>
      </header>

      {canSend && (
        <SectionCard title="Gửi thông báo mới">
          <form onSubmit={onSubmit} className="flex flex-col gap-5">
            <TextArea
              label="Nội dung"
              isRequired
              rows={3}
              value={content}
              onChange={(v) => {
                setContent(v)
                if (contentError) setContentError(null)
              }}
              isInvalid={!!contentError}
              hint={contentError ?? undefined}
              placeholder="Nhập thông báo gửi thành viên trong organization…"
            />

            <div className="grid grid-cols-1 gap-5 md:grid-cols-12">
              <div className="flex flex-col gap-2 md:col-span-7">
                <span className="text-sm font-medium text-secondary">Vai trò nhận</span>
                <div className="flex flex-wrap gap-x-5 gap-y-2.5 rounded-lg bg-secondary p-3 ring-1 ring-secondary ring-inset">
                  {TARGET_ROLES.map((role) => (
                    <Checkbox
                      key={role}
                      size="sm"
                      isSelected={targetRoles.includes(role)}
                      onChange={(selected) => toggleRole(role, selected)}
                      label={ROLE_LABELS[role]}
                    />
                  ))}
                </div>
                <span className="text-xs text-tertiary">Bỏ trống nếu muốn gửi tới mọi vai trò trong organization.</span>
              </div>

              <div className="md:col-span-5">
                <Select
                  label="Team nhận (tuỳ chọn)"
                  items={[{ id: ALL_TEAMS, label: 'Tất cả team' }, ...(teams ?? []).map((t) => ({ id: t.id, label: t.name }))]}
                  selectedKey={targetTeam}
                  onSelectionChange={(k) => setTargetTeam(Number(k))}
                >
                  {(item) => <Select.Item id={item.id} label={item.label} />}
                </Select>
              </div>
            </div>

            <div className="flex justify-end">
              <Button type="submit" color="primary" size="md" iconLeading={Send01} isLoading={pending}>
                Gửi thông báo
              </Button>
            </div>
          </form>
        </SectionCard>
      )}

      <SectionCard title="Lịch sử thông báo" bodyClassName="p-0">
        {error != null ? (
          <PageState kind="error" description={getErrorMessage(error)} onRetry={retry} />
        ) : isLoading && !data ? (
          <PageState kind="loading" />
        ) : rows.length === 0 ? (
          <PageState kind="empty" title="Chưa có thông báo" description="Chưa có thông báo nào được gửi trong organization." />
        ) : (
          <ul className="divide-y divide-secondary">
            {rows.map((a) => (
              <li key={a.id} className="flex flex-col gap-2 px-5 py-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-primary">{a.sender?.full_name ?? 'Hệ thống'}</span>
                  <span className="text-xs text-tertiary">{formatDateTime(a.created_at)}</span>
                  <span className="inline-flex flex-wrap gap-1.5">
                    {a.target_roles.length === 0 ? (
                      <Badge type="pill-color" size="sm" color="gray">Mọi vai trò</Badge>
                    ) : (
                      a.target_roles.map((r) => (
                        <Badge key={r} type="pill-color" size="sm" color="brand">{ROLE_LABELS[r]}</Badge>
                      ))
                    )}
                    {a.target_team_name && (
                      <Badge type="pill-color" size="sm" color="blue">{a.target_team_name}</Badge>
                    )}
                  </span>
                </div>
                <p className="text-sm leading-relaxed whitespace-pre-wrap text-secondary">{a.content}</p>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>
    </div>
  )
}
