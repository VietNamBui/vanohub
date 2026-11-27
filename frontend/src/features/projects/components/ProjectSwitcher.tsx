import { Select } from 'antd'
import { useNavigate } from 'react-router'
import { useRequest } from '../../../shared/hooks/useRequest'
import { listProjects } from '../api'

/** Bộ chọn "Dự án đang chọn" trên thanh trên cùng. */
export default function ProjectSwitcher({ currentProjectId }: { currentProjectId: number }) {
  const navigate = useNavigate()
  const { data: projects, isLoading } = useRequest('projects', listProjects)

  return (
    <Select
      style={{ width: 280 }}
      aria-label="Dự án đang chọn"
      loading={isLoading}
      value={projects ? currentProjectId : undefined}
      placeholder="Organization đang chọn"
      onChange={(id) => navigate(`/projects/${id}`)}
      options={projects?.map((p) => ({ value: p.id, label: p.name }))}
      showSearch={{ optionFilterProp: 'label' }}
    />
  )
}
