import { Card, Col, Row, Typography } from 'antd'
import { Link } from 'react-router'
import { getErrorMessage } from '../../../shared/api/errors'
import StateView from '../../../shared/components/StateView'
import { useRequest } from '../../../shared/hooks/useRequest'
import { listProjects } from '../api'

/** Chọn dự án để làm việc. Backend chỉ trả về dự án trong phạm vi quyền. */
export default function ProjectListPage() {
  const { data: projects, error, isLoading, retry } = useRequest('projects', listProjects)

  return (
    <div className="page" style={{ maxWidth: 1200, margin: '0 auto' }}>
      <div className="page-header">
        <div>
          <h1>Dự án của bạn</h1>
          <p>Chọn một dự án để bắt đầu.</p>
        </div>
      </div>
      {isLoading && <StateView kind="loading" />}
      {error != null && <StateView kind="error" description={getErrorMessage(error)} action={{ label: 'Thử lại', onClick: retry }} />}
      {projects?.length === 0 && (
        <StateView kind="empty" title="Bạn chưa được phân vào dự án nào" description="Liên hệ Project Manager để được giao dự án." />
      )}
      <Row gutter={[16, 16]}>
        {projects?.map((project) => (
          <Col xs={24} md={12} xl={8} key={project.id}>
            <Link to={`/projects/${project.id}`}>
              <Card hoverable title={project.name} style={{ height: '100%' }}>
                <Typography.Paragraph type="secondary" ellipsis={{ rows: 2 }}>
                  {project.description || 'Không có mô tả'}
                </Typography.Paragraph>
              </Card>
            </Link>
          </Col>
        ))}
      </Row>
    </div>
  )
}
