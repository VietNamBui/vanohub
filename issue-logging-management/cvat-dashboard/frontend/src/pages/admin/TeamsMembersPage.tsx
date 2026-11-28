import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Checkbox, Input, Modal, Select, message } from 'antd'
import { PlusOutlined, SearchOutlined, TeamOutlined } from '@ant-design/icons'
import { useStore } from '../../mock/store'
import { can } from '../../mock/policy'
import { ROLE_LABEL, STEP_LABEL, teamById, userById, userStats } from '../../mock/selectors'
import type { Team, User, WorkStep } from '../../mock/types'
import { ConfirmDanger, RowList, kpiTone, stopRow, type ListRow } from '../../components'
import { Card, DashTable, PageTitle, Tag, Who, fmt } from '../../design'
import './teams/teams.scss'

const STEPS: WorkStep[] = ['annotate', 'qc1', 'qc2']
const STEP_OPTIONS = STEPS.map((v) => ({ value: v, label: STEP_LABEL[v] }))

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : 'Có lỗi xảy ra'
}

interface FormValue { name: string; allowedSteps: WorkStep[]; canQa: boolean }

function TeamFields({ value, onChange }: { value: FormValue; onChange: (v: FormValue) => void }) {
  return (
    <div className="tm-form">
      <div>
        <label className="tm-label">Tên team</label>
        <Input value={value.name} placeholder="Ví dụ: Team Alpha" onChange={(e) => onChange({ ...value, name: e.target.value })} />
      </div>
      <div>
        <label className="tm-label">Bước được phép</label>
        <Checkbox.Group
          className="tm-checks" options={STEP_OPTIONS} value={value.allowedSteps}
          onChange={(v) => onChange({ ...value, allowedSteps: v as WorkStep[] })}
        />
      </div>
      <Checkbox checked={value.canQa} onChange={(e) => onChange({ ...value, canQa: e.target.checked })}>
        Được tham gia Audit
      </Checkbox>
    </div>
  )
}

