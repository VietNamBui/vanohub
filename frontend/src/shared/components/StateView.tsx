import { Button, Empty, Result, Spin } from 'antd'

/** Bốn trạng thái màn hình dùng chung theo wireframe CMN-04. */
type Kind = 'loading' | 'empty' | 'error' | 'forbidden'

interface Props {
  kind: Kind
  title?: string
  description?: string
  action?: { label: string; onClick: () => void }
}

export default function StateView({ kind, title, description, action }: Props) {
  const extra = action && (
    <Button type={kind === 'empty' ? 'primary' : 'default'} onClick={action.onClick}>
      {action.label}
    </Button>
  )

  if (kind === 'loading') {
    return (
      <div style={{ padding: 64, textAlign: 'center' }}>
        <Spin size="large" tip={title ?? 'Đang tải…'}>
          <div style={{ minHeight: 48 }} />
        </Spin>
      </div>
    )
  }
  if (kind === 'empty') {
    return (
      <Empty style={{ padding: 48 }} description={title ?? 'Chưa có dữ liệu'}>
        {description && <p style={{ color: 'rgba(0,0,0,.45)' }}>{description}</p>}
        {extra}
      </Empty>
    )
  }
  return (
    <Result
      status={kind === 'forbidden' ? '403' : 'error'}
      title={title ?? (kind === 'forbidden' ? 'Bạn không có quyền xem trang này' : 'Không tải được dữ liệu')}
      subTitle={description}
      extra={extra}
    />
  )
}
