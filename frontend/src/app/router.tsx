import type { ReactNode } from 'react'
import { createBrowserRouter } from 'react-router'
import LoginPage from '../features/auth/LoginPage'
import RequireAuth from '../features/auth/RequireAuth'
import JobsPage from '../features/jobs/pages/JobsPage'
import QueuePage from '../features/jobs/pages/QueuePage'
import AnnouncementsPage from '../features/projects/pages/AnnouncementsPage'
import BatchesPage from '../features/projects/pages/BatchesPage'
import DatasetsPage from '../features/projects/pages/DatasetsPage'
import GuidelinesPage from '../features/projects/pages/GuidelinesPage'
import OverviewPage from '../features/projects/pages/OverviewPage'
import ProjectListPage from '../features/projects/pages/ProjectListPage'
import TeamRankingPage from '../features/projects/pages/TeamRankingPage'
import ProjectLayout from '../features/projects/ProjectLayout'
import { ProjectIndexRedirect, RequireCap } from '../features/projects/RequireCap'
import AuditsPage from '../features/quality/qc2/AuditsPage'
import AuditStrategyPage from '../features/quality/qc2/AuditStrategyPage'
import AuditWorkPage from '../features/quality/qc2/AuditWorkPage'
import Qc2DashboardPage from '../features/quality/qc2/Qc2DashboardPage'
import CvatLinkPage from '../features/cvat/pages/CvatLinkPage'
import HomeRedirect from '../features/projects/HomeRedirect'
import TeamDetailPage from '../features/teams/pages/TeamDetailPage'
import TeamsPage from '../features/teams/pages/TeamsPage'
import MainLayout from '../layouts/MainLayout'
import StateView from '../shared/components/StateView'
import type { Capability } from '../shared/types/capabilities'

/** Route trong dự án, kèm capability cần có (khớp với capability backend kiểm tra ở API tương ứng). */
const guarded = (path: string, cap: Capability | Capability[], element: ReactNode) => ({
  path,
  element: <RequireCap cap={cap}>{element}</RequireCap>,
})

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        path: '/',
        element: <MainLayout />,
        children: [
          { index: true, element: <HomeRedirect /> },
          { path: 'projects', element: <ProjectListPage /> },
          {
            path: 'projects/:projectId',
            element: <ProjectLayout />,
            children: [
              { index: true, element: <ProjectIndexRedirect /> },
              guarded('overview', 'view_dashboard', <OverviewPage />),
              guarded('team-ranking', 'view_dashboard', <TeamRankingPage />),
              guarded('datasets', 'view_jobs', <DatasetsPage />),
              guarded('batches', 'view_jobs', <BatchesPage />),
              guarded('jobs', 'view_jobs', <JobsPage />),
              guarded('queue', 'view_jobs', <QueuePage />),
              guarded('teams', 'manage_team', <TeamsPage />),
              guarded('teams/:teamId', 'manage_team', <TeamDetailPage />),
              guarded('audits', 'manage_audits', <AuditsPage />),
              guarded('qc2/strategy', 'manage_audits', <AuditStrategyPage />),
              guarded('qc2/work', 'perform_audit', <AuditWorkPage />),
              guarded('qc2/dashboard', 'perform_audit', <Qc2DashboardPage />),
              guarded('guidelines', 'view_guidelines', <GuidelinesPage />),
              guarded('cvat-link', 'view_project', <CvatLinkPage />),
              guarded('announcements', 'view_project', <AnnouncementsPage />),
            ],
          },
        ],
      },
    ],
  },
  { path: '*', element: <StateView kind="empty" title="Không tìm thấy trang" /> },
])
