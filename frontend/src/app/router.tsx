import { createBrowserRouter, Navigate } from 'react-router'
import MainLayout from '../layouts/MainLayout'
import Placeholder from '../shared/components/Placeholder'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <MainLayout />,
    children: [
      { index: true, element: <Navigate to="/projects" replace /> },
      { path: 'projects', element: <Placeholder title="Projects" /> },
      { path: 'jobs', element: <Placeholder title="Jobs" /> },
      {
        path: 'quality',
        children: [
          { index: true, element: <Navigate to="qc1" replace /> },
          { path: 'qc1', element: <Placeholder title="QC1" /> },
          { path: 'qc2', element: <Placeholder title="QC2" /> },
          { path: 'rework', element: <Placeholder title="Rework" /> },
        ],
      },
      { path: 'teams', element: <Placeholder title="Teams" /> },
      { path: 'accounts', element: <Placeholder title="Accounts" /> },
      { path: 'analytics', element: <Placeholder title="Analytics" /> },
    ],
  },
  { path: '/login', element: <Placeholder title="Login" /> },
  { path: '*', element: <Placeholder title="404 - Không tìm thấy trang" /> },
])
