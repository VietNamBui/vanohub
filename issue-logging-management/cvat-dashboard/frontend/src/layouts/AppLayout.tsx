import { useState } from 'react'
import { Dropdown, Form, Input, Modal, Select, message } from 'antd'
import { MenuOutlined, CloseOutlined } from '@ant-design/icons'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useStore } from '../mock/store'
import { HOME_ROUTE, ROLE_LABEL } from '../mock/selectors'
import type { Role } from '../mock/types'
import { avatarColor, SpaceTabsContext } from '../design'
import '../design/dashboard.scss'
import { QuickSearch, NotificationBell } from '../components'

/**
 * Điều hướng theo "khu" (space): mỗi mục trên header là một khu; khu có nhiều trang thì hiện thanh tab con.
 * URL của từng trang giữ nguyên — chỉ gom cách hiển thị.
 */
interface NavTab { key: string; label: string }
interface NavSpace { label: string; tabs: NavTab[] }

const MENU: Record<Role, NavSpace[]> = {
  admin: [
    { label: 'Hàng đợi', tabs: [{ key: '/queue', label: 'Hàng đợi' }] },
    { label: 'Tổng quan', tabs: [{ key: '/stats', label: 'Thống kê' }] },
    { label: 'Audits', tabs: [{ key: '/audits', label: 'Audits' }] },
    { label: 'Quản trị', tabs: [{ key: '/admin/teams', label: 'Teams & Members' }, { key: '/admin', label: 'Người dùng' }] },
  ],
  pm: [
    { label: 'Tổng quan', tabs: [{ key: '/pm', label: 'Tổng quan' }, { key: '/stats', label: 'Thống kê' }] },
    { label: 'Hàng đợi', tabs: [{ key: '/queue', label: 'Hàng đợi' }] },
    {
      label: 'Dữ liệu',
      tabs: [
        { key: '/pm/distribute', label: 'Chia job' }, { key: '/pm/drift', label: 'Lệch CVAT' },
      ],
    },
    { label: 'Audits', tabs: [{ key: '/audits', label: 'Audits' }] },
    { label: 'Cài đặt', tabs: [{ key: '/pm/config', label: 'Loại dữ liệu & KPI' }] },
  ],
  lead: [
    { label: 'Hàng đợi', tabs: [{ key: '/queue', label: 'Hàng đợi' }] },
    { label: 'Thành viên', tabs: [{ key: '/lead/members', label: 'Thành viên' }] },
  ],
  annotator: [
    { label: 'Hàng đợi', tabs: [{ key: '/queue', label: 'Hàng đợi' }] },
    { label: 'KPI của tôi', tabs: [{ key: '/me', label: 'KPI của tôi' }] },
  ],
}

const ROLE_ORDER: Role[] = ['admin', 'pm', 'lead', 'annotator']
const MY_KPI: Record<Role, string> = { admin: '/stats', pm: '/stats', lead: '/me/kpi', annotator: '/me' }

const initials = (name: string) => name.trim().split(/\s+/).slice(-2).map((w) => w[0]).join('').toUpperCase()

function ChangePasswordModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [form] = Form.useForm<{ current: string; next: string; confirm: string }>()
  return (
    <Modal
      className="cvd-modal" title="Đổi mật khẩu" open={open} okText="Đổi mật khẩu" cancelText="Huỷ" destroyOnClose
      onCancel={() => { form.resetFields(); onClose() }}
      onOk={() => form.validateFields().then(() => {
        message.success('Đã đổi mật khẩu (giả lập)')
        form.resetFields()
        onClose()
      }).catch(() => undefined)}
    >
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item name="current" label="Mật khẩu hiện tại" rules={[{ required: true, message: 'Nhập mật khẩu hiện tại' }]}><Input.Password /></Form.Item>
        <Form.Item name="next" label="Mật khẩu mới" rules={[{ required: true, min: 6, message: 'Tối thiểu 6 ký tự' }]}><Input.Password /></Form.Item>
        <Form.Item
          name="confirm" label="Nhập lại mật khẩu mới" dependencies={['next']}
          rules={[{ required: true, message: 'Nhập lại mật khẩu mới' }, ({ getFieldValue }) => ({
            validator: (_, v) => (!v || getFieldValue('next') === v ? Promise.resolve() : Promise.reject(new Error('Mật khẩu nhập lại không khớp'))),
          })]}
        ><Input.Password /></Form.Item>
      </Form>
    </Modal>
  )
}

