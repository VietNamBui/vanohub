import { describe, expect, it } from 'vitest'
import { formatCvatSyncSummary, parseGuidelineSections, validateGuidelineDraft } from './projectHelpers'
import type { ProjectSyncResult } from './types'

describe('projects helpers', () => {
  it('parses markdown guidelines into sections and normalizes bullet lists', () => {
    expect(parseGuidelineSections('')).toEqual([])
    expect(parseGuidelineSections('  \n\n  ')).toEqual([])

    const md = [
      'Đọc kỹ trước khi làm',
      '',
      '# Quy tắc chung',
      '- Kiểm tra 3 góc chiếu',
      '* Không xoá track pre-label',
      '## Kiểm tra cuối',
      'Bấm Save trước khi nộp',
    ].join('\n')

    expect(parseGuidelineSections(md)).toEqual([
      { title: 'Nội dung hướng dẫn', body: 'Đọc kỹ trước khi làm' },
      { title: 'Quy tắc chung', body: '• Kiểm tra 3 góc chiếu\n• Không xoá track pre-label' },
      { title: 'Kiểm tra cuối', body: 'Bấm Save trước khi nộp' },
    ])
  })

  it('validates guideline draft title and content after trimming', () => {
    expect(validateGuidelineDraft('   ', '  ')).toEqual({
      titleError: 'Vui lòng nhập tiêu đề.',
      contentError: 'Vui lòng nhập nội dung hướng dẫn.',
      trimmedTitle: '',
      trimmedContent: '',
      valid: false,
    })

    expect(validateGuidelineDraft('Quy tắc v2', '   ')).toEqual({
      titleError: null,
      contentError: 'Vui lòng nhập nội dung hướng dẫn.',
      trimmedTitle: 'Quy tắc v2',
      trimmedContent: '',
      valid: false,
    })

    expect(validateGuidelineDraft('  Quy tắc v2  ', '  ## Mục 1\nChi tiết  ')).toEqual({
      titleError: null,
      contentError: null,
      trimmedTitle: 'Quy tắc v2',
      trimmedContent: '## Mục 1\nChi tiết',
      valid: true,
    })
  })

  it('formats CVAT sync summary omitting zero creation/update deltas', () => {
    const base: ProjectSyncResult = {
      projects: 2,
      projects_created: 0,
      tasks: 5,
      tasks_created: 0,
      jobs_created: 0,
      jobs_updated: 0,
      assignees_pushed: 0,
      waiting_link: 0,
    }
    expect(formatCvatSyncSummary(base)).toBe('Đã đồng bộ CVAT: 2 project, 5 task.')

    expect(
      formatCvatSyncSummary({
        ...base,
        projects_created: 1,
        tasks_created: 2,
        jobs_created: 8,
        jobs_updated: 3,
      }),
    ).toBe('Đã đồng bộ CVAT: 2 project, 5 task, 1 project mới, 2 task mới, 8 job mới, 3 job cập nhật.')
  })
})

