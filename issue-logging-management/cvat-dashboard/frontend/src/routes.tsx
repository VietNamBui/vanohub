import { Suspense, lazy } from 'react'
import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import AppLayout from './layouts/AppLayout'
import { useStore } from './mock/store'
import { canAccessPath, HOME_ROUTE } from './mock/selectors'
import LoginPage from './pages/login/LoginPage'
import QueuePage from './pages/queue/QueuePage'

// Các trang còn lại chia nhỏ bundle bằng React.lazy (trừ Login và Hàng đợi là trang khởi đầu).
const ProjectOverviewPage = lazy(() => import('./pages/pm/ProjectOverviewPage'))
const TeamDetailPage = lazy(() => import('./pages/pm/TeamDetailPage'))
const AnnotatorDetailPage = lazy(() => import('./pages/pm/AnnotatorDetailPage'))
const DistributePage = lazy(() => import('./pages/pm/DistributePage'))
const DataTypeConfigPage = lazy(() => import('./pages/pm/config/DataTypeConfigPage'))
const DriftListPage = lazy(() => import('./pages/pm/config/DriftListPage'))
const TeamMembersPage = lazy(() => import('./pages/lead/TeamMembersPage'))
const MyKpiPage = lazy(() => import('./pages/annotator/MyKpiPage'))
const JobDetailPage = lazy(() => import('./pages/job/JobDetailPage'))
const UsersTeamsPage = lazy(() => import('./pages/admin/UsersTeamsPage'))
const ProfilePage = lazy(() => import('./pages/profile/ProfilePage'))
const BatchRedirect = lazy(() => import('./pages/queue/BatchRedirect'))
const AuditsPage = lazy(() => import('./pages/audits/AuditsPage'))
const AuditDetailPage = lazy(() => import('./pages/audits/AuditDetailPage'))
const DataStatisticPage = lazy(() => import('./pages/stats/DataStatisticPage'))
const TeamsMembersPage = lazy(() => import('./pages/admin/TeamsMembersPage'))

/** Route table. Mỗi page là default export ở đúng đường dẫn; agent wave 1 chỉ thay nội dung file page. */
export const ROUTE_PATHS = {
  pm: '/pm', pmTeam: '/pm/teams/:teamId', pmUser: '/pm/users/:userId', pmQc2: '/pm/qc2', pmDistribute: '/pm/distribute',
  pmConfig: '/pm/config', pmDrift: '/pm/drift', lead: '/lead', leadQc1: '/lead/qc1', leadMembers: '/lead/members',
  me: '/me', meKpi: '/me/kpi', job: '/jobs/:jobId', admin: '/admin', adminTeams: '/admin/teams', login: '/login',
  queue: '/queue', profile: '/profile', datasets: '/datasets', batches: '/batches', batchDetail: '/batches/:batchId',
  audits: '/audits', auditDetail: '/audits/:auditId', stats: '/stats',
} as const

function RootRedirect() {
  const { currentUser } = useStore()
  return <Navigate to={HOME_ROUTE[currentUser.role]} replace />
}

/** Chặn trang ngoài quyền của vai (gõ thẳng URL) ⇒ về trang chủ của vai. */
function AccessGuard() {
  const { currentUser } = useStore()
  const { pathname } = useLocation()
  return canAccessPath(currentUser.role, pathname) ? <Outlet /> : <Navigate to={HOME_ROUTE[currentUser.role]} replace />
}

/** Skeleton nhẹ khi trang lazy đang tải (đúng khung .cvd-page, không spinner tròn). */
function RouteSkeleton() {
  return (
    <div className="cvd-page" style={{ padding: '24px 16px 48px' }}>
      <div className="cvd-inner">
        <div style={{ marginBottom: 24 }}>
          <div style={{ width: '38%', minWidth: 200, height: 44, borderRadius: 12, background: '#e2e2e2', animation: 'cvd-skeleton 1.2s ease-in-out infinite' }} />
        </div>
        <div className="cvd-grid" style={{ gridTemplateColumns: '2fr 1fr' }}>
          <div style={{ height: 220, borderRadius: 24, background: '#e6e6e6', animation: 'cvd-skeleton 1.2s ease-in-out infinite' }} />
          <div style={{ height: 220, borderRadius: 24, background: '#e6e6e6', animation: 'cvd-skeleton 1.2s ease-in-out infinite' }} />
        </div>
        <div className="cvd-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
          <div style={{ height: 140, borderRadius: 24, background: '#e6e6e6', animation: 'cvd-skeleton 1.2s ease-in-out infinite' }} />
          <div style={{ height: 140, borderRadius: 24, background: '#e6e6e6', animation: 'cvd-skeleton 1.2s ease-in-out infinite' }} />
          <div style={{ height: 140, borderRadius: 24, background: '#e6e6e6', animation: 'cvd-skeleton 1.2s ease-in-out infinite' }} />
        </div>
        <style>{`@keyframes cvd-skeleton { 0%,100% { opacity: .55 } 50% { opacity: 1 } }`}</style>
      </div>
    </div>
  )
}

export function AppRoutes() {
  return (
    <Suspense fallback={<RouteSkeleton />}>
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<AppLayout />}>
        <Route element={<AccessGuard />}>
          <Route path="/" element={<RootRedirect />} />
          <Route path="/pm" element={<ProjectOverviewPage />} />
          <Route path="/pm/teams/:teamId" element={<TeamDetailPage />} />
          <Route path="/pm/users/:userId" element={<AnnotatorDetailPage />} />
          <Route path="/pm/qc2" element={<Navigate to="/audits" replace />} />
          <Route path="/pm/distribute" element={<DistributePage />} />
          <Route path="/pm/config" element={<DataTypeConfigPage />} />
          <Route path="/pm/drift" element={<DriftListPage />} />
          {/* W1-A: Kho job team / Hàng chờ QC1 gộp vào Hàng đợi */}
          <Route path="/lead" element={<Navigate to="/queue" replace />} />
          <Route path="/lead/qc1" element={<Navigate to="/queue" replace />} />
          <Route path="/lead/members" element={<TeamMembersPage />} />
          <Route path="/me" element={<MyKpiPage />} />
          <Route path="/me/kpi" element={<MyKpiPage />} />
          <Route path="/jobs/:jobId" element={<JobDetailPage />} />
          <Route path="/admin" element={<UsersTeamsPage />} />
          <Route path="/admin/teams" element={<TeamsMembersPage />} />
          <Route path="/queue" element={<QueuePage />} />
          <Route path="/queue/:projectId" element={<QueuePage />} />
          <Route path="/queue/:projectId/:datasetId" element={<QueuePage />} />
          <Route path="/queue/:projectId/:datasetId/:batchId" element={<QueuePage />} />
          <Route path="/profile" element={<ProfilePage />} />
          {/* W1-A: Datasets / Batches gộp vào Hàng đợi */}
          <Route path="/datasets" element={<Navigate to="/queue" replace />} />
          <Route path="/batches" element={<Navigate to="/queue" replace />} />
          <Route path="/batches/:batchId" element={<BatchRedirect />} />
          <Route path="/audits" element={<AuditsPage />} />
          <Route path="/audits/:auditId" element={<AuditDetailPage />} />
          <Route path="/stats" element={<DataStatisticPage />} />
          <Route path="*" element={<RootRedirect />} />
        </Route>
      </Route>
    </Routes>
    </Suspense>
  )
}
