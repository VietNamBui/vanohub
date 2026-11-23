import { ExclamationCircleOutlined, LockOutlined } from '@ant-design/icons'
import { Space, Tag, Tooltip } from 'antd'
import { JOB_STATUS_COLORS, JOB_STATUS_LABELS } from '../constants'
import type { JobStatus } from '../types'

interface Props {
  status: JobStatus
  escalated?: boolean
  locked?: boolean
  overdue?: boolean
}

export default function JobStatusTag({ status, escalated, locked, overdue }: Props) {
  return (
    <Space size={4} wrap>
      <Tag color={JOB_STATUS_COLORS[status]}>{JOB_STATUS_LABELS[status]}</Tag>
      {escalated && (
        <Tag color="error" icon={<ExclamationCircleOutlined />}>
          Escalated
        </Tag>
      )}
      {overdue && <Tag color="warning">Quá hạn</Tag>}
      {locked && (
        <Tooltip title="Job đang bị khoá">
          <Tag icon={<LockOutlined />}>Khoá</Tag>
        </Tooltip>
      )}
    </Space>
  )
}
