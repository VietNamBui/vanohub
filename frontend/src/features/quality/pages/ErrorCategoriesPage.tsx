import { Edit05, Plus, SearchLg } from '@untitledui/icons'
import { useState } from 'react'
import { Table } from '@/components/application/table/table'
import { Badge } from '@/components/base/badges/badges'
import type { BadgeColors } from '@/components/base/badges/badge-types'
import { Button } from '@/components/base/buttons/button'
import { Input } from '@/components/base/input/input'
import { Select } from '@/components/base/select/select'
import { TextArea } from '@/components/base/textarea/textarea'
import { Toggle } from '@/components/base/toggle/toggle'
import { getErrorMessage } from '../../../shared/api/errors'
import EmptyRow from '../../../shared/components/ui/EmptyRow'
import FormDialog from '../../../shared/components/ui/FormDialog'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { useProject } from '../../projects/projectContext'
import { createErrorCategory, listErrorCategories, updateErrorCategory } from '../api'
import { SEVERITY_LABELS } from '../constants'
import type { ErrorCategory, Severity } from '../types'

const APPLIES_LABELS: Record<ErrorCategory['applies_to'], string> = {
  qc1: 'QC1',
  qc2: 'QC2',
  both: 'QC1 & QC2',
}

const SEVERITY_BADGE_COLORS: Record<Severity, BadgeColors> = {
  minor: 'gray',
  major: 'orange',
  critical: 'error',
}

const SEVERITY_ITEMS = (Object.entries(SEVERITY_LABELS) as [Severity, string][]).map(([id, label]) => ({ id, label }))
const APPLIES_ITEMS = (Object.entries(APPLIES_LABELS) as [ErrorCategory['applies_to'], string][]).map(([id, label]) => ({ id, label }))

type DialogState = { mode: 'create' } | { mode: 'edit'; category: ErrorCategory } | null

/** Danh mục lỗi dùng chung cho QC1 và QC2. Không xoá vì lỗi đã ghi tham chiếu đến — chỉ tắt bằng trạng thái Đang dùng. */
export default function ErrorCategoriesPage() {
  const { projectId, can } = useProject()
  const [version, setVersion] = useState(0)
  const [search, setSearch] = useState('')
  const [stageFilter, setStageFilter] = useState<string>('all')
  const [dialog, setDialog] = useState<DialogState>(null)
  const { run, pending } = useAction()
  const { data, error, isLoading, retry } = useRequest(`error-categories:${projectId}:${version}`, () =>
    listErrorCategories(projectId),
  )
  const reload = () => setVersion((v) => v + 1)
  const canManage = can('manage_quality_catalog')

  const keyword = search.trim().toLowerCase()
  const rows = (data ?? []).filter((c) => {
    if (stageFilter !== 'all' && c.applies_to !== stageFilter) return false
    if (!keyword) return true
    return c.name.toLowerCase().includes(keyword) || c.description.toLowerCase().includes(keyword)
  })

  async function toggleActive(category: ErrorCategory, isActive: boolean) {
    const ok = await run(
      () => updateErrorCategory(projectId, category.id, { is_active: isActive }),
      isActive ? `Đã bật "${category.name}"` : `Đã tắt "${category.name}"`,
    )
    if (ok) reload()
  }

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Danh mục lỗi</h1>
          <p className="mt-1 text-sm text-tertiary">
            Loại lỗi mà QC1 / QC2 chọn khi Reject. Không xoá để giữ lịch sử lỗi — tắt nếu ngừng sử dụng.
          </p>
        </div>
        {canManage && (
          <Button size="md" iconLeading={Plus} onPress={() => setDialog({ mode: 'create' })}>
            Thêm loại lỗi
          </Button>
        )}
      </header>

      <SectionCard bodyClassName="p-0">
        <div className="flex flex-wrap items-center gap-3 border-b border-secondary p-4">
          <Select
            className="w-48"
            size="sm"
            aria-label="Lọc theo stage"
            items={[{ id: 'all', label: 'Tất cả stage' }, ...APPLIES_ITEMS]}
            selectedKey={stageFilter}
            onSelectionChange={(k) => setStageFilter(String(k))}
          >
            {(item) => <Select.Item id={item.id} label={item.label} />}
          </Select>
          <Input
            className="min-w-48 flex-1"
            size="sm"
            icon={SearchLg}
            aria-label="Tìm loại lỗi"
            placeholder="Tìm theo tên hoặc mô tả…"
            value={search}
            onChange={setSearch}
          />
        </div>

        {error != null ? (
          <PageState kind="error" description={getErrorMessage(error)} onRetry={retry} />
        ) : (
          <Table aria-label="Danh mục lỗi" size="sm">
            <Table.Header>
              <Table.Head id="name" label="Tên lỗi" isRowHeader />
              <Table.Head id="description" label="Mô tả" />
              <Table.Head id="severity" label="Mức độ" />
              <Table.Head id="applies_to" label="Stage" />
              <Table.Head id="active" label="Trạng thái" />
              {canManage && <Table.Head id="actions" />}
            </Table.Header>
            <Table.Body
              items={rows}
              renderEmptyState={() => <EmptyRow text={isLoading ? 'Đang tải…' : 'Chưa có loại lỗi phù hợp'} />}
            >
              {(c) => (
                <Table.Row id={c.id}>
                  <Table.Cell className="font-medium text-primary">{c.name}</Table.Cell>
                  <Table.Cell className="max-w-sm truncate" title={c.description || undefined}>
                    {c.description || <span className="text-quaternary">—</span>}
                  </Table.Cell>
                  <Table.Cell>
                    <Badge type="pill-color" size="sm" color={SEVERITY_BADGE_COLORS[c.severity]}>
                      {SEVERITY_LABELS[c.severity]}
                    </Badge>
                  </Table.Cell>
                  <Table.Cell>
                    <Badge type="color" size="sm" color="gray">
                      {APPLIES_LABELS[c.applies_to]}
                    </Badge>
                  </Table.Cell>
                  <Table.Cell>
                    {canManage ? (
                      <div className="flex items-center gap-2.5">
                        <Toggle
                          size="sm"
                          isSelected={c.is_active}
                          isDisabled={pending}
                          aria-label={`Bật hoặc tắt ${c.name}`}
                          onChange={(active) => toggleActive(c, active)}
                        />
                        <Badge type="pill-color" size="sm" color={c.is_active ? 'success' : 'gray'}>
                          {c.is_active ? 'Đang dùng' : 'Đã tắt'}
                        </Badge>
                      </div>
                    ) : (
                      <Badge type="pill-color" size="sm" color={c.is_active ? 'success' : 'gray'}>
                        {c.is_active ? 'Đang dùng' : 'Đã tắt'}
                      </Badge>
                    )}
                  </Table.Cell>
                  {canManage && (
                    <Table.Cell className="text-right">
                      <Button size="xs" color="link-color" iconLeading={Edit05} onPress={() => setDialog({ mode: 'edit', category: c })}>
                        Sửa
                      </Button>
                    </Table.Cell>
                  )}
                </Table.Row>
              )}
            </Table.Body>
          </Table>
        )}
      </SectionCard>

      {dialog && (
        <ErrorCategoryDialog
          projectId={projectId}
          category={dialog.mode === 'edit' ? dialog.category : undefined}
          onClose={() => setDialog(null)}
          onDone={() => {
            setDialog(null)
            reload()
          }}
        />
      )}
    </div>
  )
}

