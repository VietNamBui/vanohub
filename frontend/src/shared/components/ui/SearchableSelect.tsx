import { Check, ChevronDown, SearchLg, XClose } from '@untitledui/icons'
import { useRef, useState, type ReactNode } from 'react'
import {
  Button as AriaButton,
  Dialog as AriaDialog,
  DialogTrigger as AriaDialogTrigger,
  ListBox as AriaListBox,
  ListBoxItem as AriaListBoxItem,
  Popover as AriaPopover,
} from 'react-aria-components'
import { HintText } from '@/components/base/input/hint-text'
import { Label } from '@/components/base/input/label'
import { cx } from '@/utils/cx'
import { buildSearchableRows, CLEAR_KEY, type SearchableOption } from './searchableSelectUtils'

export type { SearchableOption }

interface SearchableSelectProps<T extends SearchableOption> {
  items: T[]
  selectedKey: string | number | null
  onSelectionChange: (key: string | number | null) => void
  label?: string
  hint?: string
  ariaLabel?: string
  placeholder?: string
  searchPlaceholder?: string
  emptyText?: string
  allowClear?: boolean
  clearLabel?: string
  isDisabled?: boolean
  size?: 'sm' | 'md'
  className?: string
  popoverClassName?: string
  renderOption?: (item: T, state: { isSelected: boolean; isDisabled: boolean }) => ReactNode
}

/**
 * Ô chọn có tìm kiếm (tương đương AntD Select `showSearch` + `allowClear`),
 * dựng trên React Aria DialogTrigger + Popover + ListBox.
 */
export default function SearchableSelect<T extends SearchableOption>({
  items,
  selectedKey,
  onSelectionChange,
  label,
  hint,
  ariaLabel,
  placeholder = 'Chọn…',
  searchPlaceholder = 'Tìm kiếm…',
  emptyText = 'Không tìm thấy kết quả',
  allowClear = false,
  clearLabel = 'Bỏ chọn',
  isDisabled = false,
  size = 'md',
  className,
  popoverClassName,
  renderOption,
}: SearchableSelectProps<T>) {
  const [isOpen, setIsOpen] = useState(false)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const selectedItem = selectedKey != null ? items.find((item) => item.id === selectedKey) : undefined
  const showClear = allowClear && selectedItem != null && !isDisabled

  return (
    <div className={cx('flex flex-col gap-1.5', className)}>
      {label && <Label>{label}</Label>}

      <div
        ref={wrapperRef}
        className={cx(
          'relative flex w-full items-center rounded-lg bg-primary shadow-xs ring-1 ring-primary transition duration-100 ease-linear ring-inset',
          isOpen && 'ring-2 ring-brand',
          isDisabled && 'cursor-not-allowed opacity-50',
        )}
      >
        <AriaDialogTrigger isOpen={isOpen} onOpenChange={(next) => !isDisabled && setIsOpen(next)}>
          <AriaButton
            isDisabled={isDisabled}
            aria-label={ariaLabel ?? label ?? placeholder}
            className={cx(
              'flex min-w-0 flex-1 cursor-pointer items-center justify-between gap-2 text-left outline-hidden disabled:cursor-not-allowed',
              size === 'sm' ? 'py-2 pr-2.5 pl-3 text-sm' : 'px-3 py-2 text-md',
              showClear && 'pr-1',
            )}
          >
            <span className={cx('truncate', selectedItem ? 'font-medium text-primary' : 'text-placeholder')}>
              {selectedItem ? selectedItem.label : placeholder}
            </span>
            {!showClear && (
              <ChevronDown
                aria-hidden="true"
                className={cx('shrink-0 text-fg-quaternary', size === 'sm' ? 'size-4 stroke-[2.25px]' : 'size-5')}
              />
            )}
          </AriaButton>

          <AriaPopover
            triggerRef={wrapperRef}
            placement="bottom start"
            offset={4}
            className={(state) =>
              cx(
                'min-w-(--trigger-width) origin-(--trigger-anchor-point) overflow-hidden rounded-lg bg-primary shadow-lg ring-1 ring-secondary_alt outline-hidden will-change-transform',
                state.isEntering && 'duration-150 ease-out animate-in fade-in slide-in-from-top-0.5',
                state.isExiting && 'duration-100 ease-in animate-out fade-out slide-out-to-top-0.5',
                popoverClassName,
              )
            }
          >
            <AriaDialog aria-label={ariaLabel ?? label ?? placeholder} className="outline-hidden">
              {isOpen && (
                <SearchablePopoverBody
                  items={items}
                  selectedKey={selectedKey}
                  searchPlaceholder={searchPlaceholder}
                  emptyText={emptyText}
                  allowClear={allowClear}
                  clearLabel={clearLabel}
                  renderOption={renderOption}
                  onSelect={(key) => {
                    onSelectionChange(key)
                    setIsOpen(false)
                  }}
                  onClose={() => setIsOpen(false)}
                />
              )}
            </AriaDialog>
          </AriaPopover>
        </AriaDialogTrigger>

        {showClear && (
          <button
            type="button"
            aria-label={`Xoá ${ariaLabel ?? label ?? 'lựa chọn'}`}
            onClick={(event) => {
              event.stopPropagation()
              onSelectionChange(null)
              setIsOpen(false)
            }}
            className="mr-2 flex size-5 shrink-0 cursor-pointer items-center justify-center rounded text-fg-quaternary transition hover:bg-primary_hover hover:text-fg-secondary"
          >
            <XClose className="size-3.5" aria-hidden="true" />
          </button>
        )}
      </div>

      {hint && <HintText className={cx(size === 'sm' && 'text-xs')}>{hint}</HintText>}
    </div>
  )
}

