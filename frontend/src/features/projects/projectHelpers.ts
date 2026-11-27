import type { ProjectSyncResult } from './types'

export interface ChecklistSection {
  title: string
  body: string
}

/** Phân tích nội dung Markdown hướng dẫn theo tiêu đề # / ## thành từng mục kiểm tra. */
export function parseGuidelineSections(markdown: string): ChecklistSection[] {
  const lines = markdown.split('\n')
  const sections: ChecklistSection[] = []
  let currentTitle = ''
  let bodyLines: string[] = []

  const flush = () => {
    const body = bodyLines.join('\n').trim()
    if (currentTitle || body) {
      sections.push({ title: currentTitle || 'Nội dung hướng dẫn', body })
    }
    currentTitle = ''
    bodyLines = []
  }

  for (const raw of lines) {
    const line = raw.trim()
    if (!line) continue
    if (line.startsWith('## ')) {
      flush()
      currentTitle = line.replace(/^##\s+/, '').trim()
    } else if (line.startsWith('# ')) {
      flush()
      currentTitle = line.replace(/^#\s+/, '').trim()
    } else {
      bodyLines.push(line.replace(/^[-*]\s+/, '• '))
    }
  }
  flush()
  return sections
}

/** Kiểm tra dữ liệu nhập trước khi xuất bản phiên bản hướng dẫn mới. */
export function validateGuidelineDraft(
  title: string,
  content: string,
): {
  titleError: string | null
  contentError: string | null
  trimmedTitle: string
  trimmedContent: string
  valid: boolean
} {
  const trimmedTitle = title.trim()
  const trimmedContent = content.trim()
  const titleError = trimmedTitle ? null : 'Vui lòng nhập tiêu đề.'
  const contentError = trimmedContent ? null : 'Vui lòng nhập nội dung hướng dẫn.'
  return {
    titleError,
    contentError,
    trimmedTitle,
    trimmedContent,
    valid: Boolean(trimmedTitle && trimmedContent),
  }
}

/** Định dạng thông báo tóm tắt kết quả đồng bộ organization với CVAT. */
export function formatCvatSyncSummary(result: ProjectSyncResult): string {
  const parts = [
    `${result.projects} project, ${result.tasks} task`,
    result.projects_created ? `${result.projects_created} project mới` : null,
    result.tasks_created ? `${result.tasks_created} task mới` : null,
    result.jobs_created ? `${result.jobs_created} job mới` : null,
    result.jobs_updated ? `${result.jobs_updated} job cập nhật` : null,
  ].filter(Boolean)
  return `Đã đồng bộ CVAT: ${parts.join(', ')}.`
}

