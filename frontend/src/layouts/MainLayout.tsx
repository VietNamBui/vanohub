import { ChevronDown, Folder, HelpCircle, Key01, Link03, LogOut01, SearchLg, Settings01, User01 } from '@untitledui/icons'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, Outlet, useMatch, useNavigate } from 'react-router'
import ChangePasswordDialog from '../features/auth/ChangePasswordDialog'
import { useAuth } from '../features/auth/useAuth'
import { listProjects } from '../features/projects/api'
import ProjectSwitcher from '../features/projects/components/ProjectSwitcher'
import RoleBadges from '../shared/components/RoleBadges'
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
    `header-projects:${user?.id ?? 0}:${user?.role_assignments.length ?? 0}:${projectId ?? 'all'}`,
    listProjects,
  )
  const scopedProjects = useMemo(
    () => (projects ?? []).filter((p) => projectId === null || p.id === projectId),
    [projects, projectId],
  )
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

  const scopedRoles = useMemo<Role[]>(
    () => [...new Set(scopedProjects.flatMap((p) => p.my_roles))],
    [scopedProjects],
  )

  const primaryRoleLabel = useMemo(() => {
    if (scopedRoles.length === 0) return 'Thành viên'
    if (scopedRoles.length === 1) return ROLE_LABELS[scopedRoles[0]]
    return scopedRoles.map((r) => ROLE_LABELS[r]).slice(0, 2).join(' · ')
  }, [scopedRoles])

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
            <svg viewBox="0 0 32 32" className="size-8 rounded-lg bg-brand-solid shadow-xs" aria-hidden>
              <path d="M16 7.5 24 12v8l-8 4.5L8 20v-8z" fill="none" stroke="white" strokeWidth="1.8" strokeLinejoin="round" />
              <path d="M8 12l8 4.5 8-4.5M16 16.5v8" fill="none" stroke="white" strokeWidth="1.8" strokeLinejoin="round" opacity=".7" />
            </svg>
            <span className="text-lg font-semibold tracking-tight text-primary">VanoHub</span>
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
              className="hidden h-10 w-64 cursor-pointer items-center justify-between rounded-lg border border-primary bg-primary px-3.5 text-sm text-tertiary shadow-xs transition hover:bg-primary_hover hover:text-secondary md:flex lg:w-80"
            >
              <span className="flex items-center gap-2">
                <SearchLg className="size-4 text-fg-quaternary" />
                <span>Tìm kiếm nhanh</span>
              </span>
              <kbd className="rounded border border-secondary bg-secondary px-1.5 py-0.5 text-xs font-medium text-tertiary">
                ⌘K
              </kbd>
            </button>

            <button
              type="button"
              onClick={() => setSearchOpen(true)}
              aria-label="Tìm kiếm nhanh"
              className="flex size-10 cursor-pointer items-center justify-center rounded-lg text-fg-tertiary transition hover:bg-primary_hover hover:text-fg-secondary md:hidden"
            >
              <SearchLg className="size-5" />
            </button>

            {scopedProjects.length > 0 && <NotificationBell projects={scopedProjects} />}

            {scopedRoles.length > 0 && (
              <div className="hidden items-center lg:flex">
                <RoleBadges roles={scopedRoles} short />
              </div>
            )}

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
                      icon={<User01 className="size-4 text-fg-secondary" />}
                      label="Hồ sơ cá nhân"
                      onClick={() => {
                        setMenuOpen(false)
                        navigate(`${settingsPath}?tab=profile`)
                      }}
                    />
                    <MenuButton
                      icon={<Settings01 className="size-4 text-fg-secondary" />}
                      label="Cài đặt tài khoản"
                      onClick={() => {
                        setMenuOpen(false)
                        navigate(settingsPath)
                      }}
                    />
                    <MenuButton
                      icon={<Link03 className="size-4 text-fg-secondary" />}
                      label="Liên kết CVAT"
                      onClick={() => {
                        setMenuOpen(false)
                        navigate(cvatLinkPath)
                      }}
                    />
                    <MenuButton
                      icon={<Key01 className="size-4 text-fg-secondary" />}
                      label="Đổi mật khẩu"
                      onClick={() => {
                        setMenuOpen(false)
                        setChangingPassword(true)
                      }}
                    />
                  </div>

                  <div className="border-t border-secondary p-1.5">
                    <MenuButton
                      icon={<HelpCircle className="size-4 text-fg-secondary" />}
                      label="Trung tâm hỗ trợ"
                      onClick={() => {
                        setMenuOpen(false)
                        setSupportOpen(true)
                      }}
                    />
                    <MenuButton
                      icon={<SearchLg className="size-4 text-fg-secondary" />}
                      label="Tìm kiếm nhanh"
                      shortcut="⌘K"
                      onClick={() => {
                        setMenuOpen(false)
                        setSearchOpen(true)
                      }}
                    />
                    <MenuButton
                      icon={<Folder className="size-4 text-fg-secondary" />}
                      label="Organization của tôi"
                      onClick={() => {
                        setMenuOpen(false)
                        navigate('/projects')
                      }}
                    />
                  </div>

                  <div className="border-t border-secondary p-1.5">
                    <MenuButton
                      icon={<LogOut01 className="size-4 text-fg-secondary" />}
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
