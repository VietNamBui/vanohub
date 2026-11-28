import { ArrowRight, Edit05, Link03, Plus, RefreshCw01 } from '@untitledui/icons'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { Checkbox } from '@/components/base/checkbox/checkbox'
import { Input } from '@/components/base/input/input'
import { TextArea } from '@/components/base/textarea/textarea'
import { getErrorMessage } from '../../../shared/api/errors'
import type { UserBrief } from '../../../shared/api/types'
import RoleBadges from '../../../shared/components/RoleBadges'
import FormDialog from '../../../shared/components/ui/FormDialog'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { useAuth } from '../../auth/useAuth'
import { createProject, listMembers, listProjects, syncOrganizationsFromCvat, updateProject } from '../api'
import type { ProjectSummary, ProjectsSyncResult } from '../types'

/**
 * Chọn Organization để làm việc (model Project = CVAT organization). Backend chỉ trả về organization trong phạm vi quyền.
 * PM = Owner / Maintainer của CVAT organization (đã liên kết VanoHub) → "Đồng bộ từ CVAT" để kéo về hoặc tạo organization nội bộ.
 */
export default function ProjectListPage() {
  const navigate = useNavigate()
  const { user, refreshUser } = useAuth()
  const isPm = user?.is_pm ?? false
  const [version, setVersion] = useState(0)
  const { data: projects, error, isLoading, retry } = useRequest(`projects:${user?.id ?? 0}:${version}`, listProjects)
  const [syncing, setSyncing] = useState(false)
  const [result, setResult] = useState<ProjectsSyncResult | null>(null)
  const [syncError, setSyncError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<ProjectSummary | null>(null)

  async function reloadWithAuth() {
    setVersion((v) => v + 1)
    try {
      await refreshUser()
    } catch {
      // ignore transient auth refresh error; project list reloads via version bump
    }
  }

  async function sync() {
    setSyncing(true)
    setSyncError(null)
    try {
      setResult(await syncOrganizationsFromCvat())
      await reloadWithAuth()
    } catch (e) {
      setSyncError(getErrorMessage(e))
    } finally {
      setSyncing(false)
    }
  }

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Organization của bạn</h1>
          <p className="mt-1 text-sm text-tertiary">
            Chọn một organization để bắt đầu. Danh sách gồm các organization bạn là thành viên trên VanoHub.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="md" color="secondary" iconLeading={Link03} onPress={() => navigate('/cvat-link')}>
            Liên kết CVAT
          </Button>
          {isPm && (
            <>
              <Button size="md" color="secondary" iconLeading={RefreshCw01} isLoading={syncing} onPress={sync}>
                Đồng bộ từ CVAT
              </Button>
              <Button size="md" color="primary" iconLeading={Plus} onPress={() => setCreating(true)}>
                Tạo organization
              </Button>
            </>
          )}
        </div>
      </header>

      {syncError && (
        <div role="alert" className="rounded-xl bg-error-primary px-4 py-3 text-sm text-error-primary ring-1 ring-error_subtle ring-inset">
          {syncError}
        </div>
      )}
      {result && <SyncSummary result={result} />}

      {error != null ? (
        <SectionCard>
          <PageState kind="error" description={getErrorMessage(error)} onRetry={retry} />
        </SectionCard>
      ) : isLoading && !projects ? (
        <SectionCard>
          <PageState kind="loading" />
        </SectionCard>
      ) : projects?.length === 0 ? (
        <SectionCard>
          <div className="flex flex-col items-center gap-2 px-4 py-14 text-center">
            <p className="text-sm font-semibold text-secondary">Bạn chưa thuộc organization nào</p>
            <p className="max-w-md text-sm text-tertiary">
              {isPm
                ? 'Tạo organization nội bộ hoặc được thêm vào CVAT organization (Owner / Maintainer) → liên kết tài khoản CVAT → bấm “Đồng bộ từ CVAT”.'
                : 'Liên hệ Project Manager để được thêm vào organization, hoặc liên kết tài khoản CVAT nếu bạn đã là thành viên trong CVAT organization.'}
            </p>
            <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
              {isPm && (
                <Button size="md" color="primary" iconLeading={Plus} onPress={() => setCreating(true)}>
                  Tạo organization
                </Button>
              )}
              <Button size="md" color={isPm ? 'secondary' : 'primary'} iconLeading={Link03} onPress={() => navigate('/cvat-link')}>
                Liên kết CVAT ngay
              </Button>
            </div>
          </div>
        </SectionCard>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {projects?.map((project) => {
            const canEditOrg = project.my_roles.includes('project_manager')
            return (
              <article
                key={project.id}
                className="group flex flex-col justify-between gap-4 rounded-2xl bg-primary p-5 shadow-xs ring-1 ring-secondary transition hover:bg-primary_hover hover:ring-brand"
              >
                <Link to={`/projects/${project.id}`} className="flex flex-1 flex-col justify-between gap-3">
                  <div>
                    <div className="flex items-start justify-between gap-2">
                      <h2 className="text-md font-semibold text-primary group-hover:text-brand-secondary">{project.name}</h2>
                      <ArrowRight className="mt-0.5 size-4 shrink-0 text-fg-quaternary transition group-hover:translate-x-0.5 group-hover:text-fg-brand-primary" />
                    </div>
                    <p className="mt-2 line-clamp-2 text-sm text-tertiary">
                      {project.description || 'Không có mô tả'}
                    </p>
                  </div>

                  <div className="flex flex-wrap items-center gap-2 text-xs text-tertiary tabular-nums">
                    <span>
                      {project.done_count}/{project.job_count} job ({project.progress_percent}%)
                    </span>
                    {project.overdue_count > 0 && (
                      <Badge type="pill-color" size="sm" color="warning">
                        {project.overdue_count} quá hạn
                      </Badge>
                    )}
                    {project.escalated_count > 0 && (
                      <Badge type="pill-color" size="sm" color="error">
                        {project.escalated_count} escalated
                      </Badge>
                    )}
                  </div>
                </Link>

                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-secondary pt-3">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <RoleBadges roles={project.my_roles} />
                    <Badge type="pill-color" size="sm" color="gray">
                      {project.cvat_org_id != null ? `CVAT: ${project.cvat_org_slug || `#${project.cvat_org_id}`}` : 'Nội bộ'}
                    </Badge>
                  </div>
                  {canEditOrg && (
                    <Button size="xs" color="link-gray" iconLeading={Edit05} onPress={() => setEditing(project)}>
                      Sửa
                    </Button>
                  )}
                </div>
              </article>
            )
          })}
        </div>
      )}

      {creating && (
        <OrganizationFormDialog
          key="create-org"
          mode="create"
          onClose={() => setCreating(false)}
          onDone={() => {
            setCreating(false)
            void reloadWithAuth()
          }}
        />
      )}

      {editing && (
        <OrganizationFormDialog
          key={`edit-org-${editing.id}`}
          mode="edit"
          project={editing}
          onClose={() => setEditing(null)}
          onDone={() => {
            setEditing(null)
            void reloadWithAuth()
          }}
        />
      )}
    </div>
  )
}

function OrganizationFormDialog({
  mode,
  project,
  onClose,
  onDone,
}: {
  mode: 'create' | 'edit'
  project?: ProjectSummary
  onClose: () => void
  onDone: () => void
}) {
  const initialPmIds = (project?.project_managers ?? []).map((u) => u.id)
  const [name, setName] = useState(project?.name ?? '')
  const [description, setDescription] = useState(project?.description ?? '')
  const [selectedPmIds, setSelectedPmIds] = useState<number[]>(initialPmIds)
  const [showErrors, setShowErrors] = useState(false)
  const { run, pending } = useAction()

  const { data: members } = useRequest(
    mode === 'edit' && project ? `org-edit-members:${project.id}` : 'org-edit-members:none',
    () => (mode === 'edit' && project ? listMembers(project.id) : Promise.resolve([])),
  )

  const candidatePms: UserBrief[] = (() => {
    if (mode !== 'edit' || !project) return []
    const byId = new Map<number, UserBrief>()
    for (const pm of project.project_managers ?? []) byId.set(pm.id, pm)
    for (const m of members ?? []) byId.set(m.user.id, m.user)
    return [...byId.values()]
  })()

  const trimmedName = name.trim()
  const pmSelectionInvalid = mode === 'edit' && candidatePms.length > 0 && selectedPmIds.length === 0

  function togglePm(userId: number, selected: boolean) {
    setSelectedPmIds((prev) => (selected ? [...new Set([...prev, userId])] : prev.filter((id) => id !== userId)))
  }

  async function submit() {
    setShowErrors(true)
    if (!trimmedName || pmSelectionInvalid) return

    if (mode === 'create') {
      const created = await run(
        () => createProject({ name: trimmedName, description: description.trim() }),
        'Đã tạo organization',
      )
      if (created) onDone()
      return
    }

    if (!project) return
    const pmChanged =
      selectedPmIds.length > 0 &&
      ([...selectedPmIds].sort((a, b) => a - b).join(',') !== [...initialPmIds].sort((a, b) => a - b).join(','))
    const updated = await run(
      () =>
        updateProject(project.id, {
          name: trimmedName,
          description: description.trim(),
          ...(pmChanged ? { pm_ids: selectedPmIds } : {}),
        }),
      'Đã cập nhật organization',
    )
    if (updated) onDone()
  }

  return (
    <FormDialog
      isOpen
      title={mode === 'create' ? 'Tạo organization mới' : `Chỉnh sửa ${project?.name ?? 'organization'}`}
      description={
        mode === 'create'
          ? 'Tạo organization nội bộ trên VanoHub (bạn sẽ tự động là Project Manager).'
          : 'Cập nhật tên, mô tả và danh sách Project Manager của organization.'
      }
      submitLabel={mode === 'create' ? 'Tạo organization' : 'Lưu thay đổi'}
      onClose={onClose}
      onSubmit={submit}
      pending={pending}
    >
      <Input
        label="Tên organization"
        size="sm"
        isRequired
        value={name}
        onChange={setName}
        isInvalid={showErrors && !trimmedName}
        hint={showErrors && !trimmedName ? 'Vui lòng nhập tên organization.' : undefined}
        placeholder="VD: Lidar Labeling Team A"
      />
      <TextArea
        label="Mô tả"
        rows={3}
        value={description}
        onChange={setDescription}
        placeholder="Mô tả ngắn về phạm vi công việc…"
      />
      {mode === 'edit' && candidatePms.length > 0 && (
        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium text-secondary">Project Manager phụ trách</span>
          <div className="flex max-h-44 flex-col gap-2 overflow-y-auto rounded-lg bg-secondary p-3 ring-1 ring-secondary ring-inset">
            {candidatePms.map((u) => (
              <Checkbox
                key={u.id}
                size="sm"
                isSelected={selectedPmIds.includes(u.id)}
                onChange={(checked) => togglePm(u.id, checked)}
                label={`${u.full_name} (${u.username})`}
              />
            ))}
          </div>
          {pmSelectionInvalid ? (
            <p className="text-xs text-error-primary">Mỗi organization phải có ít nhất một Project Manager.</p>
          ) : (
            <p className="text-xs text-tertiary">Cần giữ ít nhất một PM. Gỡ PM sẽ thu hồi phiên JWT hiện tại của người bị gỡ.</p>
          )}
        </div>
      )}
    </FormDialog>
  )
}

function SyncSummary({ result }: { result: ProjectsSyncResult }) {
  const nothing = !result.created.length && !result.pm_added.length && !result.members_added.length
  return (
    <div role="status" className="rounded-xl bg-secondary p-4 text-sm text-tertiary ring-1 ring-secondary ring-inset">
      <div className="flex flex-wrap items-center gap-2">
        <p className="font-semibold text-secondary">
          {nothing
            ? 'Không có organization mới.'
            : `Đã thêm ${result.created.length} organization, ${result.pm_added.length} lượt giao PM.`}
        </p>
        {result.members_added.length > 0 && (
          <Badge type="pill-color" size="sm" color="success">
            +{result.members_added.length} thành viên
          </Badge>
        )}
      </div>
      {result.waiting.length > 0 && (
        <>
          <p className="mt-2">CVAT organization chưa đưa lên VanoHub ({result.waiting.length}):</p>
          <ul className="mt-1 list-disc pl-5">
            {result.waiting.map((w) => (
              <li key={w.cvat_org_id}>
                {w.name} — {w.reason}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
