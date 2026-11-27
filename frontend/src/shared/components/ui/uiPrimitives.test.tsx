import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import RoleBadges from '../RoleBadges'
import StateView from '../StateView'
import MetricCard from './MetricCard'
import SearchableSelect from './SearchableSelect'
import {
  buildSearchableRows,
  CLEAR_KEY,
  filterSearchableOptions,
  type SearchableOption,
} from './searchableSelectUtils'

const SAMPLE_ITEMS: SearchableOption[] = [
  { id: 1, label: 'Đội Xe Tự Lái', supportingText: 'team-alpha' },
  { id: 2, label: 'Đội Đường Phố', searchText: 'Doanh nghiep street-team', isDisabled: true },
  { id: 3, label: 'Biển Báo Giao Thông', supportingText: 'signs' },
]

describe('searchableSelectUtils', () => {
  it('filters options case-insensitively with trimmed query and searchText override', () => {
    expect(filterSearchableOptions(SAMPLE_ITEMS, '')).toEqual(SAMPLE_ITEMS)
    expect(filterSearchableOptions(SAMPLE_ITEMS, '   ')).toEqual(SAMPLE_ITEMS)
    expect(filterSearchableOptions(SAMPLE_ITEMS, '  alpha ').map((i) => i.id)).toEqual([1])
    expect(filterSearchableOptions(SAMPLE_ITEMS, 'STREET-TEAM').map((i) => i.id)).toEqual([2])
    expect(filterSearchableOptions(SAMPLE_ITEMS, 'biển báo').map((i) => i.id)).toEqual([3])
    expect(filterSearchableOptions(SAMPLE_ITEMS, 'Đội Đường Phố')).toEqual([])
  })

  it('builds popover rows with optional clear entry only when query is empty and collects disabledKeys', () => {
    const withClear = buildSearchableRows(SAMPLE_ITEMS, '', true, 'Bỏ chọn')
    expect(withClear.rows[0]).toEqual({ id: CLEAR_KEY, label: 'Bỏ chọn', isClear: true })
    expect(withClear.rows.map((r) => r.id)).toEqual([CLEAR_KEY, 1, 2, 3])
    expect(withClear.disabledKeys).toEqual([2])

    const searched = buildSearchableRows(SAMPLE_ITEMS, 'team', true, 'Bỏ chọn')
    expect(searched.rows.map((r) => r.id)).toEqual([1, 2])
    expect(searched.disabledKeys).toEqual([2])

    const noClear = buildSearchableRows(SAMPLE_ITEMS, '', false, 'Bỏ chọn')
    expect(noClear.rows.map((r) => r.id)).toEqual([1, 2, 3])
  })
})

describe('shared UI primitives SSR regressions', () => {
  it('renders SearchableSelect placeholder, selected value, and clear button rules', () => {
    const emptyHtml = renderToStaticMarkup(
      <SearchableSelect
        ariaLabel="Tổ chức"
        placeholder="Chọn tổ chức"
        items={SAMPLE_ITEMS}
        selectedKey={null}
        onSelectionChange={vi.fn()}
        allowClear
      />,
    )
    expect(emptyHtml).toContain('Chọn tổ chức')
    expect(emptyHtml).not.toContain('aria-label="Xoá Tổ chức"')

    const selectedHtml = renderToStaticMarkup(
      <SearchableSelect
        ariaLabel="Tổ chức"
        items={SAMPLE_ITEMS}
        selectedKey={1}
        onSelectionChange={vi.fn()}
        allowClear
      />,
    )
    expect(selectedHtml).toContain('Đội Xe Tự Lái')
    expect(selectedHtml).toContain('aria-label="Xoá Tổ chức"')

    const disabledHtml = renderToStaticMarkup(
      <SearchableSelect
        ariaLabel="Tổ chức"
        items={SAMPLE_ITEMS}
        selectedKey={1}
        onSelectionChange={vi.fn()}
        allowClear
        isDisabled
      />,
    )
    expect(disabledHtml).toContain('Đội Xe Tự Lái')
    expect(disabledHtml).not.toContain('aria-label="Xoá Tổ chức"')
  })

  it('renders StateView variants without any Ant Design classes', () => {
    const loadingHtml = renderToStaticMarkup(<StateView kind="loading" />)
    expect(loadingHtml).toContain('role="status"')
    expect(loadingHtml).toContain('Đang tải…')
    expect(loadingHtml).not.toContain('ant-spin')

    const emptyHtml = renderToStaticMarkup(<StateView kind="empty" />)
    expect(emptyHtml).toContain('Chưa có dữ liệu')

    const errorHtml = renderToStaticMarkup(
      <StateView kind="error" description="Lỗi kết nối" action={{ label: 'Thử lại', onClick: vi.fn() }} />,
    )
    expect(errorHtml).toContain('role="alert"')
    expect(errorHtml).toContain('Không tải được dữ liệu')
    expect(errorHtml).toContain('Lỗi kết nối')
    expect(errorHtml).toContain('Thử lại')

    const forbiddenHtml = renderToStaticMarkup(<StateView kind="forbidden" title="Từ chối" />)
    expect(forbiddenHtml).toContain('Từ chối')
  })

  it('renders RoleBadges in canonical ROLE_ORDER regardless of input order', () => {
    expect(renderToStaticMarkup(<RoleBadges roles={[]} />)).toContain('Không có vai trò')

    const shortHtml = renderToStaticMarkup(
      <RoleBadges roles={['annotator', 'qc1', 'project_manager', 'qc2']} short />,
    )
    const pmIdx = shortHtml.indexOf('PM')
    const qc2Idx = shortHtml.indexOf('QC2')
    const qc1Idx = shortHtml.indexOf('QC1')
    const annoIdx = shortHtml.indexOf('Annotator')
    expect(pmIdx).toBeGreaterThan(-1)
    expect(pmIdx).toBeLessThan(qc2Idx)
    expect(qc2Idx).toBeLessThan(qc1Idx)
    expect(qc1Idx).toBeLessThan(annoIdx)

    const fullHtml = renderToStaticMarkup(<RoleBadges roles={['qc2', 'project_manager']} />)
    expect(fullHtml).toContain('Project Manager')
    expect(fullHtml).toContain('QC2')
  })

  it('renders MetricCard pending_definition as dash (never 0), provisional, and ok values', () => {
    const pendingHtml = renderToStaticMarkup(
      <MetricCard label="CL11" metric={{ value: null, status: 'pending_definition', formula: 'TBD' }} suffix="%" />,
    )
    expect(pendingHtml).toContain('Chưa chốt công thức')
    expect(pendingHtml).toContain('—')
    expect(pendingHtml).not.toContain('0%')

    const provisionalHtml = renderToStaticMarkup(
      <MetricCard label="SL01" metric={{ value: 42, status: 'provisional', formula: 'S1' }} />,
    )
    expect(provisionalHtml).toContain('Tạm tính')
    expect(provisionalHtml).toContain('42')

    const okHtml = renderToStaticMarkup(
      <MetricCard label="FPY" metric={{ value: 92.5, status: 'ok', formula: 'passed/total' }} suffix="%" />,
    )
    expect(okHtml).toContain('92.5%')
    expect(okHtml).not.toContain('Chưa chốt công thức')
    expect(okHtml).not.toContain('Tạm tính')
  })
})

