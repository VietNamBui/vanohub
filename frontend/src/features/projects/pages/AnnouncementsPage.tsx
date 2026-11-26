import { Card, List, Space, Tag, Typography } from 'antd'
import { getErrorMessage } from '../../../shared/api/errors'
import StateView from '../../../shared/components/StateView'
import { useRequest } from '../../../shared/hooks/useRequest'
import { ROLE_LABELS } from '../../../shared/types/roles'
import { formatDateTime } from '../../../shared/utils/format'
import { listAnnouncements } from '../api'
import { useProject } from '../projectContext'

/** Thông báo của organization — chỉ xem lịch sử (phần soạn / gửi thông báo đã bỏ khỏi giao diện). */
export default function AnnouncementsPage() {
  const { projectId } = useProject()
  const { data, error, isLoading, retry } = useRequest(`announcements:${projectId}`, () => listAnnouncements(projectId))

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Thông báo organization</h1>
          <p>Lịch sử thông báo trong organization.</p>
        </div>
      </div>
      <Card title="Lịch sử thông báo">
        {error != null ? (
          <StateView kind="error" description={getErrorMessage(error)} action={{ label: 'Thử lại', onClick: retry }} />
        ) : (
          <List
            loading={isLoading}
            dataSource={data ?? []}
            locale={{ emptyText: 'Chưa có thông báo' }}
            renderItem={(a) => (
              <List.Item>
                <List.Item.Meta
                  title={
                    <Space wrap>
                      <span>{a.sender?.full_name}</span>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>{formatDateTime(a.created_at)}</Typography.Text>
                      {a.target_roles.length === 0 ? <Tag>Mọi vai trò</Tag> : a.target_roles.map((r) => <Tag key={r}>{ROLE_LABELS[r]}</Tag>)}
                      {a.target_team_name && <Tag color="blue">{a.target_team_name}</Tag>}
                    </Space>
                  }
                  description={<span style={{ whiteSpace: 'pre-wrap', color: 'inherit' }}>{a.content}</span>}
                />
              </List.Item>
            )}
          />
        )}
      </Card>
    </div>
  )
}
