import {
  AuditOutlined,
  BarChartOutlined,
  DatabaseOutlined,
  NotificationOutlined,
  SendOutlined,
  SettingOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import { Layout, Menu, type MenuProps } from 'antd'
import { useEffect, useMemo } from 'react'
import { Outlet, useLocation, useNavigate, useParams } from 'react-router'
import { getErrorKind, getErrorMessage } from '../../shared/api/errors'
import StateView from '../../shared/components/StateView'
import { useRequest } from '../../shared/hooks/useRequest'
import type { Capability } from '../../shared/types/capabilities'
import { getProject } from './api'
import { setLastProjectId } from './lastProject'
import { ProjectContext, type ProjectContextValue } from './projectContext'

type Item = { key: string; label: string; cap: Capability | Capability[] }
type Group = { key: string; label: string; icon: React.ReactNode; items: Item[] }

/** Menu theo workflow. Mục nào user không có capability thì ẩn đi. */
const MENU: Group[] = [
  {
    key: 'g-overview', label: 'Tổng quan', icon: <BarChartOutlined />,
    items: [
      { key: 'overview', label: 'Tổng quan dự án', cap: 'view_dashboard' },
      { key: 'team-ranking', label: 'Xếp hạng team', cap: 'view_dashboard' },
      { key: 'qc2/dashboard', label: 'Tổng quan QC2', cap: 'perform_audit' },
      { key: 'qc1/dashboard', label: 'Tổng quan QC1', cap: ['perform_qc1', 'view_dashboard'] },
      { key: 'leader/overview', label: 'Tổng quan team', cap: 'lead_team' },
      { key: 'annotator/dashboard', label: 'Tổng quan Annotator', cap: 'annotate_jobs' },
    ],
  },
  {
    key: 'g-ops', label: 'Vận hành', icon: <DatabaseOutlined />,
    items: [
      { key: 'datasets', label: 'Datasets', cap: 'view_jobs' },
      { key: 'batches', label: 'Batches', cap: 'view_jobs' },
      { key: 'jobs', label: 'Jobs', cap: 'view_jobs' },
      { key: 'queue', label: 'Data Queue', cap: 'view_jobs' },
      { key: 'leader/jobs', label: 'Job của team', cap: 'lead_team' },
      { key: 'annotator/jobs', label: 'Job của tôi', cap: 'annotate_jobs' },
    ],
  },
  {
    key: 'g-people', label: 'Nhân sự', icon: <TeamOutlined />,
    items: [
      { key: 'teams', label: 'Team & Members', cap: 'manage_team' },
      { key: 'workload', label: 'Tải công việc', cap: ['manage_team', 'view_dashboard'] },
      { key: 'leader/members', label: 'Thành viên team', cap: 'lead_team' },
      { key: 'leader/workload', label: 'Tải công việc team', cap: 'lead_team' },
    ],
  },
  {
    key: 'g-quality', label: 'Chất lượng', icon: <AuditOutlined />,
    items: [
      { key: 'audits', label: 'Quản lý Audit', cap: 'manage_audits' },
      { key: 'qc2/strategy', label: 'Chiến thuật audit', cap: 'manage_audits' },
      { key: 'qc2/work', label: 'Job audit QC2', cap: 'perform_audit' },
      { key: 'qc1/work', label: 'Job kiểm tra QC1', cap: 'perform_qc1' },
      { key: 'error-categories', label: 'Danh mục lỗi', cap: 'manage_quality_catalog' },
      { key: 'guidelines', label: 'Hướng dẫn gán nhãn', cap: 'view_guidelines' },
    ],
  },
  {
    key: 'g-delivery', label: 'Bàn giao', icon: <SendOutlined />,
    items: [{ key: 'delivery', label: 'Delivery', cap: 'manage_delivery' }],
  },
  {
    key: 'g-settings', label: 'Cấu hình', icon: <SettingOutlined />,
    items: [
      { key: 'cvat-link', label: 'Liên kết CVAT', cap: 'view_project' },
    ],
  },
  {
    key: 'g-notify', label: 'Thông báo', icon: <NotificationOutlined />,
    items: [{ key: 'announcements', label: 'Thông báo dự án', cap: 'view_project' }],
  },
]

export default function ProjectLayout() {
  const projectId = Number(useParams().projectId)
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { data: project, error, isLoading, retry } = useRequest(`project:${projectId}`, () => getProject(projectId))

  const context = useMemo<ProjectContextValue | null>(() => {
    if (!project) return null
    const caps = new Set(project.my_capabilities)
    return { project, projectId, can: (cap) => caps.has(cap), reload: retry }
  }, [project, projectId, retry])

  // Chỉ nhớ dự án đã mở được (có quyền) → lần đăng nhập sau vào thẳng dự án này.
  useEffect(() => {
    if (project) setLastProjectId(project.id)
  }, [project])

  if (isLoading) return <StateView kind="loading" />
  if (error != null || !context) {
    return getErrorKind(error) === 'not_found' ? (
      <StateView kind="forbidden" title="Không tìm thấy dự án hoặc bạn không có quyền truy cập" />
    ) : (
      <StateView kind="error" description={getErrorMessage(error)} action={{ label: 'Thử lại', onClick: retry }} />
    )
  }

  const allowed = (cap: Item['cap']) => (Array.isArray(cap) ? cap.some(context.can) : context.can(cap))
  const items: MenuProps['items'] = MENU.map((group) => ({
    key: group.key,
    label: group.label,
    icon: group.icon,
    children: group.items.filter((item) => allowed(item.cap)).map((item) => ({ key: item.key, label: item.label })),
  })).filter((group) => group.children.length > 0)

  const base = `/projects/${projectId}/`
  const subPath = pathname.startsWith(base) ? pathname.slice(base.length).replace(/\/$/, '') : ''
  // Trang con (vd. teams/3) vẫn sáng mục cha "teams" trong menu.
  const selected = MENU.flatMap((group) => group.items.map((item) => item.key))
    .filter((key) => subPath === key || subPath.startsWith(`${key}/`))
    .sort((a, b) => b.length - a.length)[0] ?? subPath

  return (
    <ProjectContext.Provider value={context}>
      <Layout style={{ minHeight: 'calc(100vh - 64px)' }}>
        <Layout.Sider width={232} theme="light" breakpoint="lg" collapsedWidth={0} style={{ borderRight: '1px solid #f0f0f0' }}>
          <Menu
            mode="inline"
            items={items}
            selectedKeys={[selected]}
            defaultOpenKeys={MENU.map((g) => g.key)}
            onClick={({ key }) => navigate(`${base}${key}`)}
            style={{ borderInlineEnd: 'none', paddingTop: 8 }}
          />
        </Layout.Sider>
        <Layout.Content style={{ minWidth: 0 }}>
          <Outlet />
        </Layout.Content>
      </Layout>
    </ProjectContext.Provider>
  )
}
