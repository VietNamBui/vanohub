import { DownOutlined, KeyOutlined, LogoutOutlined, UserOutlined } from '@ant-design/icons'
import { Avatar, Dropdown, Layout, Space } from 'antd'
import { useState } from 'react'
import { Link, Outlet, useMatch } from 'react-router'
import ChangePasswordDialog from '../features/auth/ChangePasswordDialog'
import { useAuth } from '../features/auth/useAuth'
import { listProjects } from '../features/projects/api'
import ProjectSwitcher from '../features/projects/components/ProjectSwitcher'
import { useRequest } from '../shared/hooks/useRequest'
import HeaderRoles from './HeaderRoles'
import NotificationBell from './NotificationBell'

/**
 * Khung chung sau khi đăng nhập: thanh trên cùng + nội dung.
 * Dự án đang chọn lấy từ URL (/projects/:projectId/...) nên tải lại trang vẫn đúng.
 */
export default function MainLayout() {
  const { user, logout } = useAuth()
  const [changingPassword, setChangingPassword] = useState(false)
  const projectMatch = useMatch('/projects/:projectId/*')
  const projectId = projectMatch ? Number(projectMatch.params.projectId) : null
  // Dùng chung cho vai trò + chuông. Tải lại khi đổi trang dự án → vai trò vừa được gán cũng hiện ra.
  const { data: projects } = useRequest(`header-projects:${projectId ?? 'all'}`, listProjects)
  const scopedProjects = (projects ?? []).filter((p) => projectId === null || p.id === projectId)
  const displayName = [user?.first_name, user?.last_name].filter(Boolean).join(' ') || user?.username

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Header
        style={{
          display: 'flex', alignItems: 'center', gap: 16, padding: '0 20px',
          background: '#fff', borderBottom: '1px solid #f0f0f0', position: 'sticky', top: 0, zIndex: 10,
        }}
      >
        <Link to="/projects" style={{ fontSize: 18, fontWeight: 700, color: 'inherit', width: 196 }}>
          Vanohub
        </Link>
        {projectId !== null && <ProjectSwitcher currentProjectId={projectId} />}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12 }}>
          {scopedProjects.length > 0 && <NotificationBell projects={scopedProjects} />}
          <HeaderRoles projects={projects ?? []} projectId={projectId} />
          <Dropdown
            menu={{
              items: [
                { key: 'projects', label: <Link to="/projects">Organization của tôi</Link> },
                { key: 'password', icon: <KeyOutlined />, label: 'Đổi mật khẩu', onClick: () => setChangingPassword(true) },
                { type: 'divider' },
                { key: 'logout', icon: <LogoutOutlined />, label: 'Đăng xuất', onClick: logout },
              ],
            }}
          >
            <Space style={{ cursor: 'pointer' }}>
              <Avatar size="small" icon={<UserOutlined />} />
              {displayName}
              <DownOutlined style={{ fontSize: 10 }} />
            </Space>
          </Dropdown>
        </div>
      </Layout.Header>
      <Layout.Content>
        <Outlet />
      </Layout.Content>
      {changingPassword && <ChangePasswordDialog onClose={() => setChangingPassword(false)} />}
    </Layout>
  )
}
