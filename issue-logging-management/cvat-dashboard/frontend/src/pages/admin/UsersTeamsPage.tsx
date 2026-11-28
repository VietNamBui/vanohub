import { SearchOutlined } from '@ant-design/icons'
import { Checkbox, Form, Input, Modal, Select, message } from 'antd'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { RowList, kpiTone, stopRow, type ListRow, type RowTone } from '../../components'
import { Card, PageTitle, Pill, StatCard, StripedBar, Tag, Who, fmt } from '../../design'
import type { Tone } from '../../design/widgets'
import { ROLE_LABEL, dataTypeOfProject, projectTeamIds, userById, userStats } from '../../mock/selectors'
import { useStore } from '../../mock/store'
import type { Role, Team, User } from '../../mock/types'
import './admin.scss'

const ROLES: Role[] = ['admin', 'pm', 'lead', 'annotator']
const ROLE_TONE: Record<Role, Tone> = { admin: 'pink', pm: 'blue', lead: 'purple', annotator: 'green' }

type Tab = 'users' | 'teams' | 'projects'

export default function UsersTeamsPage() {
  const s = useStore()
  const nav = useNavigate()
  // Người dùng/team lấy trực tiếp từ store (R9/R7 do policy+store quyết định); đổi team qua TeamsMembers `moveMember`.
  const users = s.users
  const teams = s.teams
  const [tab, setTab] = useState<Tab>('users')
  const [q, setQ] = useState('')
  const [roleFilter, setRoleFilter] = useState<Role | undefined>()
  const [editing, setEditing] = useState<User | null>(null)
  const [form] = Form.useForm<User>()

  const teamName = (id: string) => teams.find((t) => t.id === id)?.name ?? id
  const filtered = useMemo(
    () => users.filter((u) =>
      (!roleFilter || u.role === roleFilter) &&
      `${u.name} ${u.cvatUsername}`.toLowerCase().includes(q.trim().toLowerCase()),
    ),
    [users, q, roleFilter],
  )

  const jobsOfTeam = (id: string) => s.jobs.filter((j) => j.teamId === id).length
  const maxTeamJobs = Math.max(1, ...teams.map((t) => jobsOfTeam(t.id)))

  const saveUser = (v: User) => {
    if (!editing) return
    // Role/team không sửa ở đây (đổi qua TeamsMembers); chỉ tên / username / isQc qua policy `updateUser`.
    try {
      s.updateUser(editing.id, { name: v.name, cvatUsername: v.cvatUsername, isQc: v.isQc })
      message.success('Đã cập nhật người dùng')
      setEditing(null)
    } catch (e) { message.error(e instanceof Error ? e.message : 'Không thực hiện được') }
  }

  const userRows: ListRow[] = filtered.map((u) => {
    const st = userStats(s, u.id)
    return {
      key: u.id, tone: kpiTone(st.kpiToday, st.kpiTarget), label: `Mở ${u.name}`, onOpen: () => nav(`/pm/users/${u.id}`),
      cells: [
        <Who name={u.name} sub={u.cvatUsername} />,
        <Tag tone={ROLE_TONE[u.role]}>{ROLE_LABEL[u.role]}</Tag>,
        u.teamIds.length ? <div className="ad-tags">{u.teamIds.map((id) => <Tag key={id} tone="gray">{teamName(id)}</Tag>)}</div> : <span className="cvd-muted">—</span>,
        u.isQc ? <Tag tone="orange">QC1</Tag> : <span className="cvd-muted">—</span>,
        <span className="cvd-rowlist-actions" onClick={stopRow}><Pill onClick={() => { setEditing(u); form.setFieldsValue(u) }}>Sửa</Pill></span>,
      ],
    }
  })
  // Vạch màu team: chưa có thành viên hồng · chưa có Team lead cam · còn lại xanh.
  const teamTone = (t: Team): RowTone => (t.memberIds.length === 0 ? 'bad' : !t.leadId ? 'warn' : 'ok')
  const teamRows: ListRow[] = teams.map((t) => {
    const lead = userById(s, t.leadId)
    const jobs = jobsOfTeam(t.id)
    const projects = s.projects.filter((p) => projectTeamIds(s, p.id).includes(t.id))
    return {
      key: t.id, tone: teamTone(t), label: `Mở team ${t.name}`, onOpen: () => nav(`/pm/teams/${t.id}`),
      cells: [
        <b>{t.name}</b>,
        lead ? <Who name={lead.name} /> : <Tag tone="orange">Chưa có Team lead</Tag>,
        fmt(t.memberIds.length),
        projects.length ? <div className="ad-tags">{projects.map((p) => <Tag key={p.id} tone="purple">{p.name}</Tag>)}</div> : <span className="cvd-muted">Chưa có dự án</span>,
        <div className="cvd-cell-progress"><StripedBar value={jobs} max={maxTeamJobs} tone="blue" thin /><span className="cvd-muted">{fmt(jobs)} job</span></div>,
      ],
    }
  })

  const qcCount = users.filter((u) => u.isQc).length

  return (
    <>
      <PageTitle<Tab>
        title="Quản trị"
        tabs={{
          options: [
            { value: 'users', label: 'Người dùng' },
            { value: 'teams', label: 'Team' },
            { value: 'projects', label: 'Dự án' },
          ],
          value: tab,
          onChange: setTab,
        }}
      />

      <div className="cvd-grid cvd-row-stats">
        <StatCard label="Số người" value={fmt(users.length)} foot="Tất cả vai trò" />
        <StatCard label="Số team" value={fmt(teams.length)} foot="Đang hoạt động" />
        <StatCard label="Số dự án" value={fmt(s.projects.length)} foot="Trên CVAT" />
        <StatCard label="Số QC" value={fmt(qcCount)} foot="Được chọn làm QC1" />
      </div>

      {tab === 'users' && (
        <div className="cvd-row-full">
          <Card title={`Người dùng (${filtered.length})`}>
            <div className="ad-filters">
              <Input allowClear prefix={<SearchOutlined />} placeholder="Tìm tên / CVAT username" value={q} onChange={(e) => setQ(e.target.value)} />
              <Select allowClear placeholder="Lọc vai trò" value={roleFilter} onChange={setRoleFilter} options={ROLES.map((r) => ({ value: r, label: ROLE_LABEL[r] }))} />
            </div>
            <RowList
              heads={['Tên', 'Vai trò', 'Team', 'QC', '']}
              cols="minmax(0,2fr) minmax(0,1fr) minmax(0,1.8fr) minmax(0,0.6fr) 72px"
              rows={userRows} emptyText="Không có người dùng khớp bộ lọc." emptyHint="Thử bỏ bớt từ khoá hoặc chọn lại vai trò."
              onClear={() => { setQ(''); setRoleFilter(undefined) }} resetKey={`${q}|${roleFilter ?? ''}`}
            />
          </Card>
        </div>
      )}

      {tab === 'teams' && (
        <div className="cvd-row-full">
          <Card title={`Team (${teams.length})`}>
            <RowList
              heads={['Team', 'Team lead', 'Thành viên', 'Dự án', 'Khối lượng']}
              cols="minmax(0,1.3fr) minmax(0,1.5fr) minmax(0,0.8fr) minmax(0,1.8fr) minmax(0,1.3fr)"
              rows={teamRows} emptyText="Chưa có team."
            />
          </Card>
        </div>
      )}

      {tab === 'projects' && (
        <div className="cvd-grid cvd-row-full" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
          {s.projects.map((p) => (
            <Card key={p.id} title={p.name}>
              <dl className="ad-kv">
                <dt>PM</dt>
                <dd>{p.pmIds.length ? p.pmIds.map((id) => <Who key={id} name={userById(s, id)?.name ?? id} />) : '—'}</dd>
                <dt>Team</dt>
                <dd><div className="ad-tags">{projectTeamIds(s, p.id).map((id) => <Tag key={id} tone="gray">{teamName(id)}</Tag>)}</div></dd>
                <dt>Loại dữ liệu</dt>
                <dd><Tag tone="blue">{dataTypeOfProject(s, p.id)?.name ?? '—'}</Tag></dd>
              </dl>
            </Card>
          ))}
        </div>
      )}


      <Modal className="cvd-modal" title={`Sửa người dùng: ${editing?.name ?? ''}`} open={!!editing} onCancel={() => setEditing(null)} onOk={() => form.submit()} okText="Lưu" cancelText="Huỷ" forceRender>
        <Form form={form} layout="vertical" onFinish={saveUser}>
          <Form.Item name="name" label="Tên" rules={[{ required: true, message: 'Nhập tên' }]}><Input /></Form.Item>
          <Form.Item name="cvatUsername" label="CVAT username" rules={[{ required: true, message: 'Nhập username' }]}><Input /></Form.Item>
          {editing && (
            <div className="aq-hint">
              Vai trò: <b>{ROLE_LABEL[editing.role]}</b> · Team: {editing.teamIds.length ? editing.teamIds.map(teamName).join(', ') : '—'}
              {' — đây không sửa ở đây, hãy đổi qua trang "Team và thành viên".'}
            </div>
          )}
          <Form.Item name="isQc" valuePropName="checked"><Checkbox>Được chọn làm QC1</Checkbox></Form.Item>
        </Form>
      </Modal>
    </>
  )
}
