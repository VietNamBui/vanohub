import type { ReactNode } from 'react'
import { createBrowserRouter } from 'react-router'
import AccountSettingsPage from '../features/accounts/AccountSettingsPage'
import AnnotatorAnalyticsPage from '../features/analytics/AnnotatorAnalyticsPage'
import LoginPage from '../features/auth/LoginPage'
import RequireAuth from '../features/auth/RequireAuth'
import CvatLinkPage from '../features/cvat/pages/CvatLinkPage'
import AnnotatorDashboardPage from '../features/jobs/pages/AnnotatorDashboardPage'
import AnnotatorJobDetailPage from '../features/jobs/pages/AnnotatorJobDetailPage'
import AnnotatorJobsPage from '../features/jobs/pages/AnnotatorJobsPage'
import AnnotatorRequestsPage from '../features/jobs/pages/AnnotatorRequestsPage'
import AnnotatorReworkPage from '../features/jobs/pages/AnnotatorReworkPage'
import JobsPage from '../features/jobs/pages/JobsPage'
import QueuePage from '../features/jobs/pages/QueuePage'
import HomeRedirect from '../features/projects/HomeRedirect'
import AnnouncementsPage from '../features/projects/pages/AnnouncementsPage'
import BatchesPage from '../features/projects/pages/BatchesPage'
import DatasetsPage from '../features/projects/pages/DatasetsPage'
import DeliveryPage from '../features/projects/pages/DeliveryPage'
import GuidelinesPage from '../features/projects/pages/GuidelinesPage'
import OverviewPage from '../features/projects/pages/OverviewPage'
import ProjectListPage from '../features/projects/pages/ProjectListPage'
import TeamRankingPage from '../features/projects/pages/TeamRankingPage'
import ProjectLayout from '../features/projects/ProjectLayout'
import { ProjectIndexRedirect, RequireCap } from '../features/projects/RequireCap'
import ErrorCategoriesPage from '../features/quality/pages/ErrorCategoriesPage'
import Qc1DashboardPage from '../features/quality/qc1/Qc1DashboardPage'
import Qc1WorkPage from '../features/quality/qc1/Qc1WorkPage'
import AuditsPage from '../features/quality/qc2/AuditsPage'
import AuditStrategyPage from '../features/quality/qc2/AuditStrategyPage'
import AuditWorkPage from '../features/quality/qc2/AuditWorkPage'
import Qc2DashboardPage from '../features/quality/qc2/Qc2DashboardPage'
import TeamDetailPage from '../features/teams/pages/TeamDetailPage'
import TeamsPage from '../features/teams/pages/TeamsPage'
import WorkloadPage from '../features/teams/pages/WorkloadPage'
import MainLayout from '../layouts/MainLayout'
import StateView from '../shared/components/StateView'
import type { Capability } from '../shared/types/capabilities'

/** Route trong organization, kèm capability cần có (khớp với capability backend kiểm tra ở API tương ứng). */
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
          { path: 'cvat-link', element: <CvatLinkPage /> },
          { path: 'account/settings', element: <AccountSettingsPage /> },
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
              guarded('workload', ['manage_team', 'view_dashboard'], <WorkloadPage />),
              guarded('audits', 'manage_audits', <AuditsPage />),
              guarded('qc2/strategy', 'manage_audits', <AuditStrategyPage />),
              guarded('qc2/work', 'perform_audit', <AuditWorkPage />),
              guarded('qc2/dashboard', 'perform_audit', <Qc2DashboardPage />),
              guarded('qc1/dashboard', ['perform_qc1', 'view_dashboard'], <Qc1DashboardPage />),
              guarded('qc1/work', 'perform_qc1', <Qc1WorkPage />),
              guarded('annotator/dashboard', 'annotate_jobs', <AnnotatorDashboardPage />),
              guarded('annotator/analytics', 'annotate_jobs', <AnnotatorAnalyticsPage />),
              guarded('annotator/jobs', 'annotate_jobs', <AnnotatorJobsPage />),
              guarded('annotator/jobs/:jobId', 'annotate_jobs', <AnnotatorJobDetailPage />),
              guarded('annotator/rework', 'annotate_jobs', <AnnotatorReworkPage />),
              guarded('annotator/requests', ['annotate_jobs', 'manage_jobs'], <AnnotatorRequestsPage />),
              guarded('error-categories', 'manage_quality_catalog', <ErrorCategoriesPage />),
              guarded('delivery', 'manage_delivery', <DeliveryPage />),
              guarded('guidelines', 'view_guidelines', <GuidelinesPage />),
              guarded('cvat-link', 'view_project', <CvatLinkPage />),
              guarded('announcements', 'view_project', <AnnouncementsPage />),
              guarded('account/settings', 'view_project', <AccountSettingsPage />),
            ],
          },
        ],
      },
    ],
  },
  { path: '*', element: <StateView kind="empty" title="Không tìm thấy trang" /> },
])