function SearchablePopoverBody<T extends SearchableOption>({
  items,
  selectedKey,
  searchPlaceholder,
  emptyText,
  allowClear,
  clearLabel,
  renderOption,
  onSelect,
  onClose,
}: {
  items: T[]
  selectedKey: string | number | null
  searchPlaceholder: string
  emptyText: string
  allowClear: boolean
  clearLabel: string
  renderOption?: (item: T, state: { isSelected: boolean; isDisabled: boolean }) => ReactNode
  onSelect: (key: string | number | null) => void
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const { rows, disabledKeys } = buildSearchableRows(items, query, allowClear, clearLabel)

  return (
    <div className="flex flex-col">
      <div className="flex items-center gap-2 border-b border-secondary px-3 py-2">
        <SearchLg className="size-4 shrink-0 text-fg-quaternary" aria-hidden="true" />
        <input
          type="text"
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={searchPlaceholder}
          aria-label={searchPlaceholder}
          className="w-full bg-transparent text-sm text-primary placeholder:text-placeholder focus:outline-hidden"
        />
        {query && (
          <button
            type="button"
            aria-label="Xoá từ khoá tìm kiếm"
            onClick={() => setQuery('')}
            className="cursor-pointer rounded p-0.5 text-fg-quaternary hover:bg-primary_hover hover:text-fg-secondary"
          >
            <XClose className="size-3.5" aria-hidden="true" />
          </button>
        )}
      </div>

      {rows.length === 0 ? (
        <p className="px-3 py-4 text-center text-sm text-tertiary">{emptyText}</p>
      ) : (
        <AriaListBox
          aria-label="Danh sách lựa chọn"
          items={rows}
          selectionMode="single"
          selectedKeys={selectedKey != null ? [selectedKey] : []}
          disabledKeys={disabledKeys}
          onSelectionChange={(keys) => {
            if (keys === 'all') return
            const first = keys.values().next().value
            if (first === undefined) {
              onClose()
              return
            }
            if (first === CLEAR_KEY) {
              onSelect(null)
              return
            }
            const matched = rows.find((r) => r.id === first)?.item
            onSelect(matched ? matched.id : (first as string | number))
          }}
          className="max-h-60 overflow-y-auto py-1 outline-hidden"
        >
          {(row) => (
            <AriaListBoxItem
              id={row.id}
              textValue={row.label}
              isDisabled={row.isDisabled}
              className="px-1.5 py-px outline-hidden"
            >
              {({ isFocused, isHovered, isSelected, isDisabled }) => (
                <div
                  className={cx(
                    'flex cursor-pointer items-center justify-between gap-2 rounded-md px-2.5 py-2 text-sm select-none',
                    (isFocused || isHovered || isSelected) && 'bg-primary_hover',
                    isDisabled && 'cursor-not-allowed opacity-50',
                  )}
                >
                  <div className="min-w-0 flex-1">
                    {row.isClear || !row.item ? (
                      <span className="text-tertiary">{row.label}</span>
                    ) : renderOption ? (
                      renderOption(row.item, { isSelected, isDisabled })
                    ) : (
                      <div className="flex flex-col">
                        <span className="truncate font-medium text-primary">{row.item.label}</span>
                        {row.item.supportingText && (
                          <span className="truncate text-xs text-tertiary">{row.item.supportingText}</span>
                        )}
                      </div>
                    )}
                  </div>
                  {isSelected && !row.isClear && (
                    <Check className="size-4 shrink-0 text-fg-brand-primary" aria-hidden="true" />
                  )}
                </div>
              )}
            </AriaListBoxItem>
          )}
        </AriaListBox>
      )}
    </div>
  )
}
