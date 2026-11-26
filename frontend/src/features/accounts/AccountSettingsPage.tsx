import { useRef, useState } from 'react'
import { useParams, useSearchParams } from 'react-router'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { Input } from '@/components/base/input/input'
import { NativeSelect } from '@/components/base/select/select-native'
import { Toggle } from '@/components/base/toggle/toggle'
import { useAction } from '../../shared/hooks/useAction'
import { ROLE_LABELS, type Role } from '../../shared/types/roles'
import { cx } from '@/utils/cx'
import { changePassword, updateCurrentUser } from '../auth/api'
import type { CurrentUser } from '../auth/types'
import { useAuth } from '../auth/useAuth'
import ProjectBreadcrumb from '../../shared/components/ui/ProjectBreadcrumb'

type SettingsTab = 'profile' | 'security' | 'notifications'

const TIMEZONE_OPTIONS = [
  { value: 'Asia/Ho_Chi_Minh', label: '(GMT+07:00) Hà Nội' },
  { value: 'Asia/Bangkok', label: '(GMT+07:00) Bangkok' },
  { value: 'Asia/Singapore', label: '(GMT+08:00) Singapore' },
  { value: 'Asia/Tokyo', label: '(GMT+09:00) Tokyo' },
  { value: 'UTC', label: '(GMT+00:00) UTC' },
]

function initialsOf(name?: string) {
  if (!name) return '?'
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

function getFullName(user: CurrentUser | null) {
  return user?.full_name || [user?.first_name, user?.last_name].filter(Boolean).join(' ') || user?.username || ''
}

/** Trang "Cài đặt tài khoản": Hồ sơ (PQ03), Bảo mật, Thông báo. */
export default function AccountSettingsPage() {
  const { user, setUser } = useAuth()
  const { projectId: projectIdParam } = useParams()
  const projectId = projectIdParam ? Number(projectIdParam) : null
  const [searchParams, setSearchParams] = useSearchParams()
  const rawTab = searchParams.get('tab') as SettingsTab | null
  const tab: SettingsTab =
    rawTab && ['profile', 'security', 'notifications'].includes(rawTab) ? rawTab : 'profile'

  const switchTab = (next: SettingsTab) => {
    setSearchParams({ tab: next }, { replace: true })
  }

  const userSyncKey = `${user?.id ?? 0}:${user?.email ?? ''}:${user?.timezone_name ?? ''}:${user?.avatar_url ?? ''}:${getFullName(user)}`
  const notifSyncKey = `${user?.id ?? 0}:${user?.notify_rework}:${user?.notify_deadline}:${user?.notify_request_updates}:${user?.notify_qc_pass}`

  const scopedRoles: Role[] = (user?.role_assignments ?? [])
    .filter((ra) => projectId === null || ra.project === projectId || ra.project === null)
    .map((ra) => ra.role)
  const uniqueRoles = [...new Set(scopedRoles)]
  const primaryRole = uniqueRoles[0] ? ROLE_LABELS[uniqueRoles[0]] : 'Thành viên'
  const scopedProjectName =
    user?.role_assignments.find((ra) => ra.project === projectId)?.project_name ||
    user?.role_assignments.find((ra) => ra.project_name)?.project_name ||
    ''

  return (
    <div className="mx-auto flex max-w-[1160px] flex-col gap-6 px-6 py-7">
      <ProjectBreadcrumb projectId={projectId} items={[{ label: 'Cài đặt tài khoản' }]} />

      <header>
        <h1 className="text-[30px] leading-tight font-bold text-[#101828]">Cài đặt tài khoản</h1>
        <p className="mt-1 text-base text-[#475467]">Quản lý hồ sơ, bảo mật và tuỳ chọn thông báo.</p>
      </header>

      <div className="flex items-center gap-6 border-b border-[#EAECF0]">
        {(
          [
            { id: 'profile', label: 'Hồ sơ' },
            { id: 'security', label: 'Bảo mật' },
            { id: 'notifications', label: 'Thông báo' },
          ] as { id: SettingsTab; label: string }[]
        ).map((item) => {
          const active = tab === item.id
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => switchTab(item.id)}
              className={cx(
                'relative cursor-pointer pb-3 text-sm font-semibold transition',
                active ? 'text-[#6941C6]' : 'text-[#667085] hover:text-[#344054]',
              )}
            >
              {item.label}
              {active && <span className="absolute inset-x-0 bottom-0 h-0.5 bg-[#7F56D9]" />}
            </button>
          )
        })}
      </div>

      {tab === 'profile' && (
        <ProfileTab
          key={userSyncKey}
          user={user}
          primaryRole={primaryRole}
          scopedProjectName={scopedProjectName}
          onSaved={setUser}
        />
      )}

      {tab === 'security' && <SecurityTab />}

      {tab === 'notifications' && (
        <NotificationsTab key={notifSyncKey} user={user} onSaved={setUser} />
      )}
    </div>
  )
}

