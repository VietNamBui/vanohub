import { Alert, Card, Col, Descriptions, Row, Select, Statistic, Tag } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router'
import { getErrorMessage } from '../../../shared/api/errors'
import StateView from '../../../shared/components/StateView'
import { useRequest } from '../../../shared/hooks/useRequest'
import { listBatches } from '../../projects/api'
import { useProject } from '../../projects/projectContext'
import { getJobQueue } from '../api'
import { JOB_STATUS_LABELS, STAGE_LABELS } from '../constants'
import type { JobStatus } from '../types'

/**
 * PM-06 Data Queue. Quyết định đề xuất: queue là CÁCH XEM job theo stage
 * (không phải bảng hàng đợi riêng). Quy tắc phân phối tự động chưa có đặc tả nên chưa làm.
 */
export default function QueuePage() {
  const { projectId } = useProject()
  const [batch, setBatch] = useState<number>()
  const { data, error, isLoading, retry } = useRequest(`queue:${projectId}:${batch ?? ''}`, () => getJobQueue(projectId, batch))
  const { data: batches } = useRequest(`batches:${projectId}`, () => listBatches(projectId))

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Data Queue</h1>
          <p>Backlog theo từng stage. Bấm số liệu để mở danh sách job tương ứng.</p>
        </div>
        <Select
          allowClear placeholder="Tất cả task" style={{ width: 200 }} value={batch} onChange={setBatch}
          options={batches?.map((b) => ({ value: b.id, label: b.name }))}
        />
      </div>
      <Alert
        type="info" showIcon style={{ marginBottom: 16 }}
        title="Quy tắc phân phối tự động (ưu tiên rework, giới hạn job theo người) chưa có đặc tả — hiện PM giao việc thủ công ở trang Jobs / Tải công việc."
      />
      {isLoading && <StateView kind="loading" />}
      {error != null && <StateView kind="error" description={getErrorMessage(error)} action={{ label: 'Thử lại', onClick: retry }} />}
      {data && (
        <>
          <Row gutter={[16, 16]}>
            {data.stages.map((stage) => (
              <Col xs={24} lg={8} key={stage.stage}>
                <Card title={`Hàng đợi ${STAGE_LABELS[stage.stage]}`}>
                  <Statistic title="Job đang ở stage" value={stage.total} />
                  <Descriptions column={1} size="small" style={{ marginTop: 16 }}>
                    {stage.stage !== 'qc2' && (
                      <Descriptions.Item label={stage.stage === 'annotation' ? 'Chưa có annotator' : 'Chưa có người QC1'}>
                        {stage.unassigned}
                      </Descriptions.Item>
                    )}
                    {stage.stage === 'annotation' && <Descriptions.Item label="Rework">{stage.rework}</Descriptions.Item>}
                    <Descriptions.Item label="Escalated">{stage.escalated}</Descriptions.Item>
                    <Descriptions.Item label="Quá hạn">{stage.overdue}</Descriptions.Item>
                    <Descriptions.Item label="Đang khoá">{stage.locked}</Descriptions.Item>
                  </Descriptions>
                  <div style={{ marginTop: 12 }}>
                    {Object.entries(stage.by_status).map(([status, n]) => (
                      <Tag key={status}>{JOB_STATUS_LABELS[status as JobStatus]}: {n}</Tag>
                    ))}
                  </div>
                  <div style={{ marginTop: 12 }}>
                    <Link to={`../jobs${batch ? `?batch=${batch}` : ''}`} relative="path">Xem danh sách job →</Link>
                  </div>
                </Card>
              </Col>
            ))}
          </Row>
          <Card style={{ marginTop: 16 }}>
            <Statistic title="Job đã hoàn tất (Đã duyệt / Đã bàn giao)" value={data.done} suffix={`/ ${data.total}`} />
          </Card>
        </>
      )}
    </div>
  )
}
