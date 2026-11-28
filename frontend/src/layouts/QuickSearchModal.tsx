import { AlertTriangle, BarChart01, BookOpen01, CheckCircle, SearchLg } from '@untitledui/icons'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { Badge } from '@/components/base/badges/badges'
import { listJobs, quickSearchAnnotator } from '../features/jobs/api'
import { JOB_STATUS_LABELS } from '../features/jobs/constants'
import type { JobStatus } from '../features/jobs/types'
import type { ProjectSummary } from '../features/projects/types'
import { listAuditSamples, listQc1Jobs } from '../features/quality/api'
import type { Capability } from '../shared/types/capabilities'
import type { Role } from '../shared/types/roles'
import { cx } from '@/utils/cx'
import { useShell } from './ShellContext'

interface QuickPage {
  id: string
  label: string
  path: string
  kind: 'dashboard' | 'rework' | 'guideline' | 'page'
  keywords?: string
  cap?: Capability | Capability[]
}

interface QuickJobItem {
  id: number
  name: string
  status: JobStatus
  statusLabel: string
  meta: string
  path: string
}

interface Props {
  open: boolean
  projectId: number | null
  currentProject?: ProjectSummary | null
  onClose: () => void
}

const ROLE_CAPS: Record<Role, Capability[]> = {
  project_manager: [
    'view_project',
    'view_dashboard',
    'view_jobs',
    'manage_data',
    'manage_jobs',
    'manage_team',
    'manage_settings',
    'manage_audits',
    'perform_audit',
    'manage_quality_catalog',
    'view_guidelines',
    'manage_delivery',
    'send_announcement',
    'view_activity',
  ],
  qc2: ['view_project', 'view_guidelines', 'perform_audit'],
  qc1: ['view_project', 'view_guidelines', 'perform_qc1'],
  annotator: ['view_project', 'view_guidelines', 'annotate_jobs'],
}

function capabilitiesFromRoles(roles: Role[]): Capability[] {
  const set = new Set<Capability>()
  for (const role of roles) {
    for (const cap of ROLE_CAPS[role] ?? []) {
      set.add(cap)
    }
  }
  return [...set]
}

/** Tìm kiếm nhanh (⌘K): tra cứu job theo quyền trong organization và nhảy nhanh tới các trang được phép. */
export default function QuickSearchModal({ open, projectId, currentProject, onClose }: Props) {
  if (!open) return null
  return <QuickSearchPalette projectId={projectId} currentProject={currentProject} onClose={onClose} />
}

