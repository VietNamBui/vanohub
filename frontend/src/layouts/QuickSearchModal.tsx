import { AlertTriangle, CheckCircle, SearchLg } from '@untitledui/icons'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { listJobs, quickSearchAnnotator } from '../features/jobs/api'
import type { AnnotatorQuickSearchResult } from '../features/jobs/types'
import { getProject } from '../features/projects/api'
import type { Capability } from '../shared/types/capabilities'
import { cx } from '@/utils/cx'

interface QuickPage {
  id: string
  label: string
  path: string
  kind: 'dashboard' | 'rework' | 'guideline' | 'page'
  cap?: Capability | Capability[]
}

interface QuickJobItem {
  id: number
  name: string
  status: string
  status_label: string
  rework_round: number
  progress_percent: number
  targetPath: string
}

interface Props {
  open: boolean
  projectId: number | null
  onClose: () => void
}

/** Tìm kiếm nhanh (⌘K): tra cứu job theo phạm vi quyền và nhảy nhanh tới các màn hình phù hợp. */
export default function QuickSearchModal({ open, projectId, onClose }: Props) {
  if (!open) return null
  return <QuickSearchPalette projectId={projectId} onClose={onClose} />
}

function QuickSearchPalette({ projectId, onClose }: { projectId: number | null; onClose: () => void }) {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [capsState, setCapsState] = useState<{ projectId: number; caps: Capability[] } | null>(null)
  const [jobs, setJobs] = useState<QuickJobItem[]>([])
  const [loading, setLoading] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)

  useEffect(() => {
    if (!projectId) return
    let cancelled = false
    getProject(projectId)
      .then((proj) => {
        if (!cancelled) setCapsState({ projectId, caps: proj.my_capabilities })
      })
      .catch(() => {
        if (!cancelled) setCapsState({ projectId, caps: [] })
      })
    return () => {
      cancelled = true
    }
  }, [projectId])

  const caps = projectId && capsState?.projectId === projectId ? capsState.caps : null
  const canAnnotate = caps?.includes('annotate_jobs') ?? false
  const canViewAllJobs = caps?.includes('view_jobs') ?? false
  const canSearchJobs = projectId != null && (canAnnotate || canViewAllJobs)

  const pages = useMemo<QuickPage[]>(() => {
    const base = projectId ? `/projects/${projectId}` : null
    const can = (cap?: Capability | Capability[]) => {
      if (!cap) return true
      if (!caps) return false
      return Array.isArray(cap) ? cap.some((c) => caps.includes(c)) : caps.includes(cap)
    }

    const list: QuickPage[] = base
      ? (
          [
            { id: 'p-ann-dash', label: 'Tổng quan cá nhân', path: `${base}/annotator/dashboard`, kind: 'dashboard', cap: 'annotate_jobs' },
            { id: 'p-ann-jobs', label: 'Job của tôi', path: `${base}/annotator/jobs`, kind: 'page', cap: 'annotate_jobs' },
            { id: 'p-ann-rework', label: 'Cần sửa', path: `${base}/annotator/rework`, kind: 'rework', cap: 'annotate_jobs' },
            { id: 'p-ann-analytics', label: 'Phân tích cá nhân (P2)', path: `${base}/annotator/analytics`, kind: 'dashboard', cap: 'annotate_jobs' },
            { id: 'p-requests', label: canAnnotate ? 'Yêu cầu của tôi' : 'Yêu cầu xử lý', path: `${base}/annotator/requests`, kind: 'page', cap: ['annotate_jobs', 'manage_jobs'] },
            { id: 'p-pm-dash', label: 'Tổng quan dự án', path: `${base}/overview`, kind: 'dashboard', cap: 'view_dashboard' },
            { id: 'p-datasets', label: 'Datasets', path: `${base}/datasets`, kind: 'page', cap: 'view_jobs' },
            { id: 'p-batches', label: 'Batches', path: `${base}/batches`, kind: 'page', cap: 'view_jobs' },
            { id: 'p-jobs', label: 'Jobs', path: `${base}/jobs`, kind: 'page', cap: 'view_jobs' },
            { id: 'p-teams', label: 'Team & Members', path: `${base}/teams`, kind: 'page', cap: 'manage_team' },
            { id: 'p-qc1-dash', label: 'Tổng quan QC1', path: `${base}/qc1/dashboard`, kind: 'dashboard', cap: ['perform_qc1', 'view_dashboard'] },
            { id: 'p-qc1-work', label: 'Job kiểm tra QC1', path: `${base}/qc1/work`, kind: 'page', cap: 'perform_qc1' },
            { id: 'p-qc2-dash', label: 'Tổng quan QC2', path: `${base}/qc2/dashboard`, kind: 'dashboard', cap: 'perform_audit' },
            { id: 'p-qc2-work', label: 'Job audit QC2', path: `${base}/qc2/work`, kind: 'page', cap: 'perform_audit' },
            { id: 'p-audits', label: 'Quản lý Audit', path: `${base}/audits`, kind: 'page', cap: 'manage_audits' },
            { id: 'p-guide', label: 'Hướng dẫn gán nhãn', path: `${base}/guidelines`, kind: 'guideline', cap: 'view_guidelines' },
            { id: 'p-settings', label: 'Cài đặt tài khoản', path: `${base}/account/settings`, kind: 'page', cap: 'view_project' },
          ] satisfies QuickPage[]
        ).filter((item) => can(item.cap))
      : [
          { id: 'p-projects', label: 'Dự án của tôi', path: '/projects', kind: 'page' },
          { id: 'p-settings', label: 'Cài đặt tài khoản', path: '/account/settings', kind: 'page' },
        ]
    const needle = query.trim().toLowerCase()
    if (!needle) return list.slice(0, 6)
    return list.filter((item) => item.label.toLowerCase().includes(needle))
  }, [projectId, caps, canAnnotate, query])

  useEffect(() => {
    if (!projectId || !canSearchJobs) return
    let cancelled = false
    const timer = setTimeout(async () => {
      setLoading(true)
      try {
        if (canAnnotate) {
          const res: AnnotatorQuickSearchResult = await quickSearchAnnotator(projectId, query)
          if (!cancelled) {
            setJobs(
              res.jobs.map((j) => ({
                ...j,
                targetPath: `/projects/${projectId}/annotator/jobs/${j.id}`,
              })),
            )
          }
        } else if (canViewAllJobs) {
          const res = await listJobs(projectId, { search: query, page_size: 8 })
          if (!cancelled) {
            setJobs(
              res.results.map((j) => ({
                id: j.id,
                name: j.name,
                status: j.status,
                status_label: j.status_label,
                rework_round: j.rework_round,
                progress_percent: j.progress_percent ?? 0,
                targetPath: `/projects/${projectId}/jobs?search=${encodeURIComponent(j.name)}`,
              })),
            )
          }
        }
      } catch {
        if (!cancelled) setJobs([])
      } finally {
        if (!cancelled) setLoading(false)
      }
    }, 120)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [projectId, canSearchJobs, canAnnotate, canViewAllJobs, query])

  const visibleJobs = useMemo(() => (canSearchJobs ? jobs : []), [canSearchJobs, jobs])

  const flatTargets = useMemo(() => {
    const jobItems = visibleJobs.map((j) => ({
      key: `job-${j.id}`,
      path: j.targetPath,
    }))
    const pageItems = pages.map((p) => ({ key: p.id, path: p.path }))
    return [...jobItems, ...pageItems]
  }, [visibleJobs, pages])

  useEffect(() => {
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
  }, [flatTargets, activeIndex, navigate, onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[12vh] px-4" role="dialog" aria-modal="true" aria-label="Tìm kiếm nhanh">
      <div className="fixed inset-0 bg-[#0C111D]/40 backdrop-blur-[2px]" onClick={onClose} />

      <div className="relative z-10 flex w-full max-w-[640px] flex-col overflow-hidden rounded-xl border border-[#EAECF0] bg-white shadow-2xl">
        <div className="flex items-center gap-3 border-b border-[#EAECF0] px-5 py-3.5">
          <SearchLg className="size-5 shrink-0 text-[#667085]" />
          <input
            autoFocus
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setActiveIndex(0)
            }}
            placeholder={canSearchJobs ? 'Tìm mã job, batch hoặc chuyển nhanh tới trang…' : 'Chuyển nhanh tới trang…'}
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
          {canSearchJobs && (
            <div className="mb-2">
              <div className="px-3 py-1.5 text-xs font-semibold text-[#667085]">Job</div>
              {loading && visibleJobs.length === 0 ? (
                <p className="px-3 py-2 text-sm text-[#667085]">Đang tìm…</p>
              ) : visibleJobs.length === 0 ? (
                <p className="px-3 py-2 text-sm text-[#667085]">Không thấy job phù hợp.</p>
              ) : (
                <ul>
                  {visibleJobs.map((job, idx) => (
                    <li key={job.id}>
                      <button
                        type="button"
                        onMouseEnter={() => setActiveIndex(idx)}
                        onClick={() => {
                          navigate(job.targetPath)
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
                  const flatIdx = visibleJobs.length + idx
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
