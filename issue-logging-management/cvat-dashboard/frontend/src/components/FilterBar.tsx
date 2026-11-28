import { SearchOutlined } from '@ant-design/icons'
import { Input } from 'antd'
import type { ReactNode } from 'react'

export interface FilterBarProps {
  search?: string
  onSearch?: (v: string) => void
  placeholder?: string
  /** Select/Pill lọc đặt bên cạnh ô tìm. */
  children?: ReactNode
  /** Nút bên phải (vd Tạo mới, tự làm mới). */
  extra?: ReactNode
}

/** Hàng lọc phía trên bảng: ô tìm + bộ lọc + hành động. Tự xuống dòng trên màn hẹp. */
export function FilterBar({ search, onSearch, placeholder = 'Tìm kiếm…', children, extra }: FilterBarProps) {
  return (
    <div className="cvd-filter-bar">
      {onSearch && (
        <Input
          allowClear prefix={<SearchOutlined />} placeholder={placeholder} value={search} style={{ width: 240 }}
          onChange={(e) => onSearch(e.target.value)}
        />
      )}
      {children}
      {extra && <div className="cvd-filter-extra">{extra}</div>}
    </div>
  )
}
