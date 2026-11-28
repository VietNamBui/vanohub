import { useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { Tabs } from '@/components/application/tabs/tabs'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { Input } from '@/components/base/input/input'
import { Toggle } from '@/components/base/toggle/toggle'
import RoleBadges from '../../shared/components/RoleBadges'
import SectionCard from '../../shared/components/ui/SectionCard'
import { useAction } from '../../shared/hooks/useAction'
import type { Role } from '../../shared/types/roles'
import { changePassword, updateCurrentUser } from '../auth/api'
import type { CurrentUser, UserProjectScope } from '../auth/types'
import { useAuth } from '../auth/useAuth'
import AnnotatorBreadcrumb from '../jobs/components/AnnotatorBreadcrumb'

type SettingsTab = 'profile' | 'security' | 'notifications'

function initialsOf(name?: string) {
  if (!name) return '?'
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

function getFullName(user: CurrentUser | null) {
  return user?.full_name || [user?.first_name, user?.last_name].filter(Boolean).join(' ') || user?.username || ''
}

/** Trang "Cài đặt tài khoản": Hồ sơ, Bảo mật, Thông báo. */
export default function AccountSettingsPage() {
  const { user, setUser } = useAuth()
  const { projectId: projectIdParam } = useParams()
  const projectId = projectIdParam ? Number(projectIdParam) : null
  const [searchParams, setSearchParams] = useSearchParams()
  const rawTab = searchParams.get('tab')
  const tab: SettingsTab =
    rawTab === 'security' || rawTab === 'notifications' || rawTab === 'profile' ? rawTab : 'profile'

  const switchTab = (next: SettingsTab) => {
    setSearchParams({ tab: next }, { replace: true })
  }

  const userSyncKey = `${user?.id ?? 0}:${user?.email ?? ''}:${user?.timezone_name ?? ''}:${user?.avatar_url ?? ''}:${getFullName(user)}`
  const notifSyncKey = `${user?.id ?? 0}:${user?.notify_rework}:${user?.notify_deadline}:${user?.notify_request_updates}:${user?.notify_qc_pass}`

  const userProjects: UserProjectScope[] = user?.projects ?? []
  const scopedProject = projectId !== null ? userProjects.find((p) => p.id === projectId) ?? null : null
  const fallbackRoles = [...new Set((user?.role_assignments ?? []).filter((ra) => projectId === null || ra.project === projectId).map((ra) => ra.role))]
  const scopedRoles: Role[] =
    projectId !== null
      ? scopedProject?.roles ?? fallbackRoles
      : [...new Set(userProjects.length > 0 ? userProjects.flatMap((p) => p.roles) : fallbackRoles)]
  const scopedProjectName =
    scopedProject?.name ||
    (projectId !== null ? user?.role_assignments.find((ra) => ra.project === projectId)?.project_name : '') ||
    ''
  const cvatLinkPath = projectId ? `/projects/${projectId}/cvat-link` : '/cvat-link'

  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-6 px-6 py-7">
      <AnnotatorBreadcrumb projectId={projectId} items={[{ label: 'Cài đặt tài khoản' }]} />

      <header>
        <h1 className="text-display-xs font-semibold text-primary">Cài đặt tài khoản</h1>
        <p className="mt-1 text-sm text-tertiary">Quản lý hồ sơ, bảo mật và tuỳ chọn thông báo.</p>
      </header>

      <Tabs selectedKey={tab} onSelectionChange={(key) => switchTab(key as SettingsTab)}>
        <Tabs.List type="underline" size="sm" aria-label="Cài đặt tài khoản" className="gap-6">
          <Tabs.Item id="profile" label="Hồ sơ" />
          <Tabs.Item id="security" label="Bảo mật" />
          <Tabs.Item id="notifications" label="Thông báo" />
        </Tabs.List>

        <Tabs.Panel id="profile" className="mt-6">
          <ProfileTab
            key={userSyncKey}
            user={user}
            projectId={projectId}
            scopedRoles={scopedRoles}
            scopedProjectName={scopedProjectName}
            userProjects={userProjects}
            cvatLinkPath={cvatLinkPath}
            onSaved={setUser}
          />
        </Tabs.Panel>

        <Tabs.Panel id="security" className="mt-6">
          <SecurityTab />
        </Tabs.Panel>

        <Tabs.Panel id="notifications" className="mt-6">
          <NotificationsTab key={notifSyncKey} user={user} onSaved={setUser} />
        </Tabs.Panel>
      </Tabs>
    </div>
  )
}

function ProfileTab({
  user,
  projectId,
  scopedRoles,
  scopedProjectName,
  userProjects,
  cvatLinkPath,
  onSaved,
}: {
  user: CurrentUser | null
  projectId: number | null
  scopedRoles: Role[]
  scopedProjectName: string
  userProjects: UserProjectScope[]
  cvatLinkPath: string
  onSaved: (u: CurrentUser) => void
}) {
  const { run, pending } = useAction()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const initialName = getFullName(user)

  const [fullName, setFullName] = useState(initialName)
  const [email, setEmail] = useState(user?.email ?? '')
  const [avatarUrl, setAvatarUrl] = useState(user?.avatar_url ?? '')

  function handleAvatarFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result === 'string') setAvatarUrl(reader.result)
    }
    reader.readAsDataURL(file)
  }

  async function saveProfile(e: React.FormEvent) {
    e.preventDefault()
    const updated = await run(
      () =>
        updateCurrentUser({
          full_name: fullName.trim(),
          email: email.trim(),
          avatar_url: avatarUrl,
        }),
      'Đã lưu thay đổi hồ sơ',
    )
    if (updated) onSaved(updated)
  }

  function resetProfile() {
    setFullName(initialName)
    setEmail(user?.email ?? '')
    setAvatarUrl(user?.avatar_url ?? '')
  }

  return (
    <SectionCard title="Hồ sơ cá nhân" description="Cập nhật ảnh đại diện và thông tin liên hệ của bạn.">
      <form onSubmit={saveProfile}>
        <div className="divide-y divide-secondary">
          <div className="grid grid-cols-1 gap-4 py-5 first:pt-1 md:grid-cols-12 md:items-center">
            <label className="text-sm font-semibold text-secondary md:col-span-4">Ảnh đại diện</label>
            <div className="flex items-center gap-4 md:col-span-8">
              <span className="flex size-16 shrink-0 items-center justify-center overflow-hidden rounded-full bg-brand-secondary text-2xl font-bold text-brand-secondary">
                {avatarUrl ? (
                  <img src={avatarUrl} alt={fullName} className="size-full object-cover" />
                ) : (
                  initialsOf(fullName)
                )}
              </span>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={handleAvatarFile}
              />
              <Button color="secondary" size="sm" onPress={() => fileInputRef.current?.click()}>
                Tải ảnh lên
              </Button>
              {avatarUrl && (
                <Button color="tertiary" size="sm" onPress={() => setAvatarUrl('')}>
                  Xoá ảnh
                </Button>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 py-5 md:grid-cols-12 md:items-center">
            <label className="text-sm font-semibold text-secondary md:col-span-4">Họ và tên</label>
            <div className="max-w-[480px] md:col-span-8">
              <Input aria-label="Họ và tên" value={fullName} onChange={setFullName} placeholder="Nhập họ và tên" />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 py-5 md:grid-cols-12 md:items-center">
            <label className="text-sm font-semibold text-secondary md:col-span-4">Email</label>
            <div className="max-w-[480px] md:col-span-8">
              <Input aria-label="Email" type="email" value={email} onChange={setEmail} placeholder="name@vanohub.vn" />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 py-5 md:grid-cols-12 md:items-start">
            <label className="text-sm font-semibold text-secondary md:col-span-4 md:pt-1">Vai trò & CVAT</label>
            <div className="flex flex-col gap-3 md:col-span-8">
              {projectId !== null ? (
                <div className="flex flex-wrap items-center gap-2">
                  <RoleBadges roles={scopedRoles} />
                  {scopedProjectName && <span className="text-sm text-tertiary">{scopedProjectName}</span>}
                </div>
              ) : userProjects.length > 0 ? (
                <ul className="flex flex-col gap-2">
                  {userProjects.map((proj) => (
                    <li key={proj.id} className="flex flex-wrap items-center gap-2">
                      <Link
                        to={`/projects/${proj.id}`}
                        className="text-sm font-medium text-secondary hover:text-brand-secondary hover:underline"
                      >
                        {proj.name}
                      </Link>
                      <RoleBadges roles={proj.roles} />
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="flex flex-wrap items-center gap-2">
                  <RoleBadges roles={scopedRoles} />
                </div>
              )}
              <div className="flex flex-wrap items-center gap-3">
                <Badge size="md" type="pill-color" color={user?.cvat_linked ? 'success' : 'warning'}>
                  {user?.cvat_linked ? `CVAT: ${user.cvat_username}` : 'Chưa liên kết CVAT'}
                </Badge>
                <Link to={cvatLinkPath} className="text-sm font-semibold text-brand-secondary hover:text-brand-secondary_hover hover:underline">
                  Quản lý liên kết CVAT
                </Link>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 py-5 md:grid-cols-12 md:items-center">
            <label className="text-sm font-semibold text-secondary md:col-span-4">Múi giờ</label>
            <div className="flex flex-wrap items-center gap-2 md:col-span-8">
              <Badge size="md" type="pill-color" color="gray">
                (UTC+07:00) Việt Nam · Asia/Ho_Chi_Minh
              </Badge>
              <span className="text-xs text-tertiary">Cố định theo vận hành nội bộ.</span>
            </div>
          </div>
        </div>

        <div className="mt-6 flex items-center justify-end gap-3 border-t border-secondary pt-5">
          <Button color="secondary" size="md" onPress={resetProfile}>
            Hủy
          </Button>
          <Button type="submit" color="primary" size="md" isLoading={pending}>
            Lưu thay đổi
          </Button>
        </div>
      </form>
    </SectionCard>
  )
}

function SecurityTab() {
  const { run, pending } = useAction()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [pwError, setPwError] = useState<string | null>(null)

  async function savePassword(e: React.FormEvent) {
    e.preventDefault()
    if (newPassword.length < 8) {
      setPwError('Mật khẩu mới cần ít nhất 8 ký tự.')
      return
    }
    if (newPassword !== confirmPassword) {
      setPwError('Xác nhận mật khẩu mới không khớp.')
      return
    }
    setPwError(null)
    const ok = await run(
      () => changePassword(currentPassword, newPassword),
      'Đã cập nhật mật khẩu thành công',
    )
    if (ok) {
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    }
  }

  return (
    <SectionCard
      title="Đổi mật khẩu"
      description="Dùng mật khẩu mạnh tối thiểu 8 ký tự để bảo vệ tài khoản làm việc của bạn."
    >
      <form onSubmit={savePassword}>
        <div className="max-w-[520px] space-y-4">
          <Input
            type="password"
            label="Mật khẩu hiện tại"
            value={currentPassword}
            onChange={setCurrentPassword}
            placeholder="Nhập mật khẩu hiện tại"
          />
          <Input
            type="password"
            label="Mật khẩu mới"
            value={newPassword}
            onChange={(v) => {
              setNewPassword(v)
              if (pwError) setPwError(null)
            }}
            placeholder="Tối thiểu 8 ký tự"
          />
          <Input
            type="password"
            label="Xác nhận mật khẩu mới"
            value={confirmPassword}
            onChange={(v) => {
              setConfirmPassword(v)
              if (pwError) setPwError(null)
            }}
            isInvalid={!!pwError}
            hint={pwError ?? undefined}
            placeholder="Nhập lại mật khẩu mới"
          />
        </div>
        <div className="mt-6 flex items-center justify-end gap-3 border-t border-secondary pt-5">
          <Button type="submit" color="primary" size="md" isLoading={pending}>
            Cập nhật mật khẩu
          </Button>
        </div>
      </form>
    </SectionCard>
  )
}

function NotificationsTab({
  user,
  onSaved,
}: {
  user: CurrentUser | null
  onSaved: (u: CurrentUser) => void
}) {
  const { run, pending } = useAction()
  const [notifyRework, setNotifyRework] = useState(user?.notify_rework ?? true)
  const [notifyDeadline, setNotifyDeadline] = useState(user?.notify_deadline ?? true)
  const [notifyRequests, setNotifyRequests] = useState(user?.notify_request_updates ?? true)
  const [notifyQcPass, setNotifyQcPass] = useState(user?.notify_qc_pass ?? true)

  async function saveNotifications(e: React.FormEvent) {
    e.preventDefault()
    const updated = await run(
      () =>
        updateCurrentUser({
          notify_rework: notifyRework,
          notify_deadline: notifyDeadline,
          notify_request_updates: notifyRequests,
          notify_qc_pass: notifyQcPass,
        }),
      'Đã lưu tuỳ chọn thông báo',
    )
    if (updated) onSaved(updated)
  }

  return (
    <SectionCard
      title="Tuỳ chọn thông báo"
      description="Chọn loại thông báo xuất hiện trong ngăn kéo Thông báo."
    >
      <form onSubmit={saveNotifications}>
        <div className="flex flex-col gap-5">
          <Toggle
            size="md"
            isSelected={notifyRework}
            onChange={setNotifyRework}
            label="Job bị trả sửa (Rework)"
            hint="Nhận thông báo ngay khi QC1 hoặc QC2 trả lại lỗi cần sửa."
          />
          <Toggle
            size="md"
            isSelected={notifyDeadline}
            onChange={setNotifyDeadline}
            label="Cảnh báo sắp / quá hạn"
            hint="Nhắc nhở tự động khi job đang giữ còn dưới 24 giờ tới hạn."
          />
          <Toggle
            size="md"
            isSelected={notifyRequests}
            onChange={setNotifyRequests}
            label="Cập nhật phản hồi lỗi & báo dữ liệu"
            hint="Thông báo khi Project Manager tiếp nhận và kết luận yêu cầu của bạn."
          />
          <Toggle
            size="md"
            isSelected={notifyQcPass}
            onChange={setNotifyQcPass}
            label="Job đạt kiểm tra QC1"
            hint="Thông báo khi job vượt qua QC1 và được ghi nhận FPY."
          />
        </div>

        <div className="mt-6 flex items-center justify-end gap-3 border-t border-secondary pt-5">
          <Button type="submit" color="primary" size="md" isLoading={pending}>
            Lưu tuỳ chọn
          </Button>
        </div>
      </form>
    </SectionCard>
  )
}
