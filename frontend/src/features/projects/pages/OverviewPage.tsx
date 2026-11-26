import { ExclamationCircleOutlined, InfoCircleOutlined, WarningOutlined } from '@ant-design/icons'
import { Alert, Card, Col, List, Progress, Row, Segmented, Space, Statistic, Typography } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router'
import { getErrorMessage } from '../../../shared/api/errors'
import RoleBadges from '../../../shared/components/RoleBadges'
import StateView from '../../../shared/components/StateView'
import { useRequest } from '../../../shared/hooks/useRequest'
import { STAGE_LABELS } from '../../jobs/constants'
import { getOverview } from '../api'
import MetricCard from '../components/MetricCard'
import { useProject } from '../projectContext'

const ALERT_ICONS = {
  error: <ExclamationCircleOutlined style={{ color: '#cf1322' }} />,
  warning: <WarningOutlined style={{ color: '#d48806' }} />,
  info: <InfoCircleOutlined style={{ color: '#1677ff' }} />,
}

/** PM-01 Tổng quan dự án. */
export default function OverviewPage() {
  const { project, projectId } = useProject()
  const [period, setPeriod] = useState('week')
  const { data, error, isLoading, retry } = useRequest(`overview:${projectId}:${period}`, () => getOverview(projectId, period))

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>{project.name}</h1>
          <p>
            Vai trò của bạn: <RoleBadges roles={project.my_roles} />
          </p>
        </div>
        <Segmented
          value={period}
          onChange={(v) => setPeriod(v as string)}
          options={[{ label: 'Ngày', value: 'day' }, { label: 'Tuần', value: 'week' }, { label: 'Tháng', value: 'month' }]}
        />
      </div>

      {isLoading && <StateView kind="loading" />}
      {error != null && <StateView kind="error" description={getErrorMessage(error)} action={{ label: 'Thử lại', onClick: retry }} />}
      {data && (
        <Space orientation="vertical" size={16} style={{ width: '100%' }}>
          {data.counts.jobs === 0 && (
            <Alert
              type="info" showIcon
              title="Organization chưa có job. Tạo project và task trên CVAT, rồi bấm Đồng bộ CVAT ở trang Projects."
              action={<Link to="../datasets" relative="path">Đến Projects</Link>}
            />
          )}
          <Row gutter={[16, 16]}>
            <Col xs={12} lg={6}><MetricCard title="Tổng số object" metric={data.metrics.total_objects} /></Col>
            <Col xs={12} lg={6}><MetricCard title="Quality CL" metric={data.metrics.quality_cl} suffix="%" /></Col>
            <Col xs={12} lg={6}><MetricCard title="Rework rate" metric={data.metrics.rework_rate} suffix="%" /></Col>
            <Col xs={12} lg={6}><MetricCard title="Delivery readiness" metric={data.metrics.delivery_readiness} suffix="%" /></Col>
          </Row>

          <Row gutter={[16, 16]}>
            <Col xs={24} lg={14}>
              <Card title="Tiến độ theo stage" style={{ height: '100%' }}>
                {(['annotation', 'qc1', 'qc2', 'done'] as const).map((stage) => (
                  <div key={stage} style={{ marginBottom: 12 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>{STAGE_LABELS[stage]}</span>
                      <span>{data.by_stage[stage]} job</span>
                    </div>
                    <Progress
                      percent={data.counts.jobs ? Math.round((data.by_stage[stage] * 100) / data.counts.jobs) : 0}
                      showInfo={false}
                      strokeColor={stage === 'done' ? '#52c41a' : '#1677ff'}
                    />
                  </div>
                ))}
                <Typography.Text type="secondary">
                  Ước tính hoàn thành: chưa chốt cách tính. Tiến độ kế hoạch chưa có dữ liệu kế hoạch để so sánh.
                </Typography.Text>
              </Card>
            </Col>
            <Col xs={24} lg={10}>
              <Card title="Quy mô" style={{ height: '100%' }}>
                <Row gutter={[16, 16]}>
                  <Col span={8}><Statistic title="Project" value={data.counts.datasets} /></Col>
                  <Col span={8}><Statistic title="Task" value={data.counts.batches} /></Col>
                  <Col span={8}><Statistic title="Job" value={data.counts.jobs} /></Col>
                  <Col span={12}><Statistic title="Escalated" value={data.counts.escalated} /></Col>
                  <Col span={12}><Statistic title="Quá hạn" value={data.counts.overdue} /></Col>
                </Row>
              </Card>
            </Col>
          </Row>

          <Row gutter={[16, 16]}>
            <Col xs={12} lg={6}><MetricCard title="Job nộp trong kỳ" metric={data.metrics.submitted_in_period} /></Col>
            <Col xs={12} lg={6}><MetricCard title="Thành viên đang hoạt động" metric={data.metrics.active_members} /></Col>
            <Col xs={12} lg={6}><MetricCard title="First pass yield" metric={data.metrics.first_pass_yield} suffix="%" /></Col>
            <Col xs={12} lg={6}><MetricCard title="QC2 pass rate" metric={data.metrics.qc2_pass_rate} suffix="%" /></Col>
            <Col xs={12} lg={6}><MetricCard title="Defect error rate" metric={data.metrics.defect_error_rate} suffix="%" /></Col>
            <Col xs={12} lg={6}><MetricCard title="Ước tính hoàn thành" metric={data.metrics.estimated_completion} /></Col>
          </Row>

          <Card title={`Cảnh báo dự án (${data.alerts.length})`}>
            <List
              dataSource={data.alerts}
              locale={{ emptyText: 'Không có cảnh báo' }}
              renderItem={(alert) => (
                <List.Item actions={[<Link key="open" to={`../jobs?${alert.type === 'escalated' ? 'escalated=1' : 'overdue=1'}`} relative="path">Xem</Link>]}>
                  <Space>{ALERT_ICONS[alert.level]}{alert.message}</Space>
                </List.Item>
              )}
            />
          </Card>
        </Space>
      )}
    </div>
  )
}
