import { Select, type SelectProps } from 'antd'
import { useRequest } from '../../../shared/hooks/useRequest'
import type { Role } from '../../../shared/types/roles'
import { listMembers } from '../api'

type Props = Omit<SelectProps<number>, 'options' | 'loading'> & { projectId: number; role?: Role }

/** Chọn người trong dự án, có thể lọc theo vai trò (vd. chỉ Annotator). Hiện số job đang giữ để cân tải. */
export default function MemberSelect({ projectId, role, ...props }: Props) {
  const { data: members, isLoading } = useRequest(`members:${projectId}:${role ?? ''}`, () =>
    listMembers(projectId, role),
  )
  return (
    <Select<number>
      showSearch={{ optionFilterProp: 'label' }}
      allowClear
      placeholder="Chọn người"
      loading={isLoading}
      options={members?.map((m) => ({
        value: m.user.id,
        label: `${m.user.full_name} (${m.user.username}) · ${m.active_jobs} job${m.team ? ` · ${m.team.name}` : ''}`,
      }))}
      {...props}
    />
  )
}
