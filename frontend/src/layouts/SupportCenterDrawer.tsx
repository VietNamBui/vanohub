import { ChevronDown, ChevronRight, SearchLg, XClose } from '@untitledui/icons'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { Button } from '@/components/base/buttons/button'

interface FaqItem {
  id: string
  q: string
  a: string
}

const FAQS: FaqItem[] = [
  {
    id: 'claim',
    q: 'Khi nào được nhận job mới?',
    a: 'Bạn có thể nhấn "Nhận job mới" ở trang Job của tôi khi số job đang giữ nhỏ hơn giới hạn tối đa của dự án (GV02, mặc định 2 job).',
  },
  {
    id: 'withdraw',
    q: 'Nộp job lên QC1 rồi có rút lại được không?',
    a: 'Sau khi nộp sang Chờ QC1, job sẽ chuyển cho QC1 kiểm tra và không tự rút lại được. Nếu cần mở lại gấp, hãy liên hệ Project Manager.',
  },
  {
    id: 'dispute',
    q: 'Không đồng ý lỗi QC ghi thì làm gì?',
    a: 'Mở trang Cần sửa hoặc Chi tiết Job, nhấn "Phản hồi lỗi" tại dòng lỗi tương ứng và nhập lý do. Yêu cầu sẽ được gửi đến Project Manager để xem xét xử lý.',
  },
  {
    id: 'data-issue',
    q: 'Gặp dữ liệu hỏng thì báo ai?',
    a: 'Trong trang Chi tiết Job, chọn "Báo vấn đề dữ liệu" và ghi rõ frame bị lỗi (mờ point cloud, thiếu sensor…). Yêu cầu sẽ được chuyển tới PM xử lý.',
  },
  {
    id: 'kpi',
    q: 'KPI cuboid/ngày được tính thế nào?',
    a: 'Sản lượng KPI tính theo tổng object-frame/cuboid hoàn thành trong ngày khi nộp lên QC1 (CS01–CS03). Phần rework hoàn tất vẫn được tính vào KPI.',
  },
]

interface Props {
  open: boolean
  projectId: number | null
  onClose: () => void
}

/** Trung tâm hỗ trợ — Drawer trượt phải 440px với FAQ tìm kiếm được và liên hệ PM. */
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
      <div className="fixed inset-0 bg-[#0C111D]/70 backdrop-blur-[2px]" onClick={onClose} />

      <aside className="relative z-10 flex h-full w-full max-w-[440px] flex-col border-l border-[#EAECF0] bg-white p-6 shadow-2xl">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold text-[#101828]">Trung tâm hỗ trợ</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Đóng trung tâm hỗ trợ"
            className="flex size-8 cursor-pointer items-center justify-center rounded-lg text-[#98A2B3] hover:bg-[#F9FAFB] hover:text-[#475467]"
          >
            <XClose className="size-5" />
          </button>
        </div>

        <div className="mt-5 flex items-center gap-2.5 rounded-lg border border-[#D0D5DD] bg-white px-3.5 py-2.5 focus-within:border-[#7F56D9] focus-within:ring-2 focus-within:ring-[#F4EBFF]">
          <SearchLg className="size-4 shrink-0 text-[#667085]" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Tìm câu hỏi, hướng dẫn…"
            className="w-full bg-transparent text-sm text-[#101828] outline-none placeholder:text-[#667085]"
          />
        </div>

        <div className="mt-6 flex-1 overflow-y-auto">
          <h3 className="text-sm font-semibold text-[#344054]">Câu hỏi thường gặp</h3>
          <ul className="mt-3 flex flex-col gap-2">
            {filtered.map((item) => {
              const isOpen = expanded === item.id
              return (
                <li key={item.id} className="overflow-hidden rounded-lg border border-[#EAECF0] bg-white">
                  <button
                    type="button"
                    onClick={() => setExpanded(isOpen ? null : item.id)}
                    className="flex w-full cursor-pointer items-center justify-between gap-3 px-4 py-3 text-left text-sm font-medium text-[#344054] hover:bg-[#F9FAFB]"
                  >
                    <span>{item.q}</span>
                    {isOpen ? (
                      <ChevronDown className="size-4 shrink-0 text-[#667085]" />
                    ) : (
                      <ChevronRight className="size-4 shrink-0 text-[#98A2B3]" />
                    )}
                  </button>
                  {isOpen && (
                    <div className="border-t border-[#F2F4F7] bg-[#F9FAFB] px-4 py-3 text-sm leading-relaxed text-[#475467]">
                      {item.a}
                    </div>
                  )}
                </li>
              )
            })}
            {filtered.length === 0 && (
              <li className="rounded-lg border border-dashed border-[#EAECF0] p-4 text-center text-sm text-[#667085]">
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

            <p className="text-sm text-[#475467]">
              Vẫn cần hỗ trợ? Liên hệ <span className="font-semibold text-[#101828]">Project Manager</span> của dự án.
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
