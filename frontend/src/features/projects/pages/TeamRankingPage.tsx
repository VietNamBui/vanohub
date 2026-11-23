import { Alert, Card, Col, Progress, Row, Table } from 'antd'
import { getErrorMessage } from '../../../shared/api/errors'
import StateView from '../../../shared/components/StateView'
import UserName from '../../../shared/components/UserName'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatNumber, formatPercent } from '../../../shared/utils/format'
import { getMemberPerformance, getTeamRanking } from '../api'
import { useProject } from '../projectContext'

/** PM-02 Xếp hạng team + hiệu suất thành viên. */
export default function TeamRankingPage() {
  const { projectId } = useProject()
  const ranking = useRequest(`ranking:${projectId}`, () => getTeamRanking(projectId))
  const members = useRequest(`member-perf:${projectId}`, () => getMemberPerformance(projectId))
  const maxObjects = Math.max(1, ...(ranking.data?.rows.map((r) => r.objects_done) ?? [1]))

  if (ranking.error != null) {
    return <StateView kind="error" description={getErrorMessage(ranking.error)} action={{ label: 'Thử lại', onClick: ranking.retry }} />
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Xếp hạng team</h1>
          <p>So sánh năng suất và chất lượng giữa các team.</p>
        </div>
      </div>
      {ranking.data && <Alert type="info" showIcon style={{ marginBottom: 16 }} title={`KPI tạm tính — ${ranking.data.formula}`} />}
      <Row gutter={[16, 16]}>
        <Col xs={24} xl={14}>
          <Card title="Bảng xếp hạng team">
            <Table
              rowKey={(r) => r.team.id}
              loading={ranking.isLoading}
              dataSource={ranking.data?.rows}
              pagination={false}
              locale={{ emptyText: 'Chưa có team' }}
              columns={[
                { title: 'Hạng', dataIndex: 'rank', width: 64 },
                { title: 'Team', render: (_, r) => r.team.name },
                { title: 'Thành viên', dataIndex: 'members', align: 'right' },
                { title: 'Job xong', render: (_, r) => `${r.done}/${r.jobs}`, align: 'right' },
                { title: 'Object xong', dataIndex: 'objects_done', render: formatNumber, align: 'right' },
                { title: 'Rework', dataIndex: 'rework_rate', render: formatPercent, align: 'right' },
                { title: 'Lỗi QC2', dataIndex: 'qc2_errors', align: 'right' },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} xl={10}>
          <Card title="So sánh object đã hoàn thành">
            {ranking.data?.rows.map((r) => (
              <div key={r.team.id} style={{ marginBottom: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>{r.team.name}</span>
                  <span>{formatNumber(r.objects_done)}</span>
                </div>
                <Progress percent={Math.round((r.objects_done * 100) / maxObjects)} showInfo={false} />
              </div>
            ))}
          </Card>
        </Col>
      </Row>
      <Card title="Hiệu suất annotator" style={{ marginTop: 16 }}>
        <Table
          rowKey={(r) => r.user.id}
          loading={members.isLoading}
          dataSource={members.data ?? []}
          pagination={{ pageSize: 20 }}
          columns={[
            { title: 'Annotator', render: (_, r) => <UserName user={r.user} /> },
            { title: 'Job được giao', dataIndex: 'jobs', align: 'right' },
            { title: 'Job xong', dataIndex: 'done', align: 'right' },
            { title: 'Object xong', dataIndex: 'objects_done', render: formatNumber, align: 'right' },
            { title: 'Rework', dataIndex: 'rework_rate', render: formatPercent, align: 'right' },
          ]}
        />
      </Card>
    </div>
  )
}
