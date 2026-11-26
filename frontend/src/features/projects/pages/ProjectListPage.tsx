import { RefreshCw01 } from '@untitledui/icons'
import { Card, Col, Row, Typography } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router'
import { Button } from '@/components/base/buttons/button'
import { getErrorMessage } from '../../../shared/api/errors'
import StateView from '../../../shared/components/StateView'
import { useRequest } from '../../../shared/hooks/useRequest'
import { listProjects, syncOrganizationsFromCvat } from '../api'
import type { ProjectsSyncResult } from '../types'

/**
 * Chọn Organization để làm việc (model Project = CVAT organization). Backend chỉ trả về organization trong phạm vi quyền.
 * PM = Owner / Maintainer của CVAT organization (đã liên kết VanoHub) → "Đồng bộ từ CVAT" để kéo về.
 */
export default function ProjectListPage() {
  const [version, setVersion] = useState(0)
  const { data: projects, error, isLoading, retry } = useRequest(`projects:${version}`, listProjects)
  const [syncing, setSyncing] = useState(false)
  const [result, setResult] = useState<ProjectsSyncResult | null>(null)
  const [syncError, setSyncError] = useState<string | null>(null)

  async function sync() {
    setSyncing(true)
    setSyncError(null)
    try {
      setResult(await syncOrganizationsFromCvat())
      setVersion((v) => v + 1)
    } catch (e) {
      setSyncError(getErrorMessage(e))
    } finally {
      setSyncing(false)
    }
  }

  return (
    <div className="page" style={{ maxWidth: 1200, margin: '0 auto' }}>
      <div className="page-header">
        <div>
          <h1>Organization của bạn</h1>
          <p>Chọn một organization để bắt đầu. Danh sách lấy theo các CVAT organization bạn là thành viên.</p>
        </div>
        <Button size="md" color="secondary" iconLeading={RefreshCw01} isLoading={syncing} onPress={sync}>Đồng bộ từ CVAT</Button>
      </div>

      {syncError && <p role="alert" className="mb-4 text-sm text-error-primary">{syncError}</p>}
      {result && <SyncSummary result={result} />}

      {isLoading && <StateView kind="loading" />}
      {error != null && <StateView kind="error" description={getErrorMessage(error)} action={{ label: 'Thử lại', onClick: retry }} />}
      {projects?.length === 0 && (
        <StateView kind="empty" title="Bạn chưa thuộc organization nào"
          description="Được thêm vào CVAT organization (PM: vai trò Owner / Maintainer) → liên kết tài khoản CVAT → bấm “Đồng bộ từ CVAT”." />
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

function SyncSummary({ result }: { result: ProjectsSyncResult }) {
  const nothing = !result.created.length && !result.pm_added.length && !result.members_added.length
  return (
    <div role="status" className="mb-4 rounded-xl bg-secondary p-4 text-sm text-tertiary">
      <p className="font-semibold text-secondary">
        {nothing ? 'Không có organization mới.' : `Đã thêm ${result.created.length} organization, ${result.pm_added.length} lượt giao PM.`}
      </p>
      {result.waiting.length > 0 && (
        <>
          <p className="mt-2">CVAT organization chưa đưa lên VanoHub ({result.waiting.length}):</p>
          <ul className="mt-1 list-disc pl-5">
            {result.waiting.map((w) => <li key={w.cvat_org_id}>{w.name} — {w.reason}</li>)}
          </ul>
        </>
      )}
    </div>
  )
}
