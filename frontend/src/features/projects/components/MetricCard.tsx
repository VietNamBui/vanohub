import { InfoCircleOutlined } from '@ant-design/icons'
import { Card, Statistic, Tag, Tooltip } from 'antd'
import type { Metric } from '../types'

/**
 * Ô KPI. Chỉ số chưa chốt công thức hiện "Chưa chốt" thay vì một con số tự đặt;
 * chỉ số tạm tính có nhãn "Tạm tính" và tooltip ghi công thức đang dùng.
 */
export default function MetricCard({ title, metric, suffix }: { title: string; metric: Metric; suffix?: string }) {
  const pending = metric.status === 'pending_definition'
  return (
    <Card size="small" style={{ height: '100%' }}>
      <Statistic
        title={
          <span>
            {title}{' '}
            {metric.formula && (
              <Tooltip title={metric.formula}>
                <InfoCircleOutlined style={{ color: 'rgba(0,0,0,.35)' }} />
              </Tooltip>
            )}
          </span>
        }
        value={pending || metric.value == null ? '—' : metric.value}
        suffix={!pending && metric.value != null ? suffix : undefined}
      />
      {pending && <Tag style={{ marginTop: 8 }}>Chưa chốt công thức</Tag>}
      {metric.status === 'provisional' && <Tag color="blue" style={{ marginTop: 8 }}>Tạm tính</Tag>}
    </Card>
  )
}