function ProfileTab({
  user,
  primaryRole,
  scopedProjectName,
  onSaved,
}: {
  user: CurrentUser | null
  primaryRole: string
  scopedProjectName: string
  onSaved: (u: CurrentUser) => void
}) {
  const { run, pending } = useAction()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const initialName = getFullName(user)

  const [fullName, setFullName] = useState(initialName)
  const [email, setEmail] = useState(user?.email ?? '')
  const [avatarUrl, setAvatarUrl] = useState(user?.avatar_url ?? '')
  const [avatarError, setAvatarError] = useState<string | null>(null)
  const [timezoneName, setTimezoneName] = useState(user?.timezone_name || 'Asia/Ho_Chi_Minh')

  function handleAvatarFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (!/^image\/(png|jpeg|webp|gif)$/.test(file.type)) {
      setAvatarError('Chỉ hỗ trợ ảnh PNG, JPG, WEBP hoặc GIF.')
      return
    }
    if (file.size > 350 * 1024) {
      setAvatarError('Ảnh quá lớn (tối đa 350 KB).')
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result === 'string') {
        if (reader.result.length > 500_000) {
          setAvatarError('Ảnh vượt quá kích thước cho phép.')
          return
        }
        setAvatarError(null)
        setAvatarUrl(reader.result)
      }
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
          timezone_name: timezoneName,
        }),
      'Đã lưu thay đổi hồ sơ',
    )
    if (updated) onSaved(updated)
  }

  function resetProfile() {
    setFullName(initialName)
    setEmail(user?.email ?? '')
    setAvatarUrl(user?.avatar_url ?? '')
    setTimezoneName(user?.timezone_name || 'Asia/Ho_Chi_Minh')
  }

  return (
    <form onSubmit={saveProfile} className="rounded-xl border border-[#EAECF0] bg-white p-6">
      <div className="divide-y divide-[#EAECF0]">
        <div className="grid grid-cols-1 gap-4 py-5 first:pt-1 md:grid-cols-12 md:items-center">
          <label className="text-sm font-semibold text-[#344054] md:col-span-4">Ảnh đại diện</label>
          <div className="flex items-center gap-4 md:col-span-8">
            <span className="flex size-16 shrink-0 items-center justify-center overflow-hidden rounded-full bg-[#F4EBFF] text-2xl font-bold text-[#6941C6]">
              {avatarUrl ? (
                <img src={avatarUrl} alt={fullName} className="size-full object-cover" />
              ) : (
                initialsOf(fullName)
              )}
            </span>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp,image/gif"
              className="hidden"
              onChange={handleAvatarFile}
            />
            <Button color="secondary" size="sm" onPress={() => fileInputRef.current?.click()}>
              Tải ảnh lên
            </Button>
            {avatarUrl && (
              <Button
                color="tertiary"
                size="sm"
                onPress={() => {
                  setAvatarError(null)
                  setAvatarUrl('')
                }}
              >
                Xoá ảnh
              </Button>
            )}
          </div>
          {avatarError && <p className="text-xs text-[#D92D20] md:col-span-8 md:col-start-5">{avatarError}</p>}
        </div>

        <div className="grid grid-cols-1 gap-4 py-5 md:grid-cols-12 md:items-center">
          <label className="text-sm font-semibold text-[#344054] md:col-span-4">Họ và tên</label>
          <div className="max-w-[480px] md:col-span-8">
            <Input value={fullName} onChange={setFullName} placeholder="Nhập họ và tên" />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 py-5 md:grid-cols-12 md:items-center">
          <label className="text-sm font-semibold text-[#344054] md:col-span-4">Email</label>
          <div className="max-w-[480px] md:col-span-8">
            <Input type="email" value={email} onChange={setEmail} placeholder="name@annota.vn" />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 py-5 md:grid-cols-12 md:items-center">
          <label className="text-sm font-semibold text-[#344054] md:col-span-4">Vai trò</label>
          <div className="flex flex-wrap items-center gap-3 md:col-span-8">
            <Badge size="md" type="pill-color" color="gray">
              {primaryRole}
            </Badge>
            <span className="text-sm text-[#475467]">
              {[scopedProjectName, 'tài khoản ánh xạ từ CVAT (PQ03)'].filter(Boolean).join(' · ')}
            </span>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 py-5 md:grid-cols-12 md:items-center">
          <label className="text-sm font-semibold text-[#344054] md:col-span-4">Múi giờ</label>
          <div className="max-w-[480px] md:col-span-8">
            <NativeSelect
              value={timezoneName}
              onChange={(e) => setTimezoneName(e.target.value)}
              options={TIMEZONE_OPTIONS}
            />
          </div>
        </div>
      </div>

      <div className="mt-6 flex items-center justify-end gap-3 border-t border-[#EAECF0] pt-5">
        <Button color="secondary" size="md" onPress={resetProfile}>
          Hủy
        </Button>
        <Button type="submit" color="primary" size="md" isLoading={pending}>
          Lưu thay đổi
        </Button>
      </div>
    </form>
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
      () => changePassword({ current_password: currentPassword, new_password: newPassword }),
      'Đã cập nhật mật khẩu thành công',
    )
    if (ok) {
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    }
  }

  return (
    <form onSubmit={savePassword} className="rounded-xl border border-[#EAECF0] bg-white p-6">
      <div className="max-w-[520px] space-y-4">
        <h2 className="text-base font-bold text-[#101828]">Đổi mật khẩu</h2>
        <p className="text-sm text-[#475467]">
          Dùng mật khẩu mạnh tối thiểu 8 ký tự để bảo vệ tài khoản làm việc của bạn.
        </p>
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
      <div className="mt-6 flex items-center justify-end gap-3 border-t border-[#EAECF0] pt-5">
        <Button type="submit" color="primary" size="md" isLoading={pending}>
          Cập nhật mật khẩu
        </Button>
      </div>
    </form>
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
    <form onSubmit={saveNotifications} className="rounded-xl border border-[#EAECF0] bg-white p-6">
      <h2 className="text-base font-bold text-[#101828]">Tuỳ chọn thông báo</h2>
      <p className="mt-1 text-sm text-[#475467]">
        Chọn loại thông báo xuất hiện trong ngăn kéo Thông báo (TB03).
      </p>

      <div className="mt-6 flex flex-col gap-5">
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
          label="Cảnh báo sắp / quá hạn (DH02 · DH04)"
          hint="Nhắc nhở tự động khi job đang giữ còn dưới 24 giờ tới hạn."
        />
        <Toggle
          size="md"
          isSelected={notifyRequests}
          onChange={setNotifyRequests}
          label="Cập nhật phản hồi lỗi & báo dữ liệu"
          hint="Thông báo khi PM tiếp nhận và kết luận yêu cầu của bạn."
        />
        <Toggle
          size="md"
          isSelected={notifyQcPass}
          onChange={setNotifyQcPass}
          label="Job đạt kiểm tra QC1"
          hint="Thông báo khi job vượt qua QC1 và được ghi nhận FPY."
        />
      </div>

      <div className="mt-6 flex items-center justify-end gap-3 border-t border-[#EAECF0] pt-5">
        <Button type="submit" color="primary" size="md" isLoading={pending}>
          Lưu tuỳ chọn
        </Button>
      </div>
    </form>
  )
}
