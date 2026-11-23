import { AlertCircle, ArrowRight, Eye, EyeOff, Lock01, User01 } from '@untitledui/icons'
import { isAxiosError } from 'axios'
import { useState, type FormEvent } from 'react'
import { Button as AriaButton } from 'react-aria-components'
import { Navigate, useLocation, useNavigate } from 'react-router'
import { Button } from '@/components/base/buttons/button'
import { Input } from '@/components/base/input/input'
import { getErrorMessage } from '../../shared/api/errors'
import { useAuth } from './useAuth'

export default function LoginPage() {
  const { status, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/'
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [triedSubmit, setTriedSubmit] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  if (status === 'authenticated') return <Navigate to={from} replace />

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setTriedSubmit(true)
    if (!username.trim() || !password) {
      setError('Vui lòng nhập tên đăng nhập và mật khẩu.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await login(username.trim(), password)
      navigate(from, { replace: true })
    } catch (err) {
      setError(isAxiosError(err) && err.response?.status === 401 ? 'Sai tên đăng nhập hoặc mật khẩu.' : getErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-dvh bg-primary">
      {/* Cột trái: form */}
      <main className="flex flex-1 flex-col px-4 py-8 sm:px-8 lg:px-16">
        <Logo />

        <div className="flex flex-1 items-center justify-center py-12">
          <div className="w-full max-w-sm">
            <h1 className="text-display-sm font-semibold text-primary">Chào mừng trở lại</h1>
            <p className="mt-3 text-md text-tertiary">Đăng nhập để quản lý dự án gán nhãn của bạn.</p>

            <form className="mt-8 flex flex-col gap-5" onSubmit={handleSubmit} noValidate>
              <Input
                label="Tên đăng nhập"
                placeholder="Nhập tên đăng nhập"
                icon={User01}
                autoComplete="username"
                autoFocus
                value={username}
                onChange={setUsername}
                isInvalid={triedSubmit && !username.trim()}
              />

              <div className="relative">
                <Input
                  label="Mật khẩu"
                  placeholder="Nhập mật khẩu"
                  icon={Lock01}
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  value={password}
                  onChange={setPassword}
                  inputClassName="pr-11"
                />
                <AriaButton
                  aria-label={showPassword ? 'Ẩn mật khẩu' : 'Hiện mật khẩu'}
                  onPress={() => setShowPassword((v) => !v)}
                  className="absolute right-1.5 bottom-1.5 flex size-8 cursor-pointer items-center justify-center rounded-md text-fg-quaternary outline-focus-ring transition duration-100 hover:bg-primary_hover hover:text-fg-quaternary_hover focus-visible:outline-2"
                >
                  {showPassword ? <EyeOff className="size-4.5" /> : <Eye className="size-4.5" />}
                </AriaButton>
              </div>

              {error && (
                <div role="alert" className="flex items-start gap-3 rounded-xl bg-error-primary p-3.5 ring-1 ring-error_subtle ring-inset">
                  <AlertCircle className="mt-0.5 size-5 shrink-0 text-fg-error-primary" />
                  <p className="text-sm font-medium text-error-primary">{error}</p>
                </div>
              )}

              <Button type="submit" size="lg" className="mt-1 w-full" isLoading={submitting} showTextWhileLoading iconTrailing={ArrowRight}>
                Đăng nhập
              </Button>
            </form>

            <p className="mt-8 text-center text-sm text-tertiary">
              Chưa có tài khoản? Liên hệ <span className="font-semibold text-secondary">Director</span> của bạn để được cấp quyền.
            </p>
          </div>
        </div>

        <footer className="text-sm text-quaternary">© {new Date().getFullYear()} VanoHub</footer>
      </main>

      {/* Cột phải: thông điệp + hình minh hoạ dashboard (ẩn trên màn hình nhỏ) */}
      <aside className="relative hidden flex-1 overflow-hidden bg-brand-section lg:flex lg:flex-col">
        <div aria-hidden className="pointer-events-none absolute -top-40 -right-40 size-[480px] rounded-full bg-brand-solid opacity-40 blur-3xl" />
        <div aria-hidden className="pointer-events-none absolute -bottom-48 -left-32 size-[420px] rounded-full bg-brand-solid_hover opacity-30 blur-3xl" />

        <div className="relative px-16 pt-24 xl:px-24 xl:pt-32">
          <p className="text-sm font-semibold tracking-wide text-tertiary_on-brand uppercase">Annotation Project Management</p>
          <h2 className="mt-4 max-w-lg text-display-md font-semibold text-primary_on-brand">
            Điều phối toàn bộ luồng gán nhãn ở một nơi.
          </h2>
        </div>

        <DashboardIllustration />
      </aside>
    </div>
  )
}

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <svg viewBox="0 0 32 32" className="size-8 rounded-lg bg-brand-solid" aria-hidden>
        {/* Hình khối cuboid — gợi ý annotation 3D */}
        <path d="M16 7.5 24 12v8l-8 4.5L8 20v-8z" fill="none" stroke="white" strokeWidth="1.8" strokeLinejoin="round" />
        <path d="M8 12l8 4.5 8-4.5M16 16.5v8" fill="none" stroke="white" strokeWidth="1.8" strokeLinejoin="round" opacity=".7" />
      </svg>
      <span className="text-lg font-semibold text-primary">VanoHub</span>
    </div>
  )
}

/**
 * Hình minh hoạ (thuần trang trí, không phải số liệu thật): một cửa sổ dashboard quản lý
 * với menu, ô KPI, biểu đồ cột, bảng tiến độ team — gợi ý đây là platform quản lý.
 */
function DashboardIllustration() {
  const bars = [38, 56, 44, 70, 62, 84, 76, 92]
  const teams = [
    { width: '78%', tone: 'bg-white/70' },
    { width: '54%', tone: 'bg-white/55' },
    { width: '91%', tone: 'bg-success-solid' },
    { width: '36%', tone: 'bg-warning-solid' },
  ]
  return (
    <div aria-hidden className="pointer-events-none relative mt-14 flex-1 select-none">
      {/* Cửa sổ chính, tràn ra mép phải/dưới */}
      <div className="absolute top-0 left-16 w-[960px] rounded-tl-2xl bg-white/10 p-3 shadow-2xl ring-1 ring-white/20 backdrop-blur-md xl:left-24">
        <div className="mb-3 flex gap-1.5 px-1">
          <span className="size-2.5 rounded-full bg-white/30" />
          <span className="size-2.5 rounded-full bg-white/30" />
          <span className="size-2.5 rounded-full bg-white/30" />
        </div>
        <div className="flex gap-3">
          {/* Sidebar */}
          <div className="flex w-36 shrink-0 flex-col gap-2.5 rounded-xl bg-white/8 p-3">
            <div className="mb-1 h-3 w-20 rounded-full bg-white/50" />
            {[70, 55, 80, 60, 50, 65].map((w, i) => (
              <div key={i} className={`h-2.5 rounded-full ${i === 1 ? 'bg-white/60' : 'bg-white/20'}`} style={{ width: `${w}%` }} />
            ))}
          </div>
          {/* Nội dung */}
          <div className="flex flex-1 flex-col gap-3">
            <div className="grid grid-cols-3 gap-3">
              {[0, 1, 2].map((i) => (
                <div key={i} className="rounded-xl bg-white/12 p-3.5">
                  <div className="h-2 w-14 rounded-full bg-white/30" />
                  <div className="mt-3 h-4 w-20 rounded-md bg-white/70" />
                  <div className="mt-3 h-1.5 w-full rounded-full bg-white/15">
                    <div className="h-full rounded-full bg-white/60" style={{ width: `${[72, 48, 88][i]}%` }} />
                  </div>
                </div>
              ))}
            </div>
            <div className="flex gap-3">
              {/* Biểu đồ cột */}
              <div className="flex-[1.4] rounded-xl bg-white/12 p-4">
                <div className="h-2.5 w-24 rounded-full bg-white/40" />
                <div className="mt-4 flex h-36 items-end gap-2.5">
                  {bars.map((h, i) => (
                    <div key={i} className="flex-1 rounded-t-md bg-white/25" style={{ height: `${h}%` }}>
                      <div className="h-1/3 rounded-t-md bg-white/50" />
                    </div>
                  ))}
                </div>
              </div>
              {/* Tiến độ team */}
              <div className="flex flex-1 flex-col gap-3.5 rounded-xl bg-white/12 p-4">
                <div className="h-2.5 w-20 rounded-full bg-white/40" />
                {teams.map((t, i) => (
                  <div key={i} className="flex items-center gap-2.5">
                    <span className="size-6 shrink-0 rounded-full bg-white/30 ring-2 ring-white/10" />
                    <div className="h-2 flex-1 rounded-full bg-white/15">
                      <div className={`h-full rounded-full ${t.tone}`} style={{ width: t.width }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
            {/* Bảng job */}
            <div className="rounded-xl bg-white/12 p-4">
              {[0, 1, 2].map((i) => (
                <div key={i} className="flex items-center gap-4 border-b border-white/10 py-2.5 last:border-0">
                  <div className="h-2.5 w-24 rounded-full bg-white/40" />
                  <div className="h-2.5 w-16 rounded-full bg-white/20" />
                  <div className={`ml-auto h-5 w-16 rounded-full ${['bg-success-solid/70', 'bg-white/30', 'bg-warning-solid/70'][i]}`} />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Thẻ nổi: tỉ lệ đạt chất lượng (vòng tròn) */}
      <div className="absolute top-40 left-6 w-44 rounded-2xl bg-white/15 p-4 shadow-xl ring-1 ring-white/25 backdrop-blur-lg xl:left-10">
        <div className="h-2 w-16 rounded-full bg-white/40" />
        <svg viewBox="0 0 36 36" className="mx-auto mt-3 size-20 -rotate-90">
          <circle cx="18" cy="18" r="15" fill="none" stroke="white" strokeOpacity=".15" strokeWidth="4" />
          <circle cx="18" cy="18" r="15" fill="none" stroke="white" strokeOpacity=".85" strokeWidth="4"
            strokeDasharray="94.2" strokeDashoffset="18" strokeLinecap="round" />
        </svg>
        <div className="mx-auto mt-3 h-2 w-20 rounded-full bg-white/30" />
      </div>
    </div>
  )
}
