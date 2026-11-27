import { Alert, Card, Col, Descriptions, Row, Select, Statistic, Tabs, Tag } from 'antd'
import { Link, useSearchParams } from 'react-router'
import { getErrorMessage } from '../../../shared/api/errors'
import StateView from '../../../shared/components/StateView'
import { useRequest } from '../../../shared/hooks/useRequest'
import { listBatches } from '../../projects/api'
import { useProject } from '../../projects/projectContext'
import { getJobQueue } from '../api'
import { JOB_STATUS_LABELS, STAGE_LABELS } from '../constants'
import type { JobStatus, QueueStage } from '../types'

type QueueStageFilter = '' | QueueStage['stage']

const VALID_QUEUE_STAGES = new Set<QueueStage['stage']>(['annotation', 'qc1', 'qc2'])

const STAGE_TABS: { key: QueueStageFilter; label: string }[] = [
  { key: '', label: 'Tất cả stage' },
  { key: 'annotation', label: STAGE_LABELS.annotation },
  { key: 'qc1', label: STAGE_LABELS.qc1 },
  { key: 'qc2', label: STAGE_LABELS.qc2 },
]

function parsePositiveInt(raw: string | null): number | undefined {
  if (!raw) return undefined
  const num = Number(raw)
  return Number.isInteger(num) && num > 0 ? num : undefined
}

/**
 * Data Queue — xem backlog job theo từng stage (Annotation, QC1, QC2) và chuyển thẳng sang danh sách job tương ứng.
 */
export default function QueuePage() {
  const { projectId } = useProject()
  const [searchParams, setSearchParams] = useSearchParams()
  const batch = parsePositiveInt(searchParams.get('batch'))
  const rawStage = searchParams.get('stage') ?? ''
  const selectedStage: QueueStageFilter = VALID_QUEUE_STAGES.has(rawStage as QueueStage['stage'])
    ? (rawStage as QueueStage['stage'])
    : ''

  const { data, error, isLoading, retry } = useRequest(`queue:${projectId}:${batch ?? ''}`, () =>
    getJobQueue(projectId, batch),
  )
  const { data: batches } = useRequest(`batches:${projectId}`, () => listBatches(projectId))

  function updateQuery(patch: { batch?: number; stage?: QueueStageFilter }) {
    const nextBatch = 'batch' in patch ? patch.batch : batch
    const nextStage = 'stage' in patch ? patch.stage : selectedStage
    const params = new URLSearchParams()
    if (nextStage) params.set('stage', nextStage)
    if (nextBatch) params.set('batch', String(nextBatch))
    setSearchParams(params, { replace: true })
  }

  function jobsUrl(extra: Record<string, string | number | undefined>) {
    const params = new URLSearchParams()
    if (batch) params.set('batch', String(batch))
    for (const [k, v] of Object.entries(extra)) {
      if (v !== undefined && v !== '') params.set(k, String(v))
    }
    const qs = params.toString()
    return qs ? `../jobs?${qs}` : '../jobs'
  }

  const visibleStages = data
    ? selectedStage
      ? data.stages.filter((s) => s.stage === selectedStage)
      : data.stages
    : []

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Data Queue</h1>
          <p>Backlog theo từng stage. Bấm số liệu để mở danh sách job tương ứng.</p>
        </div>
        <Select
          allowClear
          placeholder="Tất cả task"
          style={{ width: 200 }}
          value={batch}
          onChange={(value) => updateQuery({ batch: value })}
          options={batches?.map((b) => ({ value: b.id, label: b.name }))}
        />
      </div>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        title="Hiện PM giao việc thủ công ở trang Jobs / Tải công việc; Annotator có thể tự nhận việc từ hàng chờ trong giới hạn WIP."
      />
      <Tabs
        activeKey={selectedStage}
        onChange={(key) => updateQuery({ stage: key as QueueStageFilter })}
        items={STAGE_TABS}
      />
      {isLoading && <StateView kind="loading" />}
      {error != null && (
        <StateView kind="error" description={getErrorMessage(error)} action={{ label: 'Thử lại', onClick: retry }} />
      )}
      {data && (
        <>
          <Row gutter={[16, 16]}>
            {visibleStages.map((stage) => (
              <Col xs={24} lg={selectedStage ? 24 : 8} key={stage.stage}>
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
                  <div style={{ marginTop: 12 }} className="flex flex-wrap gap-1.5">
                    {Object.entries(stage.by_status).map(([status, n]) => (
                      <Link key={status} to={jobsUrl({ stage: stage.stage, status })} relative="path">
                        <Tag>{JOB_STATUS_LABELS[status as JobStatus] ?? status}: {n}</Tag>
                      </Link>
                    ))}
                  </div>
                  <div style={{ marginTop: 12 }}>
                    <Link to={jobsUrl({ stage: stage.stage })} relative="path">
                      Xem danh sách job →
                    </Link>
                  </div>
                </Card>
              </Col>
            ))}
          </Row>
          <Card style={{ marginTop: 16 }}>
            <div className="flex flex-wrap items-center justify-between gap-4">
              <Statistic title="Job đã hoàn tất (Đã duyệt / Đã bàn giao)" value={data.done} suffix={`/ ${data.total}`} />
              <Link to={jobsUrl({ stage: 'done' })} relative="path">
                Xem job hoàn tất →
              </Link>
            </div>
          </Card>
        </>
      )}
    </div>
  )
}