function QuickSearchPalette({
  projectId,
  currentProject,
  onClose,
}: {
  projectId: number | null
  currentProject?: ProjectSummary | null
  onClose: () => void
}) {
  const navigate = useNavigate()
  const { projectCapabilities } = useShell()
  const [query, setQuery] = useState('')
  const [jobs, setJobs] = useState<QuickJobItem[]>([])
  const [loading, setLoading] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)

  const capSet = useMemo(() => {
    if (projectId == null) return new Set<Capability>()
    if (projectCapabilities && projectCapabilities.projectId === projectId) {
      return new Set<Capability>(projectCapabilities.capabilities)
    }
    if (currentProject && currentProject.id === projectId) {
      return new Set<Capability>(capabilitiesFromRoles(currentProject.my_roles))
    }
    return new Set<Capability>()
  }, [projectId, projectCapabilities, currentProject])

  const searchMode = useMemo<'annotate' | 'jobs' | 'qc1' | 'qc2' | 'none'>(() => {
    if (projectId == null) return 'none'
    if (capSet.has('view_jobs')) return 'jobs'
    if (capSet.has('annotate_jobs')) return 'annotate'
    if (capSet.has('perform_qc1')) return 'qc1'
    if (capSet.has('perform_audit')) return 'qc2'
    return 'none'
  }, [projectId, capSet])

  const pages = useMemo<QuickPage[]>(() => {
    const can = (cap: Capability) => capSet.has(cap)
    const allowed = (cap?: Capability | Capability[]) => {
      if (!cap) return true
      return Array.isArray(cap) ? cap.some(can) : can(cap)
    }

    const base = projectId ? `/projects/${projectId}` : null
    const allPages: QuickPage[] = base
      ? (
          [
            { id: 'p-overview', label: 'Tổng quan', path: `${base}/overview`, kind: 'dashboard', keywords: 'overview dashboard pm', cap: 'view_dashboard' },
            { id: 'p-dash', label: 'Tổng quan cá nhân', path: `${base}/annotator/dashboard`, kind: 'dashboard', keywords: 'annotator dashboard', cap: 'annotate_jobs' },
            { id: 'p-ann-jobs', label: 'Job của tôi', path: `${base}/annotator/jobs`, kind: 'page', keywords: 'annotator jobs', cap: 'annotate_jobs' },
            { id: 'p-rework', label: 'Cần sửa', path: `${base}/annotator/rework`, kind: 'rework', keywords: 'rework', cap: 'annotate_jobs' },
            {
              id: 'p-requests',
              label: can('manage_jobs') && !can('annotate_jobs') ? 'Yêu cầu từ Annotator' : 'Yêu cầu của tôi',
              path: `${base}/annotator/requests`,
              kind: 'page',
              keywords: 'requests dispute data issue phan hoi',
              cap: ['annotate_jobs', 'manage_jobs'],
            },
            { id: 'p-analytics', label: 'Phân tích cá nhân', path: `${base}/annotator/analytics`, kind: 'dashboard', keywords: 'analytics', cap: 'annotate_jobs' },
            { id: 'p-datasets', label: 'Projects', path: `${base}/datasets`, kind: 'page', keywords: 'datasets projects', cap: 'view_jobs' },
            { id: 'p-batches', label: 'Tasks', path: `${base}/batches`, kind: 'page', keywords: 'batches tasks', cap: 'view_jobs' },
            { id: 'p-jobs', label: 'Jobs', path: `${base}/jobs`, kind: 'page', keywords: 'jobs', cap: 'view_jobs' },
            { id: 'p-queue', label: 'Data Queue', path: `${base}/queue`, kind: 'page', keywords: 'queue hang cho', cap: 'view_jobs' },
            { id: 'p-teams', label: 'Team & Members', path: `${base}/teams`, kind: 'page', keywords: 'teams members nhan su', cap: 'manage_team' },
            { id: 'p-workload', label: 'Tải công việc', path: `${base}/workload`, kind: 'page', keywords: 'workload', cap: ['manage_team', 'view_dashboard'] },
            { id: 'p-ranking', label: 'Xếp hạng team', path: `${base}/team-ranking`, kind: 'dashboard', keywords: 'team ranking', cap: 'view_dashboard' },
            { id: 'p-qc2-dash', label: 'Tổng quan QC2', path: `${base}/qc2/dashboard`, kind: 'dashboard', keywords: 'qc2 dashboard', cap: 'perform_audit' },
            { id: 'p-qc2-work', label: 'Job audit QC2', path: `${base}/qc2/work`, kind: 'page', keywords: 'qc2 work audit', cap: 'perform_audit' },
            { id: 'p-audits', label: 'Audit QC2 theo task', path: `${base}/audits`, kind: 'page', keywords: 'audits qc2', cap: 'manage_audits' },
            { id: 'p-qc2-strategy', label: 'Quy tắc QC2', path: `${base}/qc2/strategy`, kind: 'page', keywords: 'audit strategy sampling qc2', cap: 'manage_audits' },
            { id: 'p-qc1-dash', label: 'Tổng quan QC1', path: `${base}/qc1/dashboard`, kind: 'dashboard', keywords: 'qc1 dashboard', cap: ['perform_qc1', 'view_dashboard'] },
            { id: 'p-qc1-work', label: 'Job kiểm tra QC1', path: `${base}/qc1/work`, kind: 'page', keywords: 'qc1 work', cap: 'perform_qc1' },
            { id: 'p-delivery', label: 'Bàn giao', path: `${base}/delivery`, kind: 'page', keywords: 'delivery deliveries ban giao', cap: 'manage_delivery' },
            { id: 'p-settings-org', label: 'Cấu hình organization', path: `${base}/settings`, kind: 'page', keywords: 'settings config rework sampling kpi cau hinh organization', cap: 'manage_settings' },
            { id: 'p-activity', label: 'Nhật ký hoạt động', path: `${base}/activity`, kind: 'page', keywords: 'activity log audit trail nhat ky hoat dong', cap: 'view_activity' },
            { id: 'p-err-cat', label: 'Danh mục lỗi', path: `${base}/error-categories`, kind: 'page', keywords: 'error categories danh muc loi', cap: 'manage_quality_catalog' },
            { id: 'p-guide', label: 'Guidelines', path: `${base}/guidelines`, kind: 'guideline', keywords: 'guidelines huong dan', cap: 'view_guidelines' },
            { id: 'p-ann', label: 'Thông báo', path: `${base}/announcements`, kind: 'page', keywords: 'announcements thong bao', cap: 'view_project' },
            { id: 'p-cvat', label: 'Liên kết CVAT', path: `${base}/cvat-link`, kind: 'page', keywords: 'cvat link', cap: 'view_project' },
            { id: 'p-settings', label: 'Cài đặt tài khoản', path: `${base}/account/settings`, kind: 'page', keywords: 'settings account cai dat', cap: 'view_project' },
          ] satisfies QuickPage[]
        ).filter((item) => allowed(item.cap))
      : [
          { id: 'p-projects', label: 'Organization của tôi', path: '/projects', kind: 'page', keywords: 'organizations projects' },
          { id: 'p-cvat', label: 'Liên kết CVAT', path: '/cvat-link', kind: 'page', keywords: 'cvat link' },
          { id: 'p-settings', label: 'Cài đặt tài khoản', path: '/account/settings', kind: 'page', keywords: 'settings account' },
        ]

    const needle = query.trim().toLowerCase()
    if (!needle) return allPages.slice(0, 6)
    return allPages.filter(
      (item) => item.label.toLowerCase().includes(needle) || (item.keywords?.toLowerCase().includes(needle) ?? false),
    )
  }, [projectId, capSet, query])

  useEffect(() => {
    if (projectId == null || searchMode === 'none') return
    let cancelled = false
    const timer = setTimeout(async () => {
      setLoading(true)
      try {
        const trimmed = query.trim()
        if (searchMode === 'annotate') {
          const res = await quickSearchAnnotator(projectId, trimmed)
          if (!cancelled) {
            setJobs(
              res.jobs.map((job) => ({
                id: job.id,
                name: job.name,
                status: job.status,
                statusLabel:
                  job.status === 'rework' ? 'Cần sửa' : job.status === 'annotating' ? 'Đang làm' : job.status_label,
                meta: job.rework_round > 0 && job.status === 'rework' ? `Vòng ${job.rework_round}` : `${job.progress_percent}%`,
                path: `/projects/${projectId}/annotator/jobs/${job.id}`,
              })),
            )
          }
        } else if (searchMode === 'jobs') {
          const res = await listJobs(projectId, { search: trimmed || undefined, page_size: 8 })
          if (!cancelled) {
            setJobs(
              res.results.map((job) => ({
                id: job.id,
                name: job.name,
                status: job.status,
                statusLabel: job.status_label || JOB_STATUS_LABELS[job.status],
                meta: job.batch_name,
                path: `/projects/${projectId}/jobs?search=${encodeURIComponent(job.name)}`,
              })),
            )
          }
        } else if (searchMode === 'qc1') {
          const res = await listQc1Jobs(projectId, { search: trimmed || undefined, page_size: 8 })
          if (!cancelled) {
            setJobs(
              res.results.map((job) => ({
                id: job.id,
                name: job.name,
                status: job.status,
                statusLabel: job.status_label || JOB_STATUS_LABELS[job.status],
                meta: job.batch_name,
                path: `/projects/${projectId}/qc1/work?job=${job.id}`,
              })),
            )
          }
        } else if (searchMode === 'qc2') {
          const samples = await listAuditSamples(projectId, { open: true })
          const needle = trimmed.toLowerCase()
          const filtered = samples
            .filter(
              (s) =>
                !needle ||
                [s.job.name, s.job.batch_name, String(s.job.cvat_job_id ?? ''), String(s.job.id)].some((v) =>
                  v.toLowerCase().includes(needle),
                ),
            )
            .slice(0, 8)
          if (!cancelled) {
            setJobs(
              filtered.map((s) => ({
                id: s.id,
                name: s.job.name,
                status: s.job.status,
                statusLabel: JOB_STATUS_LABELS[s.job.status] ?? s.job.status,
                meta: `${s.job.batch_name} · ${s.frames.length} frame`,
                path: `/projects/${projectId}/qc2/work`,
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
  }, [projectId, searchMode, query])

  const visibleJobs = useMemo(() => (searchMode === 'none' ? [] : jobs), [searchMode, jobs])

  const flatTargets = useMemo(() => {
    const jobItems = visibleJobs.map((j) => ({ key: `job-${j.id}`, path: j.path }))
    const pageItems = pages.map((p) => ({ key: p.id, path: p.path }))
    return [...jobItems, ...pageItems]
  }, [visibleJobs, pages])

  const safeActiveIndex = flatTargets.length ? Math.min(activeIndex, flatTargets.length - 1) : 0

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
      } else if (e.key === 'Enter' && flatTargets[safeActiveIndex]) {
        e.preventDefault()
        navigate(flatTargets[safeActiveIndex].path)
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [flatTargets, safeActiveIndex, navigate, onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[12vh]" role="dialog" aria-modal="true" aria-label="Tìm kiếm nhanh">
      <div className="fixed inset-0 bg-overlay/50 backdrop-blur-[2px]" onClick={onClose} />

      <div className="relative z-10 flex w-full max-w-160 flex-col overflow-hidden rounded-xl border border-secondary bg-primary shadow-2xl">
        <div className="flex items-center gap-3 border-b border-secondary px-5 py-3.5">
          <SearchLg className="size-5 shrink-0 text-fg-quaternary" />
          <input
            autoFocus
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setActiveIndex(0)
            }}
            placeholder={
              searchMode !== 'none'
                ? 'Tìm mã job, task hoặc chuyển nhanh tới trang…'
                : 'Chuyển nhanh tới trang…'
            }
            className="w-full bg-transparent text-md text-primary outline-none placeholder:text-placeholder"
          />
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 cursor-pointer rounded border border-secondary bg-secondary px-2 py-0.5 text-xs font-medium text-tertiary transition hover:bg-primary_hover hover:text-secondary"
          >
            Esc
          </button>
        </div>

        <div className="max-h-95 overflow-y-auto p-2">
          {searchMode !== 'none' && (
            <div className="mb-2">
              <div className="px-3 py-1.5 text-xs font-semibold text-tertiary">Job</div>
              {loading && visibleJobs.length === 0 ? (
                <p className="px-3 py-2 text-sm text-tertiary">Đang tìm…</p>
              ) : visibleJobs.length === 0 ? (
                <p className="px-3 py-2 text-sm text-tertiary">Không thấy job phù hợp.</p>
              ) : (
                <ul>
                  {visibleJobs.map((job, idx) => (
                    <li key={job.id}>
                      <button
                        type="button"
                        onMouseEnter={() => setActiveIndex(idx)}
                        onClick={() => {
                          navigate(job.path)
                          onClose()
                        }}
                        className={cx(
                          'flex w-full cursor-pointer items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition',
                          safeActiveIndex === idx ? 'bg-active text-primary' : 'text-secondary hover:bg-primary_hover',
                        )}
                      >
                        <span className="flex min-w-0 items-center gap-2.5">
                          <span className="flex size-5 shrink-0 items-center justify-center text-fg-tertiary">
                            {job.status === 'rework' ? (
                              <AlertTriangle className="size-4 text-fg-warning-primary" />
                            ) : (
                              <CheckCircle className="size-4" />
                            )}
                          </span>
                          <span className="truncate font-medium text-primary">{job.name}</span>
                          <Badge size="sm" type="pill-color" color={job.status === 'rework' ? 'warning' : 'gray'}>
                            {job.statusLabel}
                          </Badge>
                        </span>
                        <span className="shrink-0 text-sm text-tertiary tabular-nums">{job.meta}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          <div>
            <div className="px-3 py-1.5 text-xs font-semibold text-tertiary">Trang</div>
            {pages.length === 0 ? (
              <p className="px-3 py-2 text-sm text-tertiary">Không có trang khớp từ khoá.</p>
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
                          safeActiveIndex === flatIdx ? 'bg-active text-primary' : 'text-secondary hover:bg-primary_hover',
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
  if (kind === 'rework') return <AlertTriangle className="size-4 text-fg-warning-primary" />
  if (kind === 'dashboard') return <BarChart01 className="size-4 text-fg-tertiary" />
  if (kind === 'guideline') return <BookOpen01 className="size-4 text-fg-tertiary" />
  return <CheckCircle className="size-4 text-fg-tertiary" />
}
