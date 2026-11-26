import { Alert, Card, Progress, Select, Table, Tag } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router'
import { getErrorMessage } from '../../../shared/api/errors'
import RoleBadges from '../../../shared/components/RoleBadges'
import StateView from '../../../shared/components/StateView'
import UserName from '../../../shared/components/UserName'
import { useRequest } from '../../../shared/hooks/useRequest'
import { useProject } from '../../projects/projectContext'
import { getWorkload, listTeams } from '../api'
import type { Workload } from '../types'

/** Tải công việc từng người (PM theo dõi workload). Xếp theo tải thấp nhất trước để chọn người nhận khi giao lại. */
export default function WorkloadPage() {
  const { projectId } = useProject()
  const [team, setTeam] = useState<number>()
  const { data, error, isLoading, retry } = useRequest(`workload:${projectId}:${team ?? ''}`, () => getWorkload(projectId, team))
  const { data: teams } = useRequest(`teams:${projectId}`, () => listTeams(projectId))

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Tải công việc</h1>
          <p>Số job đang giữ so với sức chứa. Người tải thấp nhất ở trên cùng.</p>
        </div>
        <Select allowClear placeholder="Tất cả team" style={{ width: 200 }} value={team} onChange={setTeam}
          options={teams?.map((t) => ({ value: t.id, label: t.name }))} />
      </div>
      <Alert type="info" showIcon style={{ marginBottom: 16 }} title="Chỉ tính người đã được phân vào team. Giao lại job ở trang Jobs (chọn nhiều job → Giao lại)." />
      <Card>
        {error != null ? (
          <StateView kind="error" description={getErrorMessage(error)} action={{ label: 'Thử lại', onClick: retry }} />
        ) : (
          <Table<Workload>
            rowKey={(r) => r.user.id}
            loading={isLoading}
            dataSource={data ?? []}
            locale={{ emptyText: 'Chưa có ai trong team' }}
            columns={[
              { title: 'Thành viên', render: (_, r) => <UserName user={r.user} /> },
              { title: 'Team', render: (_, r) => r.team.name },
              { title: 'Vai trò', render: (_, r) => <RoleBadges roles={r.roles} /> },
              {
                title: 'Đang giữ / sức chứa', width: 220,
                render: (_, r) => (
                  <Progress size="small" percent={Math.round((r.holding * 100) / Math.max(r.capacity, 1))}
                    status={r.holding > r.capacity ? 'exception' : 'normal'} format={() => `${r.holding}/${r.capacity}`} />
                ),
              },
              { title: 'Đang QC1', dataIndex: 'qc1_holding', align: 'right' },
              { title: 'Sắp deadline (24h)', dataIndex: 'due_soon', align: 'right', render: (n: number) => (n ? <Tag color="warning">{n}</Tag> : 0) },
              { title: 'Escalated', dataIndex: 'escalated', align: 'right', render: (n: number) => (n ? <Tag color="error">{n}</Tag> : 0) },
              { title: '', render: (_, r) => <Link to={`../jobs?assignee=${r.user.id}`} relative="path">Xem job</Link> },
            ]}
          />
        )}
      </Card>
    </div>
  )
}
