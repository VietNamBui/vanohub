import { ChevronDown, HelpCircle, Key01, Link03, SearchLg, User01 } from '@untitledui/icons'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, Outlet, useMatch, useNavigate } from 'react-router'
import ChangePasswordDialog from '../features/auth/ChangePasswordDialog'
import { useAuth } from '../features/auth/useAuth'
import { listProjects } from '../features/projects/api'
import ProjectSwitcher from '../features/projects/components/ProjectSwitcher'
import { useRequest } from '../shared/hooks/useRequest'
import { ROLE_LABELS, type Role } from '../shared/types/roles'
import NotificationBell from './NotificationBell'
import QuickSearchModal from './QuickSearchModal'
import { ShellContext, type ProjectCapabilitiesState } from './ShellContext'
import SupportCenterDrawer from './SupportCenterDrawer'

function getInitials(name?: string) {
  if (!name) return '?'
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

/**
 * Khung chung sau khi đăng nhập (72px topbar + Quick Search ⌘K + Thông báo Drawer + User Menu).
 */
export default function MainLayout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const projectMatch = useMatch('/projects/:projectId/*')
  const projectId = projectMatch ? Number(projectMatch.params.projectId) : null
  const { data: projects } = useRequest(
    `header-projects:${user?.id ?? 0}:${user?.role_assignments.length ?? 0}`,
    listProjects,
  )
  const scopedProjects = (projects ?? []).filter((p) => projectId === null || p.id === projectId)
  const currentProject = (projects ?? []).find((p) => p.id === projectId) ?? null

  const [searchOpen, setSearchOpen] = useState(false)
  const [supportOpen, setSupportOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [changingPassword, setChangingPassword] = useState(false)
  const [teamLeaderName, setTeamLeaderName] = useState<string | null>(null)
  const [projectCapabilities, setProjectCapabilities] = useState<ProjectCapabilitiesState | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  const displayName =
    user?.full_name || [user?.first_name, user?.last_name].filter(Boolean).join(' ') || user?.username || 'Người dùng'
  const initials = getInitials(displayName)

  const primaryRoleLabel = useMemo(() => {
    const roles: Role[] = scopedProjects.flatMap((p) => p.my_roles)
    const unique = [...new Set(roles)]
    if (unique.length === 0) return 'Thành viên'
    if (unique.length === 1) return ROLE_LABELS[unique[0]]
    return unique.map((r) => ROLE_LABELS[r]).slice(0, 2).join(' · ')
  }, [scopedProjects])

  const settingsPath = projectId ? `/projects/${projectId}/account/settings` : '/account/settings'
  const cvatLinkPath = projectId ? `/projects/${projectId}/cvat-link` : '/cvat-link'

  // Phím tắt toàn cục: ⌘K / Ctrl+K mở tìm kiếm nhanh; Alt+Shift+Q đăng xuất (bỏ qua khi đang gõ).
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setMenuOpen(false)
        setSearchOpen((prev) => !prev)
      } else if (e.altKey && e.shiftKey && e.key.toLowerCase() === 'q') {
        const target = e.target as HTMLElement | null
        const isEditable =
          target != null &&
          (target.tagName === 'INPUT' ||
            target.tagName === 'TEXTAREA' ||
            target.tagName === 'SELECT' ||
            target.isContentEditable)
        if (isEditable) return
        e.preventDefault()
        if (window.confirm('Bạn muốn đăng xuất?')) {
          logout()
        }
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [logout])

  // Đóng menu người dùng khi bấm ra ngoài hoặc nhấn Esc
  useEffect(() => {
    if (!menuOpen) return
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false)
    }
    window.addEventListener('mousedown', onDown)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('mousedown', onDown)
      window.removeEventListener('keydown', onKey)
    }
  }, [menuOpen])

  const shellValue = useMemo(
    () => ({
      projectId,
      projectCapabilities,
      setProjectCapabilities,
      teamLeaderName,
      setTeamLeaderName,
      openSearch: () => setSearchOpen(true),
      openSupport: () => setSupportOpen(true),
    }),
    [projectId, projectCapabilities, teamLeaderName],
  )

  return (
    <ShellContext.Provider value={shellValue}>
      <div className="flex min-h-screen flex-col bg-secondary">
        <header className="sticky top-0 z-30 flex h-[72px] items-center gap-4 border-b border-secondary bg-primary px-6">
          <Link to="/projects" className="flex shrink-0 items-center gap-2.5">
            <span
              className="flex size-8 items-center justify-center rounded-lg shadow-xs"
              style={{ background: 'linear-gradient(135deg, #9E77ED 0%, #6941C6 100%)' }}
            >
              <svg className="size-4 text-white" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="2.1">
                <rect x="2.5" y="2.5" width="13" height="13" rx="2.5" />
                <path d="M6 9h6M9 6v6" strokeLinecap="round" />
              </svg>
            </span>
            <span className="text-xl font-bold tracking-tight text-primary">VanoHub</span>
          </Link>

          {projectId !== null && (
            <div className="hidden sm:block">
              <ProjectSwitcher currentProjectId={projectId} />
            </div>
          )}

          <div className="ml-auto flex items-center gap-3">
            <button
              type="button"
              onClick={() => setSearchOpen(true)}
              className="hidden h-10 w-64 cursor-pointer items-center justify-between rounded-lg border border-primary bg-primary px-3.5 text-sm text-tertiary transition hover:border-secondary md:flex lg:w-80"
            >
              <span className="flex items-center gap-2">
                <SearchLg className="size-4 text-tertiary" />
                <span>Tìm kiếm nhanh</span>
              </span>
              <kbd className="rounded border border-secondary bg-primary px-1.5 py-0.5 text-xs font-medium text-tertiary">
                ⌘K
              </kbd>
            </button>

            <button
              type="button"
              onClick={() => setSearchOpen(true)}
              aria-label="Tìm kiếm nhanh"
              className="flex size-10 cursor-pointer items-center justify-center rounded-lg text-tertiary hover:bg-primary_hover md:hidden"
            >
              <SearchLg className="size-5" />
            </button>

            {scopedProjects.length > 0 && <NotificationBell projects={scopedProjects} />}

            <div className="relative" ref={menuRef}>
              <button
                type="button"
                onClick={() => setMenuOpen((v) => !v)}
                className="flex cursor-pointer items-center gap-3 rounded-lg px-2 py-1.5 transition hover:bg-primary_hover"
              >
                <span className="relative flex size-10 shrink-0 items-center justify-center rounded-full bg-brand-secondary text-sm font-bold text-brand-secondary">
                  {user?.avatar_url ? (
                    <img src={user.avatar_url} alt={displayName} className="size-full rounded-full object-cover" />
                  ) : (
                    initials
                  )}
                  <span className="absolute right-0 bottom-0 size-2.5 rounded-full bg-fg-success-secondary ring-2 ring-white" />
                </span>
                <span className="hidden text-left leading-tight sm:block">
                  <span className="block max-w-36 truncate text-sm font-semibold text-secondary">{displayName}</span>
                  <span className="block max-w-36 truncate text-xs text-tertiary">{primaryRoleLabel}</span>
                </span>
                <ChevronDown className="hidden size-4 text-tertiary sm:block" />
              </button>

              {menuOpen && (
                <div className="absolute right-0 mt-2 w-[264px] overflow-hidden rounded-xl border border-secondary bg-primary shadow-xl">
                  <div className="flex items-center gap-3 border-b border-secondary px-4 py-3">
                    <span className="relative flex size-10 shrink-0 items-center justify-center rounded-full bg-brand-secondary text-sm font-bold text-brand-secondary">
                      {user?.avatar_url ? (
                        <img src={user.avatar_url} alt={displayName} className="size-full rounded-full object-cover" />
                      ) : (
                        initials
                      )}
                      <span className="absolute right-0 bottom-0 size-2.5 rounded-full bg-fg-success-secondary ring-2 ring-white" />
                    </span>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-secondary">{displayName}</p>
                      <p className="truncate text-xs text-tertiary">{user?.email || user?.username}</p>
                    </div>
                  </div>

                  <div className="p-1.5">
                    <MenuButton
                      icon={<User01 className="size-4 text-secondary" />}
                      label="Hồ sơ cá nhân"
                      onClick={() => {
                        setMenuOpen(false)
                        navigate(`${settingsPath}?tab=profile`)
                      }}
                    />
                    <MenuButton
                      icon={<SettingsIcon />}
                      label="Cài đặt tài khoản"
                      onClick={() => {
                        setMenuOpen(false)
                        navigate(settingsPath)
                      }}
                    />
                    <MenuButton
                      icon={<Link03 className="size-4 text-secondary" />}
                      label="Liên kết CVAT"
                      onClick={() => {
                        setMenuOpen(false)
                        navigate(cvatLinkPath)
                      }}
                    />
                    <MenuButton
                      icon={<Key01 className="size-4 text-secondary" />}
                      label="Đổi mật khẩu"
                      onClick={() => {
                        setMenuOpen(false)
                        setChangingPassword(true)
                      }}
                    />
                  </div>

                  <div className="border-t border-secondary p-1.5">
                    <MenuButton
                      icon={<HelpCircle className="size-4 text-secondary" />}
                      label="Trung tâm hỗ trợ"
                      onClick={() => {
                        setMenuOpen(false)
                        setSupportOpen(true)
                      }}
                    />
                    <MenuButton
                      icon={<SearchLg className="size-4 text-secondary" />}
                      label="Tìm kiếm nhanh"
                      shortcut="⌘K"
                      onClick={() => {
                        setMenuOpen(false)
                        setSearchOpen(true)
                      }}
                    />
                    <MenuButton
                      icon={<ProjectsIcon />}
                      label="Organization của tôi"
                      onClick={() => {
                        setMenuOpen(false)
                        navigate('/projects')
                      }}
                    />
                  </div>

                  <div className="border-t border-secondary p-1.5">
                    <MenuButton
                      icon={<LogoutIcon />}
                      label="Đăng xuất"
                      shortcut="⌥⇧Q"
                      onClick={() => {
                        setMenuOpen(false)
                        logout()
                      }}
                    />
                  </div>
                </div>
              )}
            </div>
          </div>
        </header>

        <main className="flex flex-1 flex-col">
          <Outlet />
        </main>

        <QuickSearchModal
          open={searchOpen}
          projectId={projectId}
          currentProject={currentProject}
          onClose={() => setSearchOpen(false)}
        />
        <SupportCenterDrawer
          open={supportOpen}
          projectId={projectId}
          teamLeaderName={teamLeaderName}
          onClose={() => setSupportOpen(false)}
        />
        {changingPassword && <ChangePasswordDialog onClose={() => setChangingPassword(false)} />}
      </div>
    </ShellContext.Provider>
  )
}

