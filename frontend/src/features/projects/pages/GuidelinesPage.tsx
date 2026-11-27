import { CheckCircle, InfoCircle } from '@untitledui/icons'
import { useState } from 'react'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { Input } from '@/components/base/input/input'
import { NativeSelect } from '@/components/base/select/select-native'
import { TextArea } from '@/components/base/textarea/textarea'
import { getErrorMessage } from '../../../shared/api/errors'
import FormDialog from '../../../shared/components/ui/FormDialog'
import PageState from '../../../shared/components/ui/PageState'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import AnnotatorBreadcrumb from '../../jobs/components/AnnotatorBreadcrumb'
import { listGuidelines, publishGuideline } from '../api'
import { useProject } from '../projectContext'

interface ChecklistSection {
  title: string
  body: string
}

function parseGuidelineSections(markdown: string): ChecklistSection[] {
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

/** Guidelines: chế độ Chỉ đọc cho thành viên, danh sách kiểm tra trước khi nộp. PM có thể xuất bản phiên bản mới. */
export default function GuidelinesPage() {
  const { projectId, project, can } = useProject()
  const [version, setVersion] = useState(0)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const { run, pending } = useAction()
  const { data, error, isLoading, retry } = useRequest(`guidelines:${projectId}:${version}`, () =>
    listGuidelines(projectId),
  )

  const canManage = can('manage_quality_catalog')
  const guidelines = data ?? []
  const current = guidelines.find((g) => g.id === selectedId) ?? guidelines[0]
  const sections = current ? parseGuidelineSections(current.content) : []

  async function handlePublish() {
    if (!title.trim() || !content.trim()) return
    const ok = await run(
      () => publishGuideline(projectId, { title: title.trim(), content: content.trim() }),
      'Đã xuất bản phiên bản hướng dẫn mới',
    )
    if (ok) {
      setEditing(false)
      setSelectedId(null)
      setVersion((v) => v + 1)
    }
  }

  return (
    <div className="mx-auto flex max-w-[1160px] flex-col gap-6 px-6 py-7">
      <AnnotatorBreadcrumb projectId={projectId} items={[{ label: 'Guidelines' }]} />

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Guidelines</h1>
          <p className="mt-1 text-sm text-tertiary">
            {project.name} · Mỗi lần lưu tạo một phiên bản mới; phiên bản cũ luôn được giữ lại.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {guidelines.length > 1 && current && (
            <div className="w-56">
              <NativeSelect
                size="sm"
                aria-label="Chọn phiên bản"
                value={String(current.id)}
                onChange={(e) => setSelectedId(Number(e.target.value))}
                options={guidelines.map((g, idx) => ({
                  value: String(g.id),
                  label: `v${g.version}${idx === 0 ? ' (Mới nhất)' : ''} · ${formatDateTime(g.created_at)}`,
                }))}
              />
            </div>
          )}

          {canManage && (
            <Button
              color="primary"
              size="md"
              onPress={() => {
                setTitle(current?.title ?? '')
                setContent(current?.content ?? '')
                setEditing(true)
              }}
            >
              {current ? 'Soạn phiên bản mới' : 'Tạo hướng dẫn'}
            </Button>
          )}
        </div>
      </header>

      {error != null ? (
        <div className="rounded-2xl bg-primary p-6 shadow-xs ring-1 ring-secondary">
          <PageState kind="error" description={getErrorMessage(error)} onRetry={retry} />
        </div>
      ) : isLoading ? (
        <div className="rounded-2xl bg-primary p-6 shadow-xs ring-1 ring-secondary">
          <PageState kind="loading" />
        </div>
      ) : !current ? (
        <div className="rounded-2xl bg-primary p-8 text-center shadow-xs ring-1 ring-secondary">
          <p className="text-base font-semibold text-primary">Chưa có hướng dẫn gán nhãn</p>
          <p className="mt-1 text-sm text-tertiary">
            {canManage
              ? 'Bấm "Tạo hướng dẫn" để xuất bản phiên bản đầu tiên cho organization.'
              : 'Project Manager chưa xuất bản hướng dẫn cho organization này.'}
          </p>
        </div>
      ) : (
        <>
          <section className="flex flex-wrap items-center justify-between gap-4 rounded-2xl bg-primary px-6 py-5 shadow-xs ring-1 ring-secondary">
            <div>
              <h2 className="text-lg font-semibold text-primary">{current.title}</h2>
              <p className="mt-1 text-sm text-tertiary">
                Phiên bản áp dụng v{current.version}
                {current.created_by ? ` · ${current.created_by.full_name}` : ''} · {formatDateTime(current.created_at)}
              </p>
            </div>
            <Badge size="sm" type="pill-color" color="gray">
              Chỉ đọc
            </Badge>
          </section>

          <section className="rounded-2xl bg-primary p-6 shadow-xs ring-1 ring-secondary">
            <h2 className="text-lg font-semibold text-primary">Kiểm tra trước khi nộp</h2>
            <ul className="mt-5 flex flex-col gap-5">
              {sections.map((sec, idx) => (
                <li key={`${sec.title}-${idx}`} className="flex items-start gap-3">
                  <CheckCircle className="mt-0.5 size-5 shrink-0 text-brand-secondary" />
                  <div>
                    <h3 className="text-[15px] font-semibold text-primary">{sec.title}</h3>
                    {sec.body && (
                      <p className="mt-1 text-sm leading-relaxed whitespace-pre-line text-tertiary">{sec.body}</p>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </section>

          <div className="flex items-start gap-3 rounded-2xl border border-secondary bg-secondary px-5 py-4 text-secondary">
            <InfoCircle className="mt-0.5 size-5 shrink-0 text-brand-secondary" />
            <div>
              <p className="text-sm font-semibold text-primary">Ghi nhận sản lượng</p>
              <p className="mt-1 text-[13px] leading-relaxed text-tertiary">
                KPI tính theo object/ngày khi bạn xác nhận hoàn thành trên CVAT. Phần rework hoàn tất cũng được ghi nhận vào sản lượng.
              </p>
            </div>
          </div>
        </>
      )}

      <FormDialog
        isOpen={editing}
        onClose={() => setEditing(false)}
        title="Xuất bản phiên bản hướng dẫn mới"
        description="Mỗi lần lưu sẽ tạo phiên bản mới; lịch sử phiên bản cũ luôn được giữ lại."
        submitLabel="Lưu phiên bản"
        onSubmit={handlePublish}
        pending={pending}
      >
        <div className="flex flex-col gap-4">
          <Input label="Tiêu đề *" value={title} onChange={setTitle} placeholder="VD: Quy tắc gán nhãn" />
          <TextArea
            label="Nội dung (Markdown — dùng ## để chia các mục kiểm tra) *"
            rows={10}
            value={content}
            onChange={setContent}
            placeholder={'## Phạm vi\nMô tả quy tắc gán nhãn...\n\n## Kiểm tra trước khi nộp\n- Kiểm tra đầy đủ đối tượng.'}
          />
        </div>
      </FormDialog>
    </div>
  )
}
