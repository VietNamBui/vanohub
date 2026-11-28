import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { Button, Form, Input, message } from 'antd'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { Card, Tag } from '../../design'
import type { Tone } from '../../design/widgets'
import { HOME_ROUTE, ROLE_LABEL } from '../../mock/selectors'
import { useStore } from '../../mock/store'
import type { Role, User } from '../../mock/types'
import './login.scss'

const ROLES: Role[] = ['admin', 'pm', 'lead', 'annotator']
const ROLE_TONE: Record<Role, Tone> = { admin: 'pink', pm: 'blue', lead: 'purple', annotator: 'green' }

export function isDemoModeEnabled(env: { DEV?: boolean; VITE_USE_MOCK?: string } = import.meta.env): boolean {
  return Boolean(env.DEV || env.VITE_USE_MOCK === 'true')
}

export function shouldFallbackToMockLogin(err: unknown, demoMode: boolean): boolean {
  if (!demoMode) return false
  // Never bypass authentication when the backend explicitly rejected the request (4xx).
  if (err instanceof ApiError && err.status >= 400 && err.status < 500) return false
  return true
}

export default function LoginPage() {
  const s = useStore()
  const navigate = useNavigate()
  const [form] = Form.useForm<{ username: string; password: string }>()
  const demoMode = isDemoModeEnabled()

  const loginAs = async (u: User) => {
    if (!demoMode) return
    try {
      try {
        const apiUser = await s.loginWithApi(u.cvatUsername, 'dashboard123')
        navigate(HOME_ROUTE[apiUser.role])
        return
      } catch (err) {
        if (!shouldFallbackToMockLogin(err, demoMode)) {
          message.error(err instanceof Error ? err.message : 'Đăng nhập thất bại')
          return
        }
        // Fallback to local demo mode when Django backend is not running in dev/mock mode
      }
      s.setCurrentUser(u.id)
      navigate(HOME_ROUTE[u.role])
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const onFinish = async ({ username, password }: { username: string; password?: string }) => {
    const trimmedUser = username.trim()
    try {
      if (password) {
        const apiUser = await s.loginWithApi(trimmedUser, password)
        navigate(HOME_ROUTE[apiUser.role])
        return
      }
      if (!demoMode) {
        message.error('Vui lòng nhập mật khẩu')
        return
      }
    } catch (err) {
      if (!shouldFallbackToMockLogin(err, demoMode)) {
        message.error(err instanceof Error ? err.message : 'Đăng nhập thất bại')
        return
      }
      // Fallback to local mock accounts only when backend is offline in dev/mock mode
    }
    if (!demoMode) return
    const u = s.users.find((x) => x.cvatUsername.toLowerCase() === trimmedUser.toLowerCase())
    if (!u) {
      message.error('Không tìm thấy tài khoản CVAT này')
      return
    }
    s.setCurrentUser(u.id)
    navigate(HOME_ROUTE[u.role])
  }

  const demo = demoMode
    ? ROLES.map((r) => ({ role: r, user: s.users.find((u) => u.role === r) })).filter(
        (x): x is { role: Role; user: User } => !!x.user,
      )
    : []

  return (
    <div className="lg-canvas">
      <div className="lg-wrap">
        <div className="lg-wordmark">CV<i>A</i>T</div>
        <div className="lg-sub">Dashboard quản lý annotation</div>
        <Card className="lg-card">
          <h2>Đăng nhập bằng tài khoản CVAT</h2>
          <div className="lg-server">
            <span>Máy chủ CVAT</span>
            <Tag tone="blue">http://cvat.local</Tag>
          </div>
          <Form form={form} layout="vertical" onFinish={onFinish} requiredMark={false}>
            <Form.Item name="username" label="Tên đăng nhập CVAT" rules={[{ required: true, message: 'Nhập tên đăng nhập' }]}>
              <Input prefix={<UserOutlined />} placeholder="Tên đăng nhập CVAT" autoComplete="username" size="large" />
            </Form.Item>
            <Form.Item name="password" label="Mật khẩu" rules={[{ required: true, message: 'Nhập mật khẩu' }]}>
              <Input.Password
                prefix={<LockOutlined />}
                placeholder={demoMode ? 'Mật khẩu bất kỳ' : 'Nhập mật khẩu'}
                autoComplete="current-password"
                size="large"
              />
            </Form.Item>
            <Button type="primary" htmlType="submit" block size="large">Đăng nhập</Button>
          </Form>
          {demoMode && (
            <div className="lg-demo">
              <p>Bản demo: mật khẩu nào cũng được. Chọn nhanh tài khoản:</p>
              <div className="lg-chips">
                {demo.map(({ role, user }) => (
                  <button key={user.id} type="button" className="lg-chip" onClick={() => loginAs(user)}>
                    <Tag tone={ROLE_TONE[role]}>{ROLE_LABEL[role]}: {user.cvatUsername}</Tag>
                  </button>
                ))}
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