export default function TeamsMembersPage() {
  const s = useStore()
  const nav = useNavigate()
  const [selectedId, setSelectedId] = useState<string | 'new' | null>(s.teams[0]?.id ?? null)
  const [draft, setDraft] = useState<FormValue>({ name: '', allowedSteps: ['annotate'], canQa: false })
  const [editOpen, setEditOpen] = useState(false)
  const [editDraft, setEditDraft] = useState<FormValue>({ name: '', allowedSteps: [], canQa: false })
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [moving, setMoving] = useState<User | null>(null)
  const [moveTeam, setMoveTeam] = useState<string | undefined>()
  const [adding, setAdding] = useState(false)
  const [query, setQuery] = useState('')

  const team: Team | undefined = selectedId && selectedId !== 'new' ? teamById(s, selectedId) : undefined
  const creating = selectedId === 'new'
  const members = team ? team.memberIds.map((id) => userById(s, id)).filter((u): u is User => Boolean(u)) : []
  const lead = team?.leadId ? userById(s, team.leadId) : undefined
  const pmOptions = s.users.filter((u) => u.role === 'pm').map((u) => ({ value: u.id, label: u.name }))
  // R6: đổi PM của team — admin (Xem `can({kind:'setTeamPm'})`). Dùng pmId hiện tại (hoặc PM đầu) làm tham chiếu để mở Select.
  const canSetPm = !!team && can(s, s.currentUser, { kind: 'setTeamPm', teamId: team.id, pmId: (team.pmId || pmOptions[0]?.value || '') }).ok

  // R7: số job người đó đang làm (anno_in_progress hoặc QC1 chưa xong) sẽ bàn giao cho lead cũ khi đổi/nghỉ.
  const handoverCount = (u: User): number =>
    s.jobs.filter((j) =>
      (j.annotatorId === u.id && ['anno_in_progress'].includes(j.stage))
      || (j.qc1Id === u.id && ['anno_in_progress', 'qc1_pending', 'qc1_in_progress'].includes(j.stage)),
    ).length

  const run = (fn: () => void, ok?: string): boolean => {
    try { fn(); if (ok) message.success(ok); return true } catch (e) { message.error(errMsg(e)); return false }
  }

  const setPm = (pmId: string) => {
    if (!team) return
    run(() => s.setTeamPm(team.id, pmId), 'Đã đổi PM phụ trách')
  }
  const onSetPm = (v: string | undefined) => { if (v) setPm(v) }

  const submitCreate = () => {
    const name = draft.name.trim()
    if (run(() => s.createTeam({ ...draft, name }), 'Đã tạo team')) {
      // Store đồng bộ: team mới nằm trong state ở lần render sau; chọn theo tên khi có.
      setPendingName(name)
      setDraft({ name: '', allowedSteps: ['annotate'], canQa: false })
      setSelectedId(null)
    }
  }
  const [pendingName, setPendingName] = useState<string | null>(null)
  if (pendingName) {
    const created = s.teams.find((t) => t.name === pendingName)
    if (created) { setSelectedId(created.id); setPendingName(null) }
  }

  const memberRows: ListRow[] = team ? members.map((u) => {
    const st = userStats(s, u.id)
    return {
      key: u.id, tone: kpiTone(st.kpiToday, st.kpiTarget), label: `Mở ${u.name}`, onOpen: () => nav(`/pm/users/${u.id}`),
      cells: [
        <span className="cvd-muted">{u.employeeId}</span>,
        u.cvatUsername,
        <Who name={u.name} />,
        <Tag tone={u.id === team.leadId ? 'orange' : u.role === 'annotator' ? 'gray' : 'blue'}>
          {u.id === team.leadId ? 'Team lead' : ROLE_LABEL[u.role]}
        </Tag>,
        <span className="cvd-rowlist-actions" onClick={stopRow}>
          {can(s, s.currentUser, { kind: 'moveMember', userId: u.id, toTeamId: null }).ok
            ? <Button size="small" onClick={() => { setMoving(u); setMoveTeam(undefined) }}>Chuyển / Nghỉ</Button>
            : <span className="cvd-muted">—</span>}
        </span>,
      ],
    }
  }) : []

  const candidates = (() => {
    const q = query.trim().toLowerCase()
    if (!team || !q) return []
    return s.users
      // R7/`addMember`: chỉ thêm người chưa thuộc team nào (người mới); người đã có team thì dùng moveMember.
      .filter((u) => u.teamIds.length === 0)
      .filter((u) => String(u.employeeId).includes(q) || u.cvatUsername.toLowerCase().includes(q) || u.name.toLowerCase().includes(q))
      .slice(0, 8)
  })()

  return (
    <>
      <PageTitle title="Team và thành viên" />
      <Card>
        <div className="tm-layout">
          <div>
            <div className="tm-list">
              {s.teams.map((t) => (
                <button key={t.id} type="button" className={`tm-item ${selectedId === t.id ? 'on' : ''}`} onClick={() => { setSelectedId(t.id); setAdding(false); setQuery('') }}>
                  <TeamOutlined /> <span>{t.name}</span><small>{fmt(t.memberIds.length)}</small>
                </button>
              ))}
            </div>
            <Button className="tm-new" block type={creating ? 'primary' : 'default'} icon={<PlusOutlined />} onClick={() => setSelectedId('new')}>
              Tạo team mới
            </Button>
          </div>

          <div className="tm-panel">
            {creating && (
              <>
                <div className="tm-head"><h2>Tạo team mới</h2></div>
                <TeamFields value={draft} onChange={setDraft} />
                <div><Button type="primary" onClick={submitCreate}>Tạo</Button></div>
              </>
            )}

            {team && (
              <>
                <div className="tm-head">
                  <h2>Team “{team.name}”</h2>
                  <div className="tm-actions">
                    <Button icon={<PlusOutlined />} onClick={() => setAdding((v) => !v)}>Thêm thành viên</Button>
                    <Button onClick={() => { setEditDraft({ name: team.name, allowedSteps: team.allowedSteps, canQa: team.canQa }); setEditOpen(true) }}>Sửa</Button>
                    <Button danger onClick={() => setDeleteOpen(true)}>Xoá team</Button>
                  </div>
                </div>
                <div className="tm-tags">
                  {team.allowedSteps.map((st) => <Tag key={st} tone="blue">{STEP_LABEL[st]}</Tag>)}
                  {team.allowedSteps.length === 0 && <Tag tone="gray">Chưa có bước</Tag>}
                  {team.canQa && <Tag tone="purple">Được Audit</Tag>}
                  {lead ? <Who name={lead.name} sub="Team lead" /> : <Tag tone="orange">Chưa có Team lead</Tag>}
                  <span className="tm-pm">
                    PM phụ trách:{' '}
                    {canSetPm ? (
                      <Select size="small" style={{ width: 180 }} value={team.pmId || undefined} placeholder="Chưa có PM"
                        options={pmOptions} onChange={onSetPm} showSearch optionFilterProp="label" allowClear
                      />
                    ) : (
                      team.pmId ? <Who name={userById(s, team.pmId)?.name ?? team.pmId} /> : <span className="cvd-muted">—</span>
                    )}
                  </span>
                </div>

                {adding && (
                  <div className="tm-search">
                    <Input allowClear prefix={<SearchOutlined />} placeholder="Tìm theo ID hoặc username…" value={query} onChange={(e) => setQuery(e.target.value)} autoFocus />
                    {query.trim() && (
                      <DashTable
                        className="cvd-rowlist-table" rowKey="id" dataSource={candidates} locale={{ emptyText: 'Không có người dùng phù hợp' }}
                        columns={[
                          { title: 'ID', dataIndex: 'employeeId', key: 'id', width: 90 },
                          { title: 'Username', dataIndex: 'cvatUsername', key: 'u' },
                          { title: 'Tên', key: 'n', render: (_: unknown, u: User) => <Who name={u.name} /> },
                          {
                            title: '', key: 'a', align: 'right' as const,
                            render: (_: unknown, u: User) => (
                              <Button size="small" type="primary" disabled={!can(s, s.currentUser, { kind: 'addMember', teamId: team.id, userId: u.id }).ok}
                                onClick={() => run(() => s.addTeamMember(team.id, u.id), `Đã thêm ${u.name}`)}>Thêm</Button>
                            ),
                          },
                        ]}
                      />
                    )}
                  </div>
                )}

                <h3 style={{ margin: 0 }}>Thành viên ({fmt(members.length)})</h3>
                <RowList
                  heads={['ID', 'Username', 'Tên', 'Vai trò', '']}
                  cols="80px minmax(0,1.3fr) minmax(0,1.8fr) minmax(0,1fr) 64px"
                  rows={memberRows} emptyText="Team chưa có thành viên." emptyHint="Bấm Thêm thành viên để thêm người vào team." resetKey={team.id}
                />
              </>
            )}

            {!creating && !team && <div className="cvd-empty">Chọn một team hoặc tạo team mới.</div>}
          </div>
        </div>
      </Card>

      <Modal
        className="cvd-modal" open={editOpen} title="Sửa thông tin team" okText="Lưu" cancelText="Huỷ" destroyOnClose
        onCancel={() => setEditOpen(false)}
        onOk={() => { if (team && run(() => s.updateTeam(team.id, { ...editDraft, name: editDraft.name.trim() }), 'Đã cập nhật team')) setEditOpen(false) }}
      >
        <TeamFields value={editDraft} onChange={setEditDraft} />
      </Modal>

      <Modal
        className="cvd-modal" open={moving !== null} title={`Chuyển team / cho nghỉ: ${moving?.name ?? ''}`}
        okText="Xác nhận" cancelText="Huỷ" destroyOnClose
        onCancel={() => setMoving(null)}
        onOk={() => {
          if (team && moving) {
            const toTeamId = moveTeam ?? null
            if (run(() => s.moveMember(moving.id, toTeamId), toTeamId
              ? `Đã chuyển ${moving.name} sang ${teamById(s, toTeamId)?.name ?? toTeamId}`
              : `Đã cho ${moving.name} nghỉ`)) setMoving(null)
          }
        }}
      >
        {moving && (
          <div className="aq-form">
            <div className="aq-hint">Hiện ở team: {teamById(s, moving.teamIds[0])?.name ?? '—'}</div>
            <div className="aq-hint">Đích đến</div>
            <Select style={{ width: '100%' }} placeholder="Chọn team (để trống = cho nghỉ)" value={moveTeam} onChange={setMoveTeam} allowClear
              options={s.teams.filter((t) => t.id !== moving.teamIds[0]).map((t) => ({ value: t.id, label: t.name }))}
              showSearch optionFilterProp="label"
            />
            <p className="aq-hint" style={{ marginTop: 12 }}>
              {handoverCount(moving)} job đang làm sẽ bàn giao cho lead cũ của team; người này nghỉ hoặc về team mới.
            </p>
          </div>
        )}
      </Modal>

      <ConfirmDanger
        open={deleteOpen} title={`Xoá team “${team?.name ?? ''}”?`} okText="Xoá team"
        onCancel={() => setDeleteOpen(false)}
        onOk={() => { if (team && run(() => s.deleteTeam(team.id), 'Đã xoá team')) { setDeleteOpen(false); setSelectedId(null) } else setDeleteOpen(false) }}
      >
        Team chỉ xoá được khi không còn job đang xử lý.
      </ConfirmDanger>
    </>
  )
}
