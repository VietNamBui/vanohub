import { CheckCircle, Eye, EyeOff, Link01, LinkBroken01, LinkExternal01, Shield01 } from '@untitledui/icons'
import { useState } from 'react'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { Input } from '@/components/base/input/input'
import { FeaturedIcon } from '@/components/foundations/featured-icon/featured-icon'
import { getErrorMessage } from '../../../shared/api/errors'
import FormDialog from '../../../shared/components/ui/FormDialog'
import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import { useAuth } from '../../auth/useAuth'
import { getCvatLink, linkCvat, unlinkCvat, type CvatLinkState } from '../api'
import { cx } from '@/utils/cx'

const BENEFITS = [
  'Job được giao cho bạn trên VanoHub tự xuất hiện ở tab Jobs trong CVAT.',
  'Khi job chuyển bước (QC1, rework…), người giữ job bên CVAT được đổi theo.',
  'Thống kê năng suất, lỗi và rework được tính đúng người.',
]

/**
 * Cấu hình › Liên kết CVAT — mỗi người tự liên kết tài khoản CVAT của mình bằng Access Token.
 * Token chỉ dùng một lần để VanoHub biết bạn là user nào bên CVAT; VanoHub không lưu token.
 */
export default function CvatLinkPage() {
  const { user } = useAuth()
  const [version, setVersion] = useState(0)
  const [override, setOverride] = useState<CvatLinkState | null>(null)
  const { data, error, isLoading, retry } = useRequest(`cvat-link:${version}`, getCvatLink)
  const state = override ?? data

  const changed = (next: CvatLinkState) => {
    setOverride(next)
    setVersion((v) => v + 1)
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 p-4 md:p-6">
      <header>
        <h1 className="text-display-xs font-semibold text-primary">Liên kết CVAT</h1>
        <p className="mt-1 text-sm text-tertiary">Kết nối tài khoản VanoHub của bạn với tài khoản trên CVAT.</p>
      </header>

      {error != null && !state ? (
        <SectionCard><PageState kind="error" description={getErrorMessage(error)} onRetry={retry} /></SectionCard>
      ) : isLoading && !state ? (
        <SectionCard><PageState kind="loading" /></SectionCard>
      ) : state ? (
        <>
          <StatusCard state={state} username={user?.username ?? ''} onChanged={changed} />
          {!state.linked && <LinkForm cvatUrl={state.cvat_url} onLinked={changed} />}
        </>
      ) : null}

      <SectionCard title="Vì sao cần liên kết">
        <ul className="flex flex-col gap-3">
          {BENEFITS.map((benefit) => (
            <li key={benefit} className="flex gap-3 text-sm text-tertiary">
              <CheckCircle className="mt-0.5 size-5 shrink-0 text-fg-success-primary" />
              {benefit}
            </li>
          ))}
        </ul>
        <div className="mt-5 flex gap-3 rounded-xl bg-secondary p-4">
          <FeaturedIcon icon={Shield01} color="gray" theme="modern" size="sm" />
          <p className="text-sm text-tertiary">
            VanoHub không lưu mật khẩu hay token CVAT của bạn — chỉ lưu tên tài khoản CVAT để biết giao job cho ai.
            Sau khi liên kết, bạn có thể xoá token trong CVAT. Huỷ liên kết bất cứ lúc nào.
          </p>
        </div>
      </SectionCard>
    </div>
  )
}

function StatusCard({ state, username, onChanged }: { state: CvatLinkState; username: string; onChanged: (s: CvatLinkState) => void }) {
  const [confirm, setConfirm] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function unlink() {
    setPending(true)
    setError(null)
    try {
      onChanged(await unlinkCvat())
      setConfirm(false)
    } catch (e) {
      setError(getErrorMessage(e))
    } finally {
      setPending(false)
    }
  }

  return (
    <section className="rounded-2xl bg-primary p-5 shadow-xs ring-1 ring-secondary md:p-6">
      <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
        <div className="flex items-center gap-3">
          <AccountMark label="VH" className="bg-brand-solid" />
          <div className={cx('flex w-10 items-center justify-center', state.linked ? 'text-fg-success-primary' : 'text-fg-quaternary')}>
            {state.linked ? <Link01 className="size-5" /> : <LinkBroken01 className="size-5" />}
          </div>
          <AccountMark label="CVAT" className="bg-primary-solid text-xs" />
        </div>

        <div className="flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-md font-semibold text-primary">Tài khoản CVAT</h2>
            {state.linked
              ? <Badge type="pill-color" size="sm" color="success">Đã liên kết</Badge>
              : <Badge type="pill-color" size="sm" color="gray">Chưa liên kết</Badge>}
          </div>
          <p className="mt-1 text-sm text-tertiary">
            {state.linked ? (
              <>
                <span className="font-medium text-secondary">{username}</span> ⇄ CVAT{' '}
                <span className="font-medium text-secondary">{state.cvat_username}</span>
                {state.linked_at && <span className="text-quaternary"> · từ {formatDateTime(state.linked_at)}</span>}
              </>
            ) : (
              <>Tài khoản VanoHub <span className="font-medium text-secondary">{username}</span> chưa được liên kết với tài khoản CVAT nào.</>
            )}
          </p>
        </div>

        {state.linked && (
          <Button color="secondary-destructive" size="md" iconLeading={LinkBroken01} onPress={() => setConfirm(true)}>Huỷ liên kết</Button>
        )}
      </div>

      <SyncNotice state={state} />

      {confirm && (
        <FormDialog
          isOpen
          destructive
          title="Huỷ liên kết CVAT?"
          description={state.jobs_held
            ? `Bạn đang giữ ${state.jobs_held} job. Sau khi huỷ, các job này sẽ không còn giao cho bạn trên CVAT cho đến khi bạn liên kết lại.`
            : 'Bạn có thể liên kết lại bất cứ lúc nào.'}
          submitLabel="Huỷ liên kết"
          onClose={() => setConfirm(false)}
          onSubmit={unlink}
          pending={pending}
        >
          {error && <p className="text-sm text-error-primary">{error}</p>}
        </FormDialog>
      )}
    </section>
  )
}

