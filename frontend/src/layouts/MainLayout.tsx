import { Layout, Menu, type MenuProps } from 'antd'
import {
  BarChartOutlined,
  CheckCircleOutlined,
  FolderOutlined,
  ProfileOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { Outlet, useLocation, useNavigate } from 'react-router'

const { Header, Sider, Content } = Layout

const menuItems: MenuProps['items'] = [
  { key: '/projects', icon: <FolderOutlined />, label: 'Projects' },
  { key: '/jobs', icon: <ProfileOutlined />, label: 'Jobs' },
  {
    key: '/quality',
    icon: <CheckCircleOutlined />,
    label: 'Quality',
    children: [
      { key: '/quality/qc1', label: 'QC1' },
      { key: '/quality/qc2', label: 'QC2' },
      { key: '/quality/rework', label: 'Rework' },
    ],
  },
  { key: '/teams', icon: <TeamOutlined />, label: 'Teams' },
  { key: '/accounts', icon: <UserOutlined />, label: 'Accounts' },
  { key: '/analytics', icon: <BarChartOutlined />, label: 'Analytics' },
]

export default function MainLayout() {
  const navigate = useNavigate()
  const { pathname } = useLocation()

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider breakpoint="lg" collapsible>
        <div style={{ color: '#fff', fontWeight: 600, padding: 16, fontSize: 18 }}>
          VanoHub
        </div>
        <Menu
          theme="dark"
          mode="inline"
          items={menuItems}
          selectedKeys={[pathname]}
          defaultOpenKeys={pathname.startsWith('/quality') ? ['/quality'] : []}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', padding: '0 24px' }} />
        <Content style={{ margin: 24 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
