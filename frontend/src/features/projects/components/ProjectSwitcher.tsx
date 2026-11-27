import { useNavigate } from 'react-router'
import SearchableSelect, { type SearchableOption } from '../../../shared/components/ui/SearchableSelect'
import { useRequest } from '../../../shared/hooks/useRequest'
import { listProjects } from '../api'

/** Bộ chọn "Dự án đang chọn" trên thanh trên cùng (hỗ trợ tìm kiếm theo tên). */
export default function ProjectSwitcher({ currentProjectId }: { currentProjectId: number }) {
  const navigate = useNavigate()
  const { data: projects, isLoading } = useRequest('projects', listProjects)

  const items: SearchableOption[] = (projects ?? []).map((p) => ({
    id: p.id,
    label: p.name,
  }))

  return (
    <SearchableSelect
      size="sm"
      className="w-72"
      ariaLabel="Dự án đang chọn"
      placeholder="Organization đang chọn"
      searchPlaceholder="Tìm organization…"
      allowClear={false}
      isDisabled={isLoading || items.length === 0}
      items={items}
      selectedKey={projects?.some((p) => p.id === currentProjectId) ? currentProjectId : null}
      onSelectionChange={(key) => {
        if (key != null) navigate(`/projects/${key}`)
      }}
    />
  )
}
