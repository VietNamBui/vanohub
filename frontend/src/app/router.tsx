import { Suspense, type ReactNode } from 'react'
import { createBrowserRouter } from 'react-router'
import RequireAuth from '../features/auth/RequireAuth'
import HomeRedirect from '../features/projects/HomeRedirect'
import ProjectLayout from '../features/projects/ProjectLayout'
import { ProjectIndexRedirect, RequireCap } from '../features/projects/RequireCap'
import MainLayout from '../layouts/MainLayout'
import StateView from '../shared/components/StateView'
import PageState from '../shared/components/ui/PageState'
import type { Capability } from '../shared/types/capabilities'
import {
  AccountSettingsPage,
  AnnouncementsPage,
  AnnotatorAnalyticsPage,
  AnnotatorDashboardPage,
  AnnotatorJobDetailPage,
  AnnotatorJobsPage,
  AnnotatorRequestsPage,
  AnnotatorReworkPage,
  AuditsPage,
  AuditStrategyPage,
  AuditWorkPage,
  BatchesPage,
  CvatLinkPage,
  DatasetsPage,
  DeliveryPage,
  ErrorCategoriesPage,
  GuidelinesPage,
  JobsPage,
  LoginPage,
  OverviewPage,
  ProjectListPage,
  Qc1DashboardPage,
  Qc1WorkPage,
  Qc2DashboardPage,
  QueuePage,
  TeamDetailPage,
  TeamRankingPage,
  TeamsPage,
  WorkloadPage,
} from './lazyPages'

const page = (element: ReactNode) => <Suspense fallback={<PageState kind="loading" />}>{element}</Suspense>

/** Route trong organization, kèm capability cần có (khớp với capability backend kiểm tra ở API tương ứng). */
const guarded = (path: string, cap: Capability | Capability[], element: ReactNode) => ({
  path,
  element: <RequireCap cap={cap}>{page(element)}</RequireCap>,
})

export const router = createBrowserRouter([
  { path: '/login', element: page(<LoginPage />) },
  {
    element: <RequireAuth />,
    children: [
      {
        path: '/',
        element: <MainLayout />,
        children: [
          { index: true, element: <HomeRedirect /> },
          { path: 'projects', element: page(<ProjectListPage />) },
          { path: 'cvat-link', element: page(<CvatLinkPage />) },
          { path: 'account/settings', element: page(<AccountSettingsPage />) },
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
