import { CheckCircle, InfoCircle, Link01, LinkBroken01, Shield01 } from '@untitledui/icons'
import { useState } from 'react'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { FeaturedIcon } from '@/components/foundations/featured-icon/featured-icon'
import { useAuth } from '../../auth/useAuth'

/** Luồng dự kiến (chưa chốt cách làm, xem ghi chú ở component). */
const STEPS = [
  { title: 'Bấm "Liên kết với CVAT"', note: 'VanoHub chuyển bạn sang trang CVAT.' },
  { title: 'Đăng nhập tài khoản CVAT', note: 'Dùng đúng tài khoản bạn làm việc hằng ngày trên CVAT.' },
  { title: 'Đồng ý liên kết', note: 'Xác nhận cho phép VanoHub nhận biết tài khoản CVAT của bạn.' },
]

const BENEFITS = [
  'Job được giao cho bạn trên CVAT hiện đúng tên bạn trong VanoHub.',
  'Mở job trong CVAT từ VanoHub mà không phải tìm lại.',
  'Thống kê năng suất, lỗi và rework được tính đúng người.',
]

/**
 * Cấu hình › Liên kết CVAT — mỗi người tự liên kết tài khoản CVAT của mình.
 *
 * CHỈ LÀ GIAO DIỆN: chưa có backend. Cách liên kết thật chưa chốt — CVAT không có sẵn
 * màn hình "cho phép ứng dụng khác liên kết" (không phải nhà cung cấp OAuth), nên muốn
 * đúng luồng ở STEPS thì phải sửa server CVAT hoặc chọn cách khác. Nút liên kết hiện
 * chỉ báo "đang phát triển", không giả lập liên kết thành công.
 */
export default function CvatLinkPage() {
  const { user } = useAuth()
  const [showNotice, setShowNotice] = useState(false)

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 p-4 md:p-6">
      <header>
        <h1 className="text-display-xs font-semibold text-primary">Liên kết CVAT</h1>
        <p className="mt-1 text-sm text-tertiary">Kết nối tài khoản VanoHub của bạn với tài khoản trên CVAT.</p>
      </header>

      {/* Trạng thái liên kết */}
      <section className="rounded-2xl bg-primary p-5 shadow-xs ring-1 ring-secondary md:p-6">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
          <div className="flex items-center gap-3">
            <AccountMark label="VH" className="bg-brand-solid" />
            <div className="flex w-10 items-center justify-center text-fg-quaternary">
              <LinkBroken01 className="size-5" />
            </div>
            <AccountMark label="CVAT" className="bg-primary-solid text-xs" />
          </div>

          <div className="flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-md font-semibold text-primary">Tài khoản CVAT</h2>
              <Badge type="pill-color" size="sm" color="gray">Chưa liên kết</Badge>
            </div>
            <p className="mt-1 text-sm text-tertiary">
              Tài khoản VanoHub <span className="font-medium text-secondary">{user?.username}</span> chưa được liên kết với tài khoản CVAT nào.
            </p>
          </div>

          <Button size="md" iconLeading={Link01} onPress={() => setShowNotice(true)}>Liên kết với CVAT</Button>
        </div>

        {showNotice && (
          <div role="status" className="mt-5 flex items-start gap-3 rounded-xl bg-secondary p-4 ring-1 ring-secondary ring-inset">
            <InfoCircle className="mt-0.5 size-5 shrink-0 text-fg-brand-primary" />
            <div className="text-sm">
              <p className="font-semibold text-secondary">Tính năng đang được phát triển</p>
              <p className="mt-0.5 text-tertiary">Liên kết với CVAT chưa hoạt động. Hiện job vẫn được ghép người theo username trùng nhau giữa VanoHub và CVAT.</p>
            </div>
          </div>
        )}
      </section>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Các bước */}
        <section className="rounded-2xl bg-primary p-5 shadow-xs ring-1 ring-secondary md:p-6">
          <h2 className="text-md font-semibold text-primary">Liên kết diễn ra thế nào</h2>
          <ol className="mt-5 flex flex-col">
            {STEPS.map((step, index) => (
              <li key={step.title} className="relative flex gap-4 pb-6 last:pb-0">
                {index < STEPS.length - 1 && <span aria-hidden className="absolute top-9 bottom-1 left-4 w-px bg-border-secondary" />}
                <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-brand-secondary text-sm font-semibold text-brand-secondary ring-1 ring-brand ring-inset">
                  {index + 1}
                </span>
                <div className="pt-1">
                  <p className="text-sm font-semibold text-secondary">{step.title}</p>
                  <p className="mt-0.5 text-sm text-tertiary">{step.note}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        {/* Lợi ích + bảo mật */}
        <section className="flex flex-col gap-5 rounded-2xl bg-primary p-5 shadow-xs ring-1 ring-secondary md:p-6">
          <h2 className="text-md font-semibold text-primary">Vì sao nên liên kết</h2>
          <ul className="flex flex-col gap-3">
            {BENEFITS.map((benefit) => (
              <li key={benefit} className="flex gap-3 text-sm text-tertiary">
                <CheckCircle className="mt-0.5 size-5 shrink-0 text-fg-success-primary" />
                {benefit}
              </li>
            ))}
          </ul>
          <div className="mt-auto flex gap-3 rounded-xl bg-secondary p-4">
            <FeaturedIcon icon={Shield01} color="gray" theme="modern" size="sm" />
            <p className="text-sm text-tertiary">
              VanoHub không lưu mật khẩu CVAT của bạn. Bạn có thể huỷ liên kết bất cứ lúc nào.
            </p>
          </div>
        </section>
      </div>
    </div>
  )
}

function AccountMark({ label, className }: { label: string; className?: string }) {
  return (
    <span className={`flex size-12 items-center justify-center rounded-xl text-sm font-bold text-white shadow-xs ${className ?? ''}`}>
      {label}
    </span>
  )
}
