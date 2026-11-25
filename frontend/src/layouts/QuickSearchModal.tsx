import { AlertTriangle, CheckCircle, SearchLg } from '@untitledui/icons'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { quickSearchAnnotator } from '../features/jobs/api'
import type { AnnotatorQuickSearchResult } from '../features/jobs/types'
import { cx } from '@/utils/cx'

interface QuickPage {
  id: string
  label: string
  path: string
  kind: 'dashboard' | 'rework' | 'guideline' | 'page'
}

interface Props {
  open: boolean
  projectId: number | null
  onClose: () => void
}

/** Tìm kiếm nhanh (⌘K): tra cứu job cá nhân (PQ01) và nhảy nhanh tới các màn hình Annotator. */
export default function QuickSearchModal({ open, projectId, onClose }: Props) {
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const [query, setQuery] = useState('')
  const [jobs, setJobs] = useState<AnnotatorQuickSearchResult['jobs']>([])
  const [loading, setLoading] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)

  const pages = useMemo<QuickPage[]>(() => {
    const base = projectId ? `/projects/${projectId}` : null
    const list: QuickPage[] = base
      ? [
          { id: 'p-dash', label: 'Tổng quan cá nhân', path: `${base}/annotator/dashboard`, kind: 'dashboard' },
          { id: 'p-jobs', label: 'Job của tôi', path: `${base}/annotator/jobs`, kind: 'page' },
          { id: 'p-rework', label: 'Cần sửa', path: `${base}/annotator/rework`, kind: 'rework' },
          { id: 'p-requests', label: 'Yêu cầu của tôi', path: `${base}/annotator/requests`, kind: 'page' },
          { id: 'p-analytics', label: 'Phân tích cá nhân (P2)', path: `${base}/annotator/analytics`, kind: 'dashboard' },
          { id: 'p-guide', label: 'Hướng dẫn gán nhãn', path: `${base}/guidelines`, kind: 'guideline' },
          { id: 'p-settings', label: 'Cài đặt tài khoản', path: `${base}/account/settings`, kind: 'page' },
        ]
      : [
          { id: 'p-projects', label: 'Dự án của tôi', path: '/projects', kind: 'page' },
          { id: 'p-settings', label: 'Cài đặt tài khoản', path: '/account/settings', kind: 'page' },
        ]
    const needle = query.trim().toLowerCase()
    if (!needle) return list.slice(0, 5)
    return list.filter((item) => item.label.toLowerCase().includes(needle))
  }, [projectId, query])

  useEffect(() => {
    if (!open) return
    setQuery('')
    setActiveIndex(0)
    setTimeout(() => inputRef.current?.focus(), 20)
  }, [open])

  useEffect(() => {
    if (!open || !projectId) {
      setJobs([])
      return
    }
    let cancelled = false
    const timer = setTimeout(async () => {
      setLoading(true)
      try {
        const res = await quickSearchAnnotator(projectId, query)
        if (!cancelled) setJobs(res.jobs)
      } catch {
        if (!cancelled) setJobs([])
      } finally {
        if (!cancelled) setLoading(false)
      }
    }, 140)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [open, projectId, query])

  const flatTargets = useMemo(() => {
    const jobItems = jobs.map((j) => ({
      key: `job-${j.id}`,
      path: `/projects/${projectId}/annotator/jobs/${j.id}`,
    }))
    const pageItems = pages.map((p) => ({ key: p.id, path: p.path }))
    return [...jobItems, ...pageItems]
  }, [jobs, pages, projectId])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      } else if (e.key === 'ArrowDown') {
        e.preventDefault()
        setActiveIndex((i) => (flatTargets.length ? (i + 1) % flatTargets.length : 0))
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setActiveIndex((i) => (flatTargets.length ? (i - 1 + flatTargets.length) % flatTargets.length : 0))
      } else if (e.key === 'Enter' && flatTargets[activeIndex]) {
        e.preventDefault()
        navigate(flatTargets[activeIndex].path)
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, flatTargets, activeIndex, navigate, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[12vh] px-4" role="dialog" aria-modal="true" aria-label="Tìm kiếm nhanh">
      <div className="fixed inset-0 bg-[#0C111D]/40 backdrop-blur-[2px]" onClick={onClose} />

      <div className="relative z-10 flex w-full max-w-[640px] flex-col overflow-hidden rounded-xl border border-[#EAECF0] bg-white shadow-2xl">
        <div className="flex items-center gap-3 border-b border-[#EAECF0] px-5 py-3.5">
          <SearchLg className="size-5 shrink-0 text-[#667085]" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setActiveIndex(0)
            }}
            placeholder="Tìm mã job, batch hoặc chuyển nhanh tới trang…"
            className="w-full bg-transparent text-base text-[#101828] outline-none placeholder:text-[#667085]"
          />
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 cursor-pointer rounded border border-[#EAECF0] bg-white px-2 py-0.5 text-[11px] font-medium text-[#667085] hover:bg-[#F9FAFB]"
          >
            Esc
          </button>
        </div>

        <div className="max-h-[380px] overflow-y-auto p-2">
          {projectId != null && (
            <div className="mb-2">
              <div className="px-3 py-1.5 text-xs font-semibold text-[#667085]">Job</div>
              {loading && jobs.length === 0 ? (
                <p className="px-3 py-2 text-sm text-[#667085]">Đang tìm…</p>
              ) : jobs.length === 0 ? (
                <p className="px-3 py-2 text-sm text-[#667085]">Không thấy job phù hợp.</p>
              ) : (
                <ul>
                  {jobs.map((job, idx) => (
                    <li key={job.id}>
                      <button
                        type="button"
                        onMouseEnter={() => setActiveIndex(idx)}
                        onClick={() => {
                          navigate(`/projects/${projectId}/annotator/jobs/${job.id}`)
                          onClose()
                        }}
                        className={cx(
                          'flex w-full cursor-pointer items-center justify-between rounded-lg px-3 py-2.5 text-left text-sm transition',
                          activeIndex === idx ? 'bg-[#F9FAFB] text-[#101828]' : 'text-[#344054] hover:bg-[#F9FAFB]',
                        )}
                      >
                        <span className="flex items-center gap-3">
                          <span className="flex size-5 items-center justify-center text-[#667085]">
                            {job.status === 'rework' ? <AlertTriangle className="size-4" /> : <CheckCircle className="size-4" />}
                          </span>
                          <span className="font-medium text-[#101828]">
                            {job.name} · {job.status === 'rework' ? 'Cần sửa' : job.status === 'annotating' ? 'Đang làm' : job.status_label}
                          </span>
                        </span>
                        <span className="text-sm text-[#667085] tabular-nums">
                          {job.rework_round > 0 && job.status === 'rework' ? `Vòng ${job.rework_round}` : `${job.progress_percent}%`}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          <div>
            <div className="px-3 py-1.5 text-xs font-semibold text-[#667085]">Trang</div>
            {pages.length === 0 ? (
              <p className="px-3 py-2 text-sm text-[#667085]">Không có trang khớp từ khoá.</p>
            ) : (
              <ul>
                {pages.map((page, idx) => {
                  const flatIdx = jobs.length + idx
                  return (
                    <li key={page.id}>
                      <button
                        type="button"
                        onMouseEnter={() => setActiveIndex(flatIdx)}
                        onClick={() => {
                          navigate(page.path)
                          onClose()
                        }}
                        className={cx(
                          'flex w-full cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition',
                          activeIndex === flatIdx ? 'bg-[#F9FAFB] text-[#101828]' : 'text-[#344054] hover:bg-[#F9FAFB]',
                        )}
                      >
                        <PageIcon kind={page.kind} />
                        <span>{page.label}</span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function PageIcon({ kind }: { kind: QuickPage['kind'] }) {
  if (kind === 'rework') return <AlertTriangle className="size-4 text-[#667085]" />
  if (kind === 'dashboard') {
    return (
      <svg className="size-4 text-[#667085]" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7">
        <path d="M4 15V9M10 15V5M16 15v-3" strokeLinecap="round" />
      </svg>
    )
  }
  if (kind === 'guideline') {
    return (
      <svg className="size-4 text-[#667085]" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7">
        <path d="M4 4.5A1.5 1.5 0 0 1 5.5 3h9A1.5 1.5 0 0 1 16 4.5v11a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 4 15.5v-11Z" />
        <path d="M7.5 7h5M7.5 10h5M7.5 13h3" strokeLinecap="round" />
      </svg>
    )
  }
  return <CheckCircle className="size-4 text-[#667085]" />
}
