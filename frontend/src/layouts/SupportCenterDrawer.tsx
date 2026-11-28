import { ChevronDown, ChevronRight, SearchLg, XClose } from '@untitledui/icons'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { Button } from '@/components/base/buttons/button'
import { Input } from '@/components/base/input/input'

interface FaqItem {
  id: string
  q: string
  a: string
}

const FAQS: FaqItem[] = [
  {
    id: 'claim',
    q: 'Khi nào được nhận job mới?',
    a: 'Bạn có thể nhấn "Nhận job mới" ở trang Job của tôi khi số job đang giữ nhỏ hơn giới hạn tối đa của organization (mặc định 2 job).',
  },
  {
    id: 'withdraw',
    q: 'Nộp job lên QC1 rồi có rút lại được không?',
    a: 'Sau khi nộp sang Chờ QC1, job sẽ chuyển cho QC1 kiểm tra và không tự rút lại được. Nếu cần mở lại gấp, hãy liên hệ Project Manager.',
  },
  {
    id: 'dispute',
    q: 'Không đồng ý lỗi QC ghi thì làm gì?',
    a: 'Mở trang Cần sửa hoặc Chi tiết Job, nhấn "Phản hồi lỗi" tại dòng lỗi tương ứng và nhập lý do. Yêu cầu sẽ được gửi đến Project Manager xem xét và phân xử.',
  },
  {
    id: 'data-issue',
    q: 'Gặp dữ liệu hỏng thì báo ai?',
    a: 'Trong trang Chi tiết Job, chọn "Báo vấn đề dữ liệu" và ghi rõ frame bị lỗi (mờ point cloud, thiếu sensor…). Yêu cầu sẽ được chuyển tới Project Manager xử lý.',
  },
  {
    id: 'kpi',
    q: 'KPI cuboid/ngày được tính thế nào?',
    a: 'Sản lượng KPI tính theo tổng object-frame/cuboid hoàn thành trong ngày khi nộp lên QC1. Phần rework hoàn tất vẫn được tính vào KPI.',
  },
]

interface Props {
  open: boolean
  projectId: number | null
  onClose: () => void
}

/** Trung tâm hỗ trợ — Drawer trượt phải 440px với FAQ tìm kiếm được và liên hệ Project Manager. */
export default function SupportCenterDrawer({ open, projectId, onClose }: Props) {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  const needle = search.trim().toLowerCase()
  const filtered = needle
    ? FAQS.filter((f) => f.q.toLowerCase().includes(needle) || f.a.toLowerCase().includes(needle))
    : FAQS

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label="Trung tâm hỗ trợ">
      <div className="fixed inset-0 bg-overlay/70 backdrop-blur-[2px]" onClick={onClose} />

      <aside className="relative z-10 flex h-full w-full max-w-[440px] flex-col border-l border-secondary bg-primary p-6 shadow-2xl">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-primary">Trung tâm hỗ trợ</h2>
          <Button
            color="tertiary"
            size="xs"
            iconLeading={XClose}
            aria-label="Đóng trung tâm hỗ trợ"
            onPress={onClose}
          />
        </div>

        <div className="mt-5">
          <Input
            size="sm"
            icon={SearchLg}
            value={search}
            onChange={setSearch}
            placeholder="Tìm câu hỏi, hướng dẫn…"
            aria-label="Tìm câu hỏi, hướng dẫn"
          />
        </div>

        <div className="mt-6 flex-1 overflow-y-auto">
          <h3 className="text-sm font-semibold text-secondary">Câu hỏi thường gặp</h3>
          <ul className="mt-3 flex flex-col gap-2">
            {filtered.map((item) => {
              const isOpen = expanded === item.id
              return (
                <li key={item.id} className="overflow-hidden rounded-lg border border-secondary bg-primary">
                  <button
                    type="button"
                    onClick={() => setExpanded(isOpen ? null : item.id)}
                    className="flex w-full cursor-pointer items-center justify-between gap-3 px-4 py-3 text-left text-sm font-medium text-secondary transition hover:bg-primary_hover"
                  >
                    <span>{item.q}</span>
                    {isOpen ? (
                      <ChevronDown className="size-4 shrink-0 text-fg-tertiary" />
                    ) : (
                      <ChevronRight className="size-4 shrink-0 text-fg-quaternary" />
                    )}
                  </button>
                  {isOpen && (
                    <div className="border-t border-tertiary bg-secondary px-4 py-3 text-sm leading-relaxed text-tertiary">
                      {item.a}
                    </div>
                  )}
                </li>
              )
            })}
            {filtered.length === 0 && (
              <li className="rounded-lg border border-dashed border-secondary p-4 text-center text-sm text-tertiary">
                Không tìm thấy câu hỏi phù hợp.
              </li>
            )}
          </ul>

          <div className="mt-6 flex flex-col gap-4">
            {projectId && (
              <Button
                color="secondary"
                size="md"
                className="w-full justify-center"
                onPress={() => {
                  onClose()
                  navigate(`/projects/${projectId}/guidelines`)
                }}
              >
                Mở hướng dẫn gán nhãn
              </Button>
            )}

            <p className="text-sm text-tertiary">
              Vẫn cần hỗ trợ? Liên hệ <span className="font-semibold text-primary">Project Manager</span> phụ trách organization.
            </p>

            <Button color="primary" size="md" className="w-full justify-center" onPress={onClose}>
              Đóng
            </Button>
          </div>
        </div>
      </aside>
    </div>
  )
}