function MenuButton({
  icon,
  label,
  shortcut,
  onClick,
}: {
  icon: React.ReactNode
  label: string
  shortcut?: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full cursor-pointer items-center justify-between rounded-lg px-3 py-2 text-sm text-secondary transition hover:bg-primary_hover"
    >
      <span className="flex items-center gap-2.5">
        {icon}
        <span>{label}</span>
      </span>
      {shortcut && <span className="text-xs text-tertiary">{shortcut}</span>}
    </button>
  )
}

function SettingsIcon() {
  return (
    <svg className="size-4 text-secondary" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6">
      <circle cx="10" cy="10" r="2.75" />
      <path d="M10 3.2v1.6M10 15.2v1.6M3.2 10h1.6M15.2 10h1.6M5.2 5.2l1.1 1.1M13.7 13.7l1.1 1.1M14.8 5.2l-1.1 1.1M6.3 13.7l-1.1 1.1" strokeLinecap="round" />
    </svg>
  )
}

function ProjectsIcon() {
  return (
    <svg className="size-4 text-secondary" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M3.5 6.5A1.5 1.5 0 0 1 5 5h3.2l1.5 1.7H15a1.5 1.5 0 0 1 1.5 1.5v6.3A1.5 1.5 0 0 1 15 16H5a1.5 1.5 0 0 1-1.5-1.5v-8Z" />
    </svg>
  )
}

function LogoutIcon() {
  return (
    <svg className="size-4 text-secondary" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M12.5 14.5v1a1.5 1.5 0 0 1-1.5 1.5H5.5A1.5 1.5 0 0 1 4 15.5v-11A1.5 1.5 0 0 1 5.5 3H11a1.5 1.5 0 0 1 1.5 1.5v1" strokeLinecap="round" />
      <path d="M9 10h7.5m0 0-2.5-2.5M16.5 10 14 12.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
