import { ChevronDown, ChevronRight, HelpCircle } from '@untitledui/icons'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Outlet, useLocation, useNavigate, useParams } from 'react-router'
import { useShell } from '../../layouts/ShellContext'
import { getErrorKind, getErrorMessage } from '../../shared/api/errors'
import StateView from '../../shared/components/StateView'
import { useRequest } from '../../shared/hooks/useRequest'
import type { Capability } from '../../shared/types/capabilities'
import { cx } from '@/utils/cx'
import { getProject } from './api'
import { setLastProjectId } from './lastProject'
import { ProjectContext, type ProjectContextValue } from './projectContext'

type NavItem = { key: string; label: string; cap: Capability | Capability[]; matchPrefix?: string }
type NavGroup = {
  key: string
  label: string
  icon: ReactNode
  items: NavItem[]
  /** Nhóm một mục (bấm thẳng để điều hướng thay vì xổ menu con). */
  directKey?: string
  cap?: Capability | Capability[]
}

function BarIcon() {
  return (
    <svg className="size-5 shrink-0" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7">
      <path d="M4.5 15.5v-5M10 15.5v-11M15.5 15.5v-7.5" strokeLinecap="round" />
    </svg>
  )
}

function LayersIcon() {
  return (
    <svg className="size-5 shrink-0" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7">
      <path d="M10 3.5 3 7l7 3.5L17 7l-7-3.5Z" strokeLinejoin="round" />
      <path d="m3 10.5 7 3.5 7-3.5M3 14l7 3.5 7-3.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function BookIcon() {
  return (
    <svg className="size-5 shrink-0" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7">
      <path d="M4 4.5A1.5 1.5 0 0 1 5.5 3h9A1.5 1.5 0 0 1 16 4.5v11a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 4 15.5v-11Z" />
      <path d="M7.5 7h5M7.5 10h5M7.5 13h3" strokeLinecap="round" />
    </svg>
  )
}

function UsersIcon() {
  return (
    <svg className="size-5 shrink-0" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7">
      <circle cx="8" cy="7" r="2.5" />
      <path d="M3.5 16a4.5 4.5 0 0 1 9 0M13.5 6.5a2 2 0 0 1 0 4M14 16a3.5 3.5 0 0 1 3-3.4" strokeLinecap="round" />
    </svg>
  )
}

function ShieldIcon() {
  return (
    <svg className="size-5 shrink-0" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7">
      <path d="M10 3 4.5 5.2v4.6c0 3.7 2.4 6.5 5.5 7.7 3.1-1.2 5.5-4 5.5-7.7V5.2L10 3Z" strokeLinejoin="round" />
    </svg>
  )
}

function GearIcon() {
  return (
    <svg className="size-5 shrink-0" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7">
      <circle cx="10" cy="10" r="2.75" />
      <path d="M10 3.2v1.6M10 15.2v1.6M3.2 10h1.6M15.2 10h1.6M5.2 5.2l1.1 1.1M13.7 13.7l1.1 1.1M14.8 5.2l-1.1 1.1M6.3 13.7l-1.1 1.1" strokeLinecap="round" />
    </svg>
  )
}

/** Menu điều hướng theo 4 vai trò phẳng (PM, QC2, QC1, Annotator) và cấu trúc Organization → Project → Task → Job. */
function buildMenu(can: (cap: Capability) => boolean): NavGroup[] {
  const allowed = (cap: Capability | Capability[]) => (Array.isArray(cap) ? cap.some(can) : can(cap))
  const isAnnotator = can('annotate_jobs')
  const hasManagementOrQc =
    can('view_dashboard') || can('view_jobs') || can('perform_qc1') || can('perform_audit') || can('manage_team')

  const groups: NavGroup[] = []

  // 1. Dashboard
  const dashboardItems: NavItem[] = (
    [
      { key: 'annotator/dashboard', label: 'Tổng quan cá nhân', cap: 'annotate_jobs' },
      { key: 'annotator/analytics', label: 'Phân tích cá nhân', cap: 'annotate_jobs' },
      { key: 'overview', label: 'Tổng quan', cap: 'view_dashboard' },
      { key: 'team-ranking', label: 'Xếp hạng team', cap: 'view_dashboard' },
      { key: 'qc1/dashboard', label: 'Tổng quan QC1', cap: ['perform_qc1', 'view_dashboard'] },
      { key: 'qc2/dashboard', label: 'Tổng quan QC2', cap: 'perform_audit' },
    ] satisfies NavItem[]
  ).filter((i) => allowed(i.cap))

  if (dashboardItems.length > 0) {
    groups.push({ key: 'g-dashboard', label: 'Dashboard', icon: <BarIcon />, items: dashboardItems })
  }

  // 2. Công việc & Vận hành
  const workItems: NavItem[] = (
    [
      { key: 'annotator/jobs', label: 'Job của tôi', cap: 'annotate_jobs', matchPrefix: 'annotator/jobs' },
      { key: 'annotator/rework', label: 'Cần sửa', cap: 'annotate_jobs' },
      {
        key: 'annotator/requests',
        label: can('manage_jobs') && !isAnnotator ? 'Yêu cầu từ Annotator' : 'Yêu cầu của tôi',
        cap: ['annotate_jobs', 'manage_jobs'],
      },
      { key: 'datasets', label: 'Projects', cap: 'view_jobs' },
      { key: 'batches', label: 'Tasks', cap: 'view_jobs' },
      { key: 'jobs', label: 'Jobs', cap: 'view_jobs' },
      { key: 'queue', label: 'Data Queue', cap: 'view_jobs' },
    ] satisfies NavItem[]
  ).filter((i) => allowed(i.cap))

  if (workItems.length > 0) {
    groups.push({
      key: 'g-work',
      label: isAnnotator && !hasManagementOrQc ? 'Công việc' : 'Công việc & Vận hành',
      icon: <LayersIcon />,
      items: workItems,
    })
  }

  // 3. Guidelines (mục trực tiếp cho Annotator thuần)
  if (allowed('view_guidelines') && !hasManagementOrQc) {
    groups.push({
      key: 'guidelines',
      label: 'Guidelines',
      icon: <BookIcon />,
      directKey: 'guidelines',
      items: [],
    })
  }

  // 4. Các nhóm quản lý / QC
  if (hasManagementOrQc) {
    const peopleItems: NavItem[] = (
      [
        { key: 'teams', label: 'Team & Members', cap: 'manage_team' },
        { key: 'workload', label: 'Tải công việc', cap: ['manage_team', 'view_dashboard'] },
      ] satisfies NavItem[]
    ).filter((i) => allowed(i.cap))
    if (peopleItems.length > 0) {
      groups.push({ key: 'g-people', label: 'Nhân sự', icon: <UsersIcon />, items: peopleItems })
    }

    const qualityItems: NavItem[] = (
      [
        { key: 'audits', label: 'Audit QC2 theo task', cap: 'manage_audits' },
        { key: 'qc2/strategy', label: 'Quy tắc QC2', cap: 'manage_audits' },
        { key: 'qc2/work', label: 'Job audit QC2', cap: 'perform_audit' },
        { key: 'qc1/work', label: 'Job kiểm tra QC1', cap: 'perform_qc1' },
        { key: 'error-categories', label: 'Danh mục lỗi', cap: 'manage_quality_catalog' },
        { key: 'guidelines', label: 'Guidelines', cap: 'view_guidelines' },
      ] satisfies NavItem[]
    ).filter((i) => allowed(i.cap))
    if (qualityItems.length > 0) {
      groups.push({ key: 'g-quality', label: 'Chất lượng', icon: <ShieldIcon />, items: qualityItems })
    }
  }

  // 5. Hệ thống & Thông báo — luôn mở cho MỌI vai trò (gồm cả Annotator thuần để liên kết PAT CVAT)
  const extraItems: NavItem[] = (
    [
      { key: 'delivery', label: 'Bàn giao', cap: 'manage_delivery' },
      { key: 'cvat-link', label: 'Liên kết CVAT', cap: 'view_project' },
      { key: 'announcements', label: 'Thông báo', cap: 'view_project' },
    ] satisfies NavItem[]
  ).filter((i) => allowed(i.cap))
  if (extraItems.length > 0) {
    groups.push({ key: 'g-extra', label: 'Cấu hình & Thông báo', icon: <GearIcon />, items: extraItems })
  }

  return groups
}

export default function ProjectLayout() {
  const projectId = Number(useParams().projectId)
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { openSupport, setProjectCapabilities } = useShell()
  const { data: project, error, isLoading, retry } = useRequest(`project:${projectId}`, () => getProject(projectId))
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({
    'g-dashboard': true,
    'g-work': true,
    'g-people': true,
    'g-quality': true,
    'g-extra': true,
  })
  const [mobileOpen, setMobileOpen] = useState(false)

  const context = useMemo<ProjectContextValue | null>(() => {
    if (!project) return null
    const caps = new Set(project.my_capabilities)
    return { project, projectId, can: (cap) => caps.has(cap), reload: retry }
  }, [project, projectId, retry])

  useEffect(() => {
    if (project) {
      setLastProjectId(project.id)
      setProjectCapabilities({ projectId: project.id, capabilities: project.my_capabilities })
    }
    return () => {
      setProjectCapabilities(null)
    }
  }, [project, setProjectCapabilities])

  if (isLoading) return <StateView kind="loading" />
  if (error != null || !context) {
    return getErrorKind(error) === 'not_found' ? (
      <StateView kind="forbidden" title="Không tìm thấy organization hoặc bạn không có quyền truy cập" />
    ) : (
      <StateView kind="error" description={getErrorMessage(error)} action={{ label: 'Thử lại', onClick: retry }} />
    )
  }

  const groups = buildMenu(context.can)
  const base = `/projects/${projectId}/`
  const subPath = pathname.startsWith(base) ? pathname.slice(base.length).replace(/\/$/, '') : ''

  const allKeys = groups.flatMap((g) => (g.directKey ? [g.directKey] : g.items.map((i) => i.key)))
  const selected =
    allKeys
      .filter((key) => subPath === key || subPath.startsWith(`${key}/`))
      .sort((a, b) => b.length - a.length)[0] ?? subPath

  const toggleGroup = (key: string) => setOpenGroups((prev) => ({ ...prev, [key]: !prev[key] }))

  const sidebarContent = (
    <div className="flex h-full flex-col justify-between px-4 py-6">
      <nav aria-label="Điều hướng organization" className="flex flex-col gap-1">
        {groups.map((group) => {
          if (group.directKey) {
            const active = selected === group.directKey
            return (
              <button
                key={group.key}
                type="button"
                onClick={() => {
                  navigate(`${base}${group.directKey}`)
                  setMobileOpen(false)
                }}
                className={cx(
                  'flex w-full cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 text-left text-[15px] font-semibold transition',
                  active ? 'bg-primary_hover text-primary' : 'text-secondary hover:bg-primary_hover',
                )}
              >
                <span className={active ? 'text-secondary' : 'text-tertiary'}>{group.icon}</span>
                <span>{group.label}</span>
              </button>
            )
          }

          const hasActiveChild = group.items.some((i) => i.key === selected)
          const isExpanded = openGroups[group.key] ?? hasActiveChild

          return (
            <div key={group.key} className="flex flex-col">
              <button
                type="button"
                onClick={() => toggleGroup(group.key)}
                className={cx(
                  'flex w-full cursor-pointer items-center justify-between rounded-lg px-3 py-2.5 text-left text-[15px] font-semibold transition hover:bg-primary_hover',
                  hasActiveChild ? 'text-primary' : 'text-secondary',
                )}
              >
                <span className="flex items-center gap-3">
                  <span className={hasActiveChild ? 'text-secondary' : 'text-tertiary'}>{group.icon}</span>
                  <span>{group.label}</span>
                </span>
                {isExpanded ? (
                  <ChevronDown className="size-4 text-quaternary" />
                ) : (
                  <ChevronRight className="size-4 text-quaternary" />
                )}
              </button>

              {isExpanded && (
                <div className="mt-1 flex flex-col gap-0.5">
                  {group.items.map((item) => {
                    const active = selected === item.key
                    return (
                      <button
                        key={item.key}
                        type="button"
                        onClick={() => {
                          navigate(`${base}${item.key}`)
                          setMobileOpen(false)
                        }}
                        className={cx(
                          'w-full cursor-pointer rounded-lg py-2 pr-3 pl-11 text-left text-[15px] transition',
                          active
                            ? 'bg-primary_hover font-semibold text-primary'
                            : 'font-normal text-tertiary hover:bg-primary_hover hover:text-primary',
                        )}
                      >
                        {item.label}
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </nav>

      <div className="mt-6 flex flex-col gap-1 border-t border-secondary pt-4">
        <button
          type="button"
          onClick={() => {
            setMobileOpen(false)
            openSupport()
          }}
          className="flex w-full cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 text-left text-[15px] font-semibold text-secondary transition hover:bg-primary_hover"
        >
          <HelpCircle className="size-5 text-tertiary" />
          <span>Hỗ trợ</span>
        </button>
        <button
          type="button"
          onClick={() => {
            setMobileOpen(false)
            navigate(`${base}account/settings`)
          }}
          className={cx(
            'flex w-full cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 text-left text-[15px] font-semibold transition hover:bg-primary_hover',
            selected === 'account/settings' ? 'bg-primary_hover text-primary' : 'text-secondary',
          )}
        >
          <GearIcon />
          <span>Cài đặt</span>
        </button>
      </div>
    </div>
  )

  return (
    <ProjectContext.Provider value={context}>
      <div className="flex min-h-[calc(100vh-72px)] flex-1">
        <aside className="sticky top-[72px] hidden h-[calc(100vh-72px)] w-[280px] shrink-0 overflow-y-auto border-r border-secondary bg-primary lg:block">
          {sidebarContent}
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center justify-between border-b border-secondary bg-primary px-4 py-2 lg:hidden">
            <button
              type="button"
              onClick={() => setMobileOpen((v) => !v)}
              className="rounded-lg border border-primary px-3 py-1.5 text-sm font-semibold text-secondary"
            >
              {mobileOpen ? 'Đóng menu' : 'Menu'}
            </button>
            <span className="truncate text-sm font-medium text-tertiary">{context.project.name}</span>
          </div>

          {mobileOpen && (
            <div className="border-b border-secondary bg-primary lg:hidden">{sidebarContent}</div>
          )}

          <div className="min-w-0 flex-1">
            <Outlet key={projectId} />
          </div>
        </div>
      </div>
    </ProjectContext.Provider>
  )
}
