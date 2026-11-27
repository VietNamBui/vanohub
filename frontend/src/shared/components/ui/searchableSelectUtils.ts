export const CLEAR_KEY = '__clear__'

export interface SearchableOption {
  id: string | number
  label: string
  /** Chuỗi tìm kiếm mở rộng (mặc định tìm theo `label` + `supportingText`). */
  searchText?: string
  supportingText?: string
  isDisabled?: boolean
}

export interface PopoverOption<T extends SearchableOption> {
  id: string | number
  label: string
  item?: T
  isDisabled?: boolean
  isClear?: boolean
}

/** Lọc danh sách lựa chọn theo từ khoá (không phân biệt hoa thường, bỏ khoảng trắng đầu/cuối). */
export function filterSearchableOptions<T extends SearchableOption>(items: T[], query: string): T[] {
  const normalized = query.trim().toLowerCase()
  if (!normalized) return items
  return items.filter((item) =>
    (item.searchText ?? `${item.label} ${item.supportingText ?? ''}`).toLowerCase().includes(normalized),
  )
}

/** Tạo danh sách dòng hiển thị trong popover và tập khoá bị vô hiệu hoá. */
export function buildSearchableRows<T extends SearchableOption>(
  items: T[],
  query: string,
  allowClear: boolean,
  clearLabel: string,
): { rows: PopoverOption<T>[]; disabledKeys: (string | number)[] } {
  const normalized = query.trim().toLowerCase()
  const filtered = filterSearchableOptions(items, query)
  const rows: PopoverOption<T>[] = [
    ...(allowClear && !normalized ? [{ id: CLEAR_KEY, label: clearLabel, isClear: true }] : []),
    ...filtered.map((item) => ({
      id: item.id,
      label: item.label,
      item,
      isDisabled: item.isDisabled,
    })),
  ]
  const disabledKeys = rows.filter((r) => r.isDisabled).map((r) => r.id)
  return { rows, disabledKeys }
}

