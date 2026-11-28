import { PlusOutlined } from '@ant-design/icons'
import { Button, Col, Form, Input, InputNumber, Row, Select, message } from 'antd'
import { useEffect, useState } from 'react'
import { Card, PageTitle, Tag, fmt } from '../../../design'
import { useStore } from '../../../mock/store'
import { can } from '../../../mock/policy'
import type { DataType } from '../../../mock/types'
import './config.scss'

// Type hiện tại của store chỉ có cuboid | rectangle (polygon/points cần mở rộng types).
const SHAPES: { value: DataType['shapeType']; label: string }[] = [
  { value: 'cuboid', label: 'Cuboid (3D)' },
  { value: 'rectangle', label: 'Rectangle (2D bounding box)' },
]

export default function DataTypeConfigPage() {
  const s = useStore()
  const [selectedId, setSelectedId] = useState<string>(s.dataTypes[0]?.id ?? '')
  const selected = s.dataTypes.find((d) => d.id === selectedId)
  const [form] = Form.useForm<DataType>()
  const [cats, setCats] = useState<string[]>([])
  const [newCat, setNewCat] = useState('')
  // R9: sửa cấu hình loại dữ liệu — admin/pm (`can({kind:'dataType'})`).
  const canEdit = can(s, s.currentUser, { kind: 'dataType' }).ok

  useEffect(() => {
    if (selected) {
      form.setFieldsValue(selected)
      setCats(selected.errorCategories)
    }
  }, [selected, form])

  const addCat = () => {
    const v = newCat.trim()
    if (!v) return
    if (cats.includes(v)) {
      message.warning('Loại lỗi đã tồn tại')
      return
    }
    setCats([...cats, v])
    setNewCat('')
  }

  const save = (values: DataType) => {
    if (!selected) return
    try {
      s.updateDataType({ ...selected, ...values, errorCategories: cats })
      message.success('Đã lưu cấu hình')
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  return (
    <>
      <PageTitle title="Loại dữ liệu & KPI" />

      <div className="cf-note">
        <h3>Quy tắc đếm KPI</h3>
        <ul>
          <li>Cuboid ở mỗi frame khác với prelabel gốc thì tính là 1 cuboid đã sửa.</li>
          <li>Thêm mới hoặc xoá cuboid cũng tính 1.</li>
          <li>Nộp lại sau rework không cộng KPI; KPI ghi vào ngày nộp lần đầu.</li>
        </ul>
      </div>

      <div className="cf-split">
        <div className="cf-list">
          {s.dataTypes.map((d) => (
            <div
              key={d.id}
              role="button"
              tabIndex={0}
              onClick={() => setSelectedId(d.id)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelectedId(d.id) } }}
            >
              <Card className={`cf-type ${d.id === selectedId ? 'on' : ''}`}>
                <div className="cf-type-head">
                  <span className="cf-type-name">{d.name}</span>
                  <Tag tone={d.shapeType === 'cuboid' ? 'purple' : 'blue'}>{d.shapeType}</Tag>
                </div>
                <div className="cf-kpi">{fmt(d.kpiPerDay)}<small>/ ngày</small></div>
                <div className="cf-thresholds">
                  <Tag tone="gray">≤ {d.thresholdCm} cm</Tag>
                  <Tag tone="gray">≤ {d.thresholdDeg}°</Tag>
                  <Tag tone="orange">{d.errorCategories.length} loại lỗi</Tag>
                </div>
              </Card>
            </div>
          ))}
        </div>

        <Card title={selected ? `Chỉnh sửa: ${selected.name}` : 'Chưa chọn'}>
          {selected && (
            <Form form={form} layout="vertical" onFinish={save} className="cf-form">
              <Form.Item name="name" label="Tên" rules={[{ required: true, message: 'Nhập tên' }]}>
                <Input />
              </Form.Item>
              <Row gutter={16}>
                <Col xs={24} sm={12}>
                  <Form.Item name="shapeType" label="Loại shape đếm">
                    <Select options={SHAPES} />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item name="kpiPerDay" label="KPI / ngày" rules={[{ required: true, type: 'number', min: 1, message: 'Phải lớn hơn 0' }]}>
                    <InputNumber min={1} />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item name="thresholdCm" label="Ngưỡng sai số (cm)" rules={[{ required: true, type: 'number', min: 0 }]}>
                    <InputNumber min={0} step={0.1} />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item name="thresholdDeg" label="Ngưỡng sai số (độ)" rules={[{ required: true, type: 'number', min: 0 }]}>
                    <InputNumber min={0} step={0.1} />
                  </Form.Item>
                </Col>
              </Row>
              <p className="cvd-muted" style={{ marginTop: -8 }}>Sai số dưới ngưỡng không tính là đã sửa.</p>
              <Form.Item label="Danh mục loại lỗi">
                <div className="cf-cats">
                  {cats.map((c) => (
                    <Tag key={c} tone="pink">
                      <span className="cf-cat">
                        {c}
                        <button type="button" aria-label={`Xoá ${c}`} onClick={() => setCats(cats.filter((x) => x !== c))}>×</button>
                      </span>
                    </Tag>
                  ))}
                </div>
                <CompactRow>
                  <Input value={newCat} onChange={(e) => setNewCat(e.target.value)} onPressEnter={(e) => { e.preventDefault(); addCat() }} placeholder="Thêm loại lỗi mới" />
                  <Button icon={<PlusOutlined />} onClick={addCat}>Thêm</Button>
                </CompactRow>
              </Form.Item>
              <Button type="primary" htmlType="submit" disabled={!canEdit}>{canEdit ? 'Lưu cấu hình' : 'Chưa có quyền chỉnh cấu hình'}</Button>
            </Form>
          )}
        </Card>
      </div>
    </>
  )
}

function CompactRow({ children }: { children: React.ReactNode }) {
  return <div style={{ display: 'flex', gap: 8 }}>{children}</div>
}
