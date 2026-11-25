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

const DEFAULT_SECTIONS: ChecklistSection[] = [
  {
    title: 'Vị trí, kích thước và hướng',
    body: 'Căn cuboid sát đối tượng theo point cloud và giữ đúng hướng di chuyển. Kiểm tra lại ở các góc nhìn khác trước khi xác nhận.',
  },
  {
    title: 'Đối tượng và lớp',
    body: 'Kiểm tra các điểm bị che khuất để tránh bỏ sót đối tượng. Đối chiếu lớp và thuộc tính với đối tượng thực tế.',
  },
  {
    title: 'ID giữa các frame',
    body: 'Dùng cùng ID cho một đối tượng xuyên suốt các frame liên tiếp. Kiểm tra lại các đoạn đối tượng bị che khuất hoặc xuất hiện trở lại.',
  },
]

function parseGuidelineSections(markdown: string): ChecklistSection[] {
  const lines = markdown.split('\n')
  const sections: ChecklistSection[] = []
  let currentTitle = ''
  let bodyLines: string[] = []

  const flush = () => {
    const body = bodyLines.join(' ').replace(/\s+/g, ' ').trim()
    if (currentTitle || body) {
      sections.push({ title: currentTitle || 'Quy tắc gán nhãn', body })
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
      bodyLines.push(line.replace(/^[-*]\s+/, ''))
    }
  }
  flush()
  return sections.length > 0 ? sections : DEFAULT_SECTIONS
}

/** Hướng dẫn gán nhãn (DL07): chế độ Chỉ đọc cho Annotator, danh sách kiểm tra trước khi nộp, ghi chú KPI CS01–CS03. PM có thể xuất bản phiên bản mới. */
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
  const sections = current ? parseGuidelineSections(current.content) : DEFAULT_SECTIONS

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
      <AnnotatorBreadcrumb projectId={projectId} items={[{ label: 'Hướng dẫn gán nhãn' }]} />

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-[30px] leading-tight font-bold text-[#101828]">Hướng dẫn gán nhãn</h1>
          <p className="mt-1 text-base text-[#475467]">{project.name}</p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {guidelines.length > 1 && current && (
            <div className="w-52">
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
                setTitle(current?.title ?? 'Quy tắc gán nhãn cuboid')
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
        <div className="rounded-xl border border-[#EAECF0] bg-white p-6">
          <PageState kind="error" description={getErrorMessage(error)} onRetry={retry} />
        </div>
      ) : isLoading ? (
        <div className="rounded-xl border border-[#EAECF0] bg-white p-6">
          <PageState kind="loading" />
        </div>
      ) : (
        <>
          {/* Card phiên bản đang áp dụng */}
          <section className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-[#EAECF0] bg-white px-6 py-5">
            <div>
              <h2 className="text-lg font-bold text-[#101828]">
                {current ? current.title : 'Quy tắc gán nhãn cuboid'}
              </h2>
              <p className="mt-1 text-sm text-[#475467]">
                {current
                  ? `Phiên bản áp dụng v${current.version} · DL07${current.created_by ? ` · ${current.created_by.full_name}` : ''}`
                  : 'Chưa xuất bản hướng dẫn riêng — áp dụng bộ quy tắc chuẩn · DL07'}
              </p>
            </div>
            <Badge size="sm" type="pill-color" color="gray">
              Chỉ đọc
            </Badge>
          </section>

          {/* Card Kiểm tra trước khi nộp */}
          <section className="rounded-xl border border-[#EAECF0] bg-white p-6">
            <h2 className="text-lg font-bold text-[#101828]">Kiểm tra trước khi nộp</h2>
            <ul className="mt-5 flex flex-col gap-5">
              {sections.map((sec, idx) => (
                <li key={`${sec.title}-${idx}`} className="flex items-start gap-3">
                  <CheckCircle className="mt-0.5 size-5 shrink-0 text-[#7F56D9]" />
                  <div>
                    <h3 className="text-[15px] font-bold text-[#101828]">{sec.title}</h3>
                    {sec.body && <p className="mt-1 text-sm leading-relaxed text-[#475467]">{sec.body}</p>}
                  </div>
                </li>
              ))}
            </ul>
          </section>

          {/* Blue Info Callout CS01-CS03 */}
          <div className="flex items-start gap-3 rounded-xl border border-[#B2DDFF] bg-[#EFF8FF] px-5 py-4 text-[#175CD3]">
            <InfoCircle className="mt-0.5 size-5 shrink-0" />
            <div>
              <p className="text-sm font-bold">Ghi nhận sản lượng · CS01–CS03</p>
              <p className="mt-1 text-[13px] leading-relaxed">
                KPI tính theo cuboid/ngày khi bạn xác nhận hoàn thành object trên CVAT. Phần rework hoàn tất cũng tính vào KPI.
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
          <Input label="Tiêu đề *" value={title} onChange={setTitle} placeholder="VD: Quy tắc gán nhãn cuboid" />
          <TextArea
            label="Nội dung (Markdown — dùng ## để chia các mục kiểm tra) *"
            rows={10}
            value={content}
            onChange={setContent}
            placeholder={'## Vị trí, kích thước và hướng\nCăn cuboid sát đối tượng theo point cloud...\n\n## ID giữa các frame\nDùng cùng ID xuyên suốt các frame liên tiếp.'}
          />
        </div>
      </FormDialog>
    </div>
  )
}
