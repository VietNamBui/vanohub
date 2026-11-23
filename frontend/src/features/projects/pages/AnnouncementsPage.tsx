import { Button, Card, Col, Form, Input, List, Row, Select, Space, Tag, Typography } from 'antd'
import { useState } from 'react'
import { getErrorMessage } from '../../../shared/api/errors'
import StateView from '../../../shared/components/StateView'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { ROLE_LABELS, ROLE_ORDER } from '../../../shared/types/roles'
import { formatDateTime } from '../../../shared/utils/format'
import { listTeams } from '../../teams/api'
import { listAnnouncements, sendAnnouncement } from '../api'
import { useProject } from '../projectContext'

/** PM-12 Gửi thông báo. Mọi người trong dự án xem được thông báo dành cho vai trò / team của mình. */
export default function AnnouncementsPage() {
  const { projectId, can } = useProject()
  const [version, setVersion] = useState(0)
  const [form] = Form.useForm()
  const { run, pending } = useAction()
  const canSend = can('send_announcement')
  const { data, error, isLoading, retry } = useRequest(`announcements:${projectId}:${version}`, () => listAnnouncements(projectId))
  const { data: teams } = useRequest(`teams:${projectId}:${canSend}`, () => (canSend ? listTeams(projectId) : Promise.resolve([])))

  const list = (
    <Card title={canSend ? 'Lịch sử đã gửi' : 'Thông báo dành cho bạn'}>
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
  )

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Thông báo dự án</h1>
          <p>{canSend ? 'Gửi thông báo theo vai trò và / hoặc team.' : 'Thông báo từ PM.'}</p>
        </div>
      </div>
      {!canSend ? list : (
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={10}>
            <Card title="Soạn thông báo">
              <Form form={form} layout="vertical" onFinish={async (v) => {
                if (await run(() => sendAnnouncement(projectId, { content: v.content, target_roles: v.target_roles ?? [], target_team: v.target_team ?? null }), 'Đã gửi thông báo')) {
                  form.resetFields()
                  setVersion((n) => n + 1)
                }
              }}>
                <Form.Item name="target_roles" label="Vai trò nhận" extra="Để trống = mọi vai trò.">
                  <Select mode="multiple" allowClear options={ROLE_ORDER.filter((r) => r !== 'director').map((r) => ({ value: r, label: ROLE_LABELS[r] }))} />
                </Form.Item>
                <Form.Item name="target_team" label="Team nhận" extra="Để trống = mọi team.">
                  <Select allowClear options={teams?.map((t) => ({ value: t.id, label: t.name }))} />
                </Form.Item>
                <Form.Item name="content" label="Nội dung" rules={[{ required: true, message: 'Nhập nội dung' }]}>
                  <Input.TextArea rows={5} />
                </Form.Item>
                <Button type="primary" htmlType="submit" loading={pending}>Gửi</Button>
              </Form>
            </Card>
          </Col>
          <Col xs={24} lg={14}>{list}</Col>
        </Row>
      )}
    </div>
  )
}