export default function AppLayout() {
  const { users, currentUser, setCurrentUser, resetDemoData, datasetPreset, setDatasetPreset } = useStore()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [open, setOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [pwOpen, setPwOpen] = useState(false)

  const switchPreset = (preset: 'default' | 'workflow_test') => {
    setDatasetPreset(preset)
    setMenuOpen(false)
    message.success(
      preset === 'workflow_test'
        ? 'Đã chuyển sang Bộ kiểm thử luồng (2 DA × 3 DS × 5 Batch × 8 Job - Chưa chia)'
        : 'Đã chuyển sang Bộ mẫu đầy đủ',
    )
    navigate(HOME_ROUTE[currentUser.role])
  }

  const resetDemo = () => {
    Modal.confirm({
      title: 'Khôi phục dữ liệu mẫu?',
      content: 'Mọi thay đổi demo sẽ bị xoá, về dữ liệu mẫu ban đầu (R10).',
      okText: 'Khôi phục', cancelText: 'Huỷ',
      onOk() {
        resetDemoData()
        message.success('Đã khôi phục dữ liệu mẫu')
        setMenuOpen(false)
        navigate(HOME_ROUTE[currentUser.role])
      },
    })
  }

  const spaces = MENU[currentUser.role]
  // Tab đang mở = khoá dài nhất khớp tiền tố đường dẫn (vd /pm/distribute thắng /pm); khu = khu chứa tab đó.
  const selected = spaces
    .flatMap((sp) => sp.tabs.map((t) => t.key))
    .filter((k) => pathname === k || pathname.startsWith(k + '/'))
    .sort((a, b) => b.length - a.length)[0]
  const activeSpace = spaces.find((sp) => sp.tabs.some((t) => t.key === selected))

  const options = ROLE_ORDER.map((role) => ({
    label: ROLE_LABEL[role],
    options: users.filter((u) => u.role === role).map((u) => ({ value: u.id, label: u.name })),
  }))

  const go = (key: string) => { setOpen(false); navigate(key) }
  const links = (
    spaces.map((sp) => (
      <button key={sp.label} type="button" className={`cvd-nav-link ${sp === activeSpace ? 'active' : ''}`} onClick={() => go(sp.tabs[0].key)}>
        {sp.label}
      </button>
    ))
  )

  const spaceTabs = activeSpace && activeSpace.tabs.length > 1 ? (
    <div className="cvd-space-tabs cvd-segmented" role="tablist" aria-label={activeSpace.label}>
      {activeSpace.tabs.map((t) => (
        <button
          key={t.key} type="button" role="tab" aria-selected={t.key === selected}
          className={t.key === selected ? 'on' : ''} onClick={() => go(t.key)}
        >
          {t.label}
        </button>
      ))}
    </div>
  ) : null

  return (
    <div style={{ minHeight: '100vh' }}>
      <header className="cvd-header">
        <div className="cvd-header-left">
          <div className="cvd-logo" onClick={() => go(HOME_ROUTE[currentUser.role])}><b>CVAT</b><span>Workflow</span></div>
          <nav className="cvd-nav">{links}</nav>
        </div>
        <div className="cvd-header-right">
          <QuickSearch />
          <NotificationBell />
          <Dropdown
            trigger={['click']}
            menu={{
              items: [
                {
                  key: 'default',
                  label: 'Bộ mẫu đầy đủ (Đã có tiến độ & luồng)',
                  onClick: () => switchPreset('default'),
                },
                {
                  key: 'workflow_test',
                  label: 'Bộ kiểm thử luồng (2 DA × 3 DS × 5 Batch × 8 Job)',
                  onClick: () => switchPreset('workflow_test'),
                },
              ],
              selectedKeys: [datasetPreset ?? 'default'],
            }}
          >
            <button type="button" className="cvd-dataset-badge" title="Bấm để chuyển đổi bộ dữ liệu">
              <span className={`cvd-dataset-dot ${datasetPreset === 'workflow_test' ? 'test' : 'demo'}`} />
              {datasetPreset === 'workflow_test' ? 'Bộ kiểm thử (2 DA)' : 'Bộ mẫu đầy đủ'}
            </button>
          </Dropdown>
          <span className="cvd-role-badge">{ROLE_LABEL[currentUser.role]}</span>
          <Dropdown
            trigger={['click']} open={menuOpen} onOpenChange={setMenuOpen} placement="bottomRight"
            dropdownRender={() => (
              <div className="cvd-user-pop">
                <div className="cvd-user-pop-head"><b>{currentUser.name}</b><span>ID: {currentUser.employeeId} · {ROLE_LABEL[currentUser.role]}</span></div>
                <button type="button" className="cvd-user-pop-item" onClick={() => { setMenuOpen(false); setPwOpen(true) }}>Đổi mật khẩu</button>
                <button type="button" className="cvd-user-pop-item" onClick={() => { setMenuOpen(false); go(MY_KPI[currentUser.role]) }}>Năng suất của tôi</button>
                <button type="button" className="cvd-user-pop-item" onClick={() => { setMenuOpen(false); go('/profile') }}>Hồ sơ</button>
                <button type="button" className="cvd-user-pop-item" onClick={resetDemo}>Khôi phục dữ liệu mẫu</button>
                <button type="button" className="cvd-user-pop-item" onClick={() => { setMenuOpen(false); go('/login') }}>Đăng xuất</button>
                <div className="cvd-user-pop-demo">
                  Bộ dữ liệu (demo)
                  <Select
                    value={datasetPreset ?? 'default'}
                    options={[
                      { value: 'default', label: 'Mẫu đầy đủ (Đã có tiến độ & luồng)' },
                      { value: 'workflow_test', label: 'Kiểm thử luồng (2 DA × 3 DS × 5 Batch × 8 Job)' },
                    ]}
                    style={{ width: '100%', marginTop: 6 }}
                    onChange={(preset) => switchPreset(preset)}
                  />
                </div>
                <div className="cvd-user-pop-demo">
                  Đổi người dùng (demo)
                  <Select
                    showSearch optionFilterProp="label" value={currentUser.id} options={options} style={{ width: '100%', marginTop: 6 }}
                    onChange={(id) => {
                      setCurrentUser(id)
                      setMenuOpen(false)
                      navigate(HOME_ROUTE[users.find((u) => u.id === id)!.role])
                    }}
                  />
                </div>
              </div>
            )}
          >
            <button type="button" className="cvd-user-btn" aria-label="Menu người dùng">
              <span className="cvd-avatar" style={{ background: avatarColor(currentUser.name) }}>{initials(currentUser.name)}</span>
              <span className="cvd-user-meta"><b>{currentUser.name}</b><small>ID: {currentUser.employeeId}</small></span>
            </button>
          </Dropdown>
          <button type="button" className="cvd-nav-toggle" aria-label="Menu" onClick={() => setOpen((o) => !o)}>
            {open ? <CloseOutlined /> : <MenuOutlined />}
          </button>
        </div>
        <nav className={`cvd-nav-drawer ${open ? 'open' : ''}`}>{links}</nav>
      </header>
      <main className="cvd-page">
        <div className="cvd-inner">
          <SpaceTabsContext.Provider value={spaceTabs}>
            <Outlet />
          </SpaceTabsContext.Provider>
        </div>
      </main>
      <ChangePasswordModal open={pwOpen} onClose={() => setPwOpen(false)} />
    </div>
  )
}
