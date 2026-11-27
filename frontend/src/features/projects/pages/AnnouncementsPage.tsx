import { Button, Card, Form, Input, List, Select, Space, Tag, Typography } from 'antd'
import { useState } from 'react'
import { getErrorMessage } from '../../../shared/api/errors'
import StateView from '../../../shared/components/StateView'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { ROLE_LABELS, type Role } from '../../../shared/types/roles'
import { formatDateTime } from '../../../shared/utils/format'
import { listTeams } from '../../teams/api'
import { listAnnouncements, sendAnnouncement } from '../api'
import { useProject } from '../projectContext'

const TARGET_ROLES: Role[] = ['project_manager', 'qc2', 'qc1', 'annotator']

/** Thông báo của organization: PM có thể soạn gửi theo vai trò/team, thành viên xem lịch sử. */
export default function AnnouncementsPage() {
  const { projectId, can } = useProject()
  const [version, setVersion] = useState(0)
  const [form] = Form.useForm()
  const { run, pending } = useAction()
  const { data, error, isLoading, retry } = useRequest(`announcements:${projectId}:${version}`, () =>
    listAnnouncements(projectId),
  )
  const canSend = can('send_announcement')
  const { data: teams } = useRequest(`ann-teams:${projectId}:${canSend ? 1 : 0}`, () =>
    canSend ? listTeams(projectId) : Promise.resolve([]),
  )

  async function onSend(values: { content: string; target_roles?: string[]; target_team?: number | null }) {
    const ok = await run(
      () =>
        sendAnnouncement(projectId, {
          content: values.content.trim(),
          target_roles: values.target_roles ?? [],
          target_team: values.target_team ?? null,
        }),
      'Đã gửi thông báo',
    )
    if (ok) {
      form.resetFields()
      setVersion((v) => v + 1)
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Thông báo organization</h1>
          <p>Gửi và theo dõi thông báo theo vai trò hoặc team trong organization.</p>
        </div>
      </div>

      {canSend && (
        <Card title="Gửi thông báo mới" style={{ marginBottom: 16 }}>
          <Form form={form} layout="vertical" onFinish={onSend}>
            <Form.Item name="content" label="Nội dung" rules={[{ required: true, message: 'Nhập nội dung thông báo' }]}>
              <Input.TextArea rows={3} placeholder="Nhập thông báo gửi thành viên…" />
            </Form.Item>
            <Space wrap style={{ width: '100%' }}>
              <Form.Item name="target_roles" label="Vai trò nhận (bỏ trống = mọi vai trò)" style={{ minWidth: 260 }}>
                <Select
                  mode="multiple"
                  allowClear
                  placeholder="Tất cả vai trò"
                  options={TARGET_ROLES.map((r) => ({ value: r, label: ROLE_LABELS[r] }))}
                />
              </Form.Item>
              <Form.Item name="target_team" label="Team nhận (tuỳ chọn)" style={{ minWidth: 220 }}>
                <Select
                  allowClear
                  placeholder="Tất cả team"
                  options={(teams ?? []).map((t) => ({ value: t.id, label: t.name }))}
                />
              </Form.Item>
            </Space>
            <div>
              <Button type="primary" htmlType="submit" loading={pending}>
                Gửi thông báo
              </Button>
            </div>
          </Form>
        </Card>
      )}

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
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {formatDateTime(a.created_at)}
                      </Typography.Text>
                      {a.target_roles.length === 0 ? (
                        <Tag>Mọi vai trò</Tag>
                      ) : (
                        a.target_roles.map((r) => <Tag key={r}>{ROLE_LABELS[r]}</Tag>)
                      )}
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
