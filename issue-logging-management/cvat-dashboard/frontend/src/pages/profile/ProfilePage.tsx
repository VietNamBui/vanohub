import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Form, Input, Modal, message } from 'antd'
import { Card, PageTitle, StatCard, Tag, avatarColor, fmt, pct } from '../../design'
import { useStore } from '../../mock/store'
import { ROLE_LABEL, STEP_LABEL, teamById, userStats } from '../../mock/selectors'
import type { WorkStep } from '../../mock/types'
import './profile.scss'

const initials = (name: string) => name.trim().split(/\s+/).slice(-2).map((w) => w[0]).join('').toUpperCase()

function PasswordModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [form] = Form.useForm<{ current: string; next: string; confirm: string }>()
  return (
    <Modal
      className="cvd-modal" title="Đổi mật khẩu" open={open} okText="Đổi mật khẩu" cancelText="Huỷ" destroyOnClose
      onCancel={() => { form.resetFields(); onClose() }}
      onOk={() => form.validateFields().then(() => {
        message.success('Đã đổi mật khẩu (giả lập)')
        form.resetFields()
        onClose()
      }).catch(() => undefined)}
    >
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item name="current" label="Mật khẩu hiện tại" rules={[{ required: true, message: 'Nhập mật khẩu hiện tại' }]}><Input.Password /></Form.Item>
        <Form.Item name="next" label="Mật khẩu mới" rules={[{ required: true, min: 6, message: 'Tối thiểu 6 ký tự' }]}><Input.Password /></Form.Item>
        <Form.Item
          name="confirm" label="Nhập lại mật khẩu mới" dependencies={['next']}
          rules={[{ required: true, message: 'Nhập lại mật khẩu mới' }, ({ getFieldValue }) => ({
            validator: (_, v) => (!v || getFieldValue('next') === v ? Promise.resolve() : Promise.reject(new Error('Mật khẩu nhập lại không khớp'))),
          })]}
        ><Input.Password /></Form.Item>
      </Form>
    </Modal>
  )
}

export default function ProfilePage() {
  const s = useStore()
  const navigate = useNavigate()
  const [pwOpen, setPwOpen] = useState(false)
  const u = s.currentUser
  const st = userStats(s, u.id)
  const teams = u.teamIds.map((id) => teamById(s, id)).filter((t): t is NonNullable<typeof t> => Boolean(t))
  const steps = [...new Set(teams.flatMap((t) => t.allowedSteps))] as WorkStep[]
  const held = s.jobs.filter((j) =>
    (j.annotatorId === u.id && j.stage === 'anno_in_progress') ||
    (j.qc1Id === u.id && j.stage === 'qc1_in_progress') ||
    (j.qc2Id === u.id && j.stage === 'qc2_in_progress')).length
  const myKpi = u.role === 'annotator' ? '/me' : u.role === 'lead' ? '/me/kpi' : '/stats'

  return (
    <>
      <PageTitle title="Hồ sơ" />
      <Card>
        <div className="cvp-hero">
          <span className="cvp-avatar" style={{ background: avatarColor(u.name) }}>{initials(u.name)}</span>
          <div className="cvp-info">
            <h2>{u.name}</h2>
            <Tag tone="blue">{ROLE_LABEL[u.role]}</Tag>
            <div className="cvp-meta">
              <span className="cvd-muted">ID cá nhân</span><b>{u.employeeId}</b>
              <span className="cvd-muted">CVAT username</span><b>{u.cvatUsername}</b>
              <span className="cvd-muted">Team</span>
              <span className="cvp-tags">{teams.length ? teams.map((t) => <Tag key={t.id} tone="gray">{t.name}</Tag>) : <span className="cvd-muted">Chưa thuộc team</span>}</span>
              <span className="cvd-muted">Bước được phép</span>
              <span className="cvp-tags">{steps.length ? steps.map((x) => <Tag key={x} tone="green">{STEP_LABEL[x]}</Tag>) : <span className="cvd-muted">—</span>}</span>
              <span className="cvd-muted">Quyền QC</span>
              <span>{u.isQc ? <Tag tone="purple">Có (QC)</Tag> : <span className="cvd-muted">Không</span>}</span>
            </div>
            <div className="cvp-actions">
              <Button onClick={() => setPwOpen(true)}>Đổi mật khẩu</Button>
              <Button type="primary" onClick={() => navigate(myKpi)}>Năng suất của tôi</Button>
            </div>
          </div>
        </div>
      </Card>
      <div className="cvd-grid cvd-row-stats" style={{ marginTop: 16 }}>
        <StatCard label="KPI hôm nay" value={fmt(st.kpiToday)} suffix={`/ ${fmt(st.kpiTarget)}`} progress={{ value: st.kpiToday, max: st.kpiTarget, tone: 'blue' }} />
        <StatCard label="Tỷ lệ rework" value={pct(st.reworkRate / 100)} foot={`${fmt(st.reworkCount)} lần bị trả`} />
        <StatCard label="Job đang giữ" value={fmt(held)} foot="Đang xử lý ở mọi bước" />
      </div>
      <PasswordModal open={pwOpen} onClose={() => setPwOpen(false)} />
    </>
  )
}