function ErrorCategoryDialog({
  projectId,
  category,
  onClose,
  onDone,
}: {
  projectId: number
  category?: ErrorCategory
  onClose: () => void
  onDone: () => void
}) {
  const [name, setName] = useState(category?.name ?? '')
  const [description, setDescription] = useState(category?.description ?? '')
  const [severity, setSeverity] = useState<Severity>(category?.severity ?? 'minor')
  const [appliesTo, setAppliesTo] = useState<ErrorCategory['applies_to']>(category?.applies_to ?? 'both')
  const [isActive, setIsActive] = useState(category?.is_active ?? true)
  const [nameError, setNameError] = useState<string | null>(null)
  const { run, pending } = useAction()

  async function submit() {
    const trimmed = name.trim()
    if (!trimmed) {
      setNameError('Vui lòng nhập tên lỗi.')
      return
    }
    const payload: Partial<ErrorCategory> = {
      name: trimmed,
      description: description.trim(),
      severity,
      applies_to: appliesTo,
      is_active: isActive,
    }
    const ok = await run(
      () => (category ? updateErrorCategory(projectId, category.id, payload) : createErrorCategory(projectId, payload)),
      category ? 'Đã lưu loại lỗi' : 'Đã thêm loại lỗi',
    )
    if (ok) onDone()
  }

  return (
    <FormDialog
      isOpen
      title={category ? `Sửa loại lỗi: ${category.name}` : 'Thêm loại lỗi'}
      submitLabel="Lưu"
      onClose={onClose}
      onSubmit={submit}
      pending={pending}
    >
      <Input
        label="Tên lỗi"
        isRequired
        autoFocus
        value={name}
        onChange={(v) => {
          setName(v)
          if (nameError) setNameError(null)
        }}
        isInvalid={!!nameError}
        hint={nameError ?? undefined}
        placeholder="VD: Thiếu đối tượng"
      />
      <TextArea
        label="Mô tả"
        rows={3}
        value={description}
        onChange={setDescription}
        placeholder="Mô tả ngắn tiêu chí nhận diện lỗi…"
      />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Select
          label="Mức độ mặc định"
          items={SEVERITY_ITEMS}
          selectedKey={severity}
          onSelectionChange={(k) => setSeverity(String(k) as Severity)}
        >
          {(item) => <Select.Item id={item.id} label={item.label} />}
        </Select>
        <Select
          label="Stage áp dụng"
          items={APPLIES_ITEMS}
          selectedKey={appliesTo}
          onSelectionChange={(k) => setAppliesTo(String(k) as ErrorCategory['applies_to'])}
        >
          {(item) => <Select.Item id={item.id} label={item.label} />}
        </Select>
      </div>
      <Toggle
        size="sm"
        isSelected={isActive}
        onChange={setIsActive}
        label="Đang dùng"
        hint="Tắt để ẩn khỏi lựa chọn mới mà vẫn giữ lịch sử lỗi cũ."
      />
    </FormDialog>
  )
}
