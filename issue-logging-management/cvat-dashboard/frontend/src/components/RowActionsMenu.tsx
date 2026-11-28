import { MoreOutlined } from '@ant-design/icons'
import { Dropdown, type MenuProps } from 'antd'
import type { ReactNode } from 'react'

export interface RowAction {
  key: string
  label: ReactNode
  danger?: boolean
  disabled?: boolean
  onClick: () => void
}

type MenuItem = NonNullable<MenuProps['items']>[number]

/**
 * Nút ⋯ mở menu thao tác của một dòng.
 * Trong `items`: `null` = đường kẻ ngăn; chuỗi = tiêu đề nhóm, các thao tác sau nó thuộc nhóm đó.
 */
export function RowActionsMenu({ items }: { items: (RowAction | string | null)[] }) {
  const menu: MenuItem[] = []
  let group: MenuItem[] | null = null
  items.forEach((it, i) => {
    if (typeof it === 'string') {
      group = []
      menu.push({ type: 'group', key: `g${i}`, label: it, children: group })
    } else if (it === null) {
      group = null
      menu.push({ type: 'divider', key: `d${i}` })
    } else {
      const entry: MenuItem = {
        key: it.key, label: it.label, danger: it.danger, disabled: it.disabled,
        // Menu nằm trong portal nhưng sự kiện React vẫn nổi lên dòng bảng: chặn để không kích hoạt onRow.
        onClick: ({ domEvent }) => { domEvent.stopPropagation(); it.onClick() },
      }
      if (group) group.push(entry)
      else menu.push(entry)
    }
  })
  return (
    <Dropdown menu={{ items: menu }} trigger={['click']} placement="bottomRight">
      <button type="button" className="cvd-row-actions" aria-label="Thao tác" onClick={(e) => e.stopPropagation()}>
        <MoreOutlined />
      </button>
    </Dropdown>
  )
}