/** Kết quả đẩy job sang CVAT ngay sau khi liên kết / huỷ liên kết. */
function SyncNotice({ state }: { state: CvatLinkState }) {
  if (!state.sync) {
    if (state.linked && state.jobs_held) {
      return <p className="mt-4 text-sm text-tertiary">Bạn đang giữ {state.jobs_held} job — mở tab <b>Jobs</b> trong CVAT để làm.</p>
    }
    return null
  }
  if (state.sync.error) {
    return (
      <div role="alert" className="mt-5 rounded-xl bg-primary p-4 text-sm ring-1 ring-yellow-200 ring-inset">
        <p className="font-semibold text-warning-primary">Đã liên kết, nhưng chưa đồng bộ được job sang CVAT</p>
        <p className="mt-0.5 text-tertiary">{state.sync.error} — VanoHub sẽ thử lại ở lần đồng bộ batch tiếp theo. Báo PM nếu lỗi kéo dài.</p>
      </div>
    )
  }
  if (!state.linked) return null
  return (
    <div role="status" className="mt-5 rounded-xl bg-secondary p-4 text-sm text-tertiary">
      {state.sync.pushed
        ? <>Đã giao <b className="text-secondary">{state.sync.pushed} job</b> cho bạn trên CVAT. Mở tab <b>Jobs</b> trong CVAT để làm.</>
        : state.jobs_held ? <>Các job bạn đang giữ đã có sẵn trên CVAT.</> : <>Hiện bạn chưa giữ job nào.</>}
    </div>
  )
}

function LinkForm({ cvatUrl, onLinked }: { cvatUrl: string; onLinked: (s: CvatLinkState) => void }) {
  const [token, setToken] = useState('')
  const [show, setShow] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const base = cvatUrl.replace(/\/$/, '')

  async function submit() {
    if (!token.trim()) {
      setError('Dán Access Token tạo trong CVAT.')
      return
    }
    setPending(true)
    setError(null)
    try {
      onLinked(await linkCvat(token.trim()))
      setToken('')
    } catch (e) {
      setError(getErrorMessage(e))
    } finally {
      setPending(false)
    }
  }

  const steps = [
    { title: 'Đăng nhập CVAT', note: 'Dùng đúng tài khoản bạn làm việc hằng ngày trên CVAT.' },
    { title: 'Tạo API Token', note: 'Bấm tên tài khoản (góc trên bên phải) → Profile → tab Security → Create API Token. Bật “Read-only” là đủ, nên đặt ngày hết hạn (Expires) ngắn. Copy token ngay vì CVAT chỉ hiện một lần.' },
    { title: 'Dán token vào ô bên dưới', note: 'VanoHub kiểm tra token thuộc tài khoản CVAT nào rồi bỏ token đi.' },
  ]

  return (
    <SectionCard title="Liên kết tài khoản" description="Liên kết bằng Access Token của CVAT — không cần nhập mật khẩu CVAT."
      actions={base && <Button size="sm" color="secondary" iconTrailing={LinkExternal01} href={base} target="_blank" rel="noreferrer">Mở CVAT</Button>}>
      <ol className="flex flex-col">
        {steps.map((step, index) => (
          <li key={step.title} className="relative flex gap-4 pb-5 last:pb-0">
            {index < steps.length - 1 && <span aria-hidden className="absolute top-9 bottom-1 left-4 w-px bg-border-secondary" />}
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

      <form className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-start" onSubmit={(e) => { e.preventDefault(); submit() }}>
        <div className="relative flex-1">
          <Input
            aria-label="CVAT Access Token"
            placeholder="Dán Access Token của CVAT"
            type={show ? 'text' : 'password'}
            autoComplete="off"
            value={token}
            onChange={setToken}
            isInvalid={error != null}
            hint={error ?? undefined}
          />
          <button type="button" onClick={() => setShow((s) => !s)} aria-label={show ? 'Ẩn token' : 'Hiện token'}
            className="absolute top-2.5 right-3 text-fg-quaternary hover:text-fg-quaternary_hover">
            {show ? <EyeOff className="size-5" /> : <Eye className="size-5" />}
          </button>
        </div>
        <Button type="submit" size="md" iconLeading={Link01} isLoading={pending}>Liên kết</Button>
      </form>
    </SectionCard>
  )
}

function AccountMark({ label, className }: { label: string; className?: string }) {
  return (
    <span className={`flex size-12 items-center justify-center rounded-xl text-sm font-bold text-white shadow-xs ${className ?? ''}`}>
      {label}
    </span>
  )
}
