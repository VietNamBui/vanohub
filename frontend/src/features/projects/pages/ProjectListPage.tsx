import { ArrowRight, Link03, RefreshCw01 } from '@untitledui/icons'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { getErrorMessage } from '../../../shared/api/errors'
import RoleBadges from '../../../shared/components/RoleBadges'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useRequest } from '../../../shared/hooks/useRequest'
import { listProjects, syncOrganizationsFromCvat } from '../api'
import type { ProjectsSyncResult } from '../types'

/**
 * Chọn Organization để làm việc (model Project = CVAT organization). Backend chỉ trả về organization trong phạm vi quyền.
 * PM = Owner / Maintainer của CVAT organization (đã liên kết VanoHub) → "Đồng bộ từ CVAT" để kéo về.
 */
export default function ProjectListPage() {
  const navigate = useNavigate()
  const [version, setVersion] = useState(0)
  const { data: projects, error, isLoading, retry } = useRequest(`projects:${version}`, listProjects)
  const [syncing, setSyncing] = useState(false)
  const [result, setResult] = useState<ProjectsSyncResult | null>(null)
  const [syncError, setSyncError] = useState<string | null>(null)

  async function sync() {
    setSyncing(true)
    setSyncError(null)
    try {
      setResult(await syncOrganizationsFromCvat())
      setVersion((v) => v + 1)
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
            Chọn một organization để bắt đầu. Danh sách lấy theo các CVAT organization bạn là thành viên.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="md" color="secondary" iconLeading={Link03} onPress={() => navigate('/cvat-link')}>
            Liên kết CVAT
          </Button>
          <Button size="md" color="secondary" iconLeading={RefreshCw01} isLoading={syncing} onPress={sync}>
            Đồng bộ từ CVAT
          </Button>
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
              Được thêm vào CVAT organization (PM: vai trò Owner / Maintainer) → liên kết tài khoản CVAT → bấm “Đồng bộ từ CVAT”.
            </p>
            <Button size="md" color="primary" iconLeading={Link03} className="mt-3" onPress={() => navigate('/cvat-link')}>
              Liên kết CVAT ngay
            </Button>
          </div>
        </SectionCard>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {projects?.map((project) => (
            <Link
              key={project.id}
              to={`/projects/${project.id}`}
              className="group flex flex-col justify-between gap-4 rounded-2xl bg-primary p-5 shadow-xs ring-1 ring-secondary transition hover:bg-primary_hover hover:ring-brand"
            >
              <div>
                <div className="flex items-start justify-between gap-2">
                  <h2 className="text-md font-semibold text-primary group-hover:text-brand-secondary">{project.name}</h2>
                  <ArrowRight className="mt-0.5 size-4 shrink-0 text-fg-quaternary transition group-hover:translate-x-0.5 group-hover:text-fg-brand-primary" />
                </div>
                <p className="mt-2 line-clamp-2 text-sm text-tertiary">
                  {project.description || 'Không có mô tả'}
                </p>
              </div>
              <div className="flex items-center justify-between border-t border-secondary pt-3">
                <RoleBadges roles={project.my_roles} />
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
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
