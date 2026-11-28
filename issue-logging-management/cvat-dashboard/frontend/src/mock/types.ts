export type Role = 'admin' | 'pm' | 'lead' | 'annotator'

export interface User {
  id: string
  name: string
  cvatUsername: string
  role: Role
  teamIds: string[]
  /** Thành viên được chọn làm QC1 (ngoài team lead). */
  isQc: boolean
  /** ID cá nhân hiển thị (vd 2828). */
  employeeId: number
}

export type WorkStep = 'annotate' | 'qc1' | 'qc2'

export interface Team {
  id: string
  name: string
  leadId: string
  memberIds: string[]
  /** Các bước team được phép làm. */
  allowedSteps: WorkStep[]
  /** Được tham gia luồng QA/audit (thấy hàng QC trong Hàng đợi). */
  canQa: boolean
  /** PM sở hữu team (R1). '' = chưa có PM. */
  pmId: string
}

export interface DataType {
  id: string
  name: string
  shapeType: 'cuboid' | 'rectangle'
  kpiPerDay: number
  thresholdCm: number
  thresholdDeg: number
  errorCategories: string[]
}

export interface Partner { name: string; contact: string; email: string; contractNote: string }
export type ProjectStatus = 'running' | 'paused' | 'done'

export interface Project {
  id: string
  name: string
  dataTypeId: string
  /** PM phụ trách (người đầu = PM chính). Team của dự án suy ra từ đây: `projectTeamIds` (R1). */
  pmIds: string[]
  /** Mã dự án hiển thị (vd PRJ-P1-123). */
  code: string
  partner: Partner
  /** ISO — lần gần nhất admin đổi danh sách PM phụ trách (`pmIds`, người đầu = PM chính). */
  assignedAt: string
  /** ISO — hạn hoàn thành dự án. */
  dueAt: string
  status: ProjectStatus
}

export interface Dataset {
  id: string
  name: string
  nasPath: string
  dataTypeId: string
  projectId: string
  fileCount: number
  frameCount: number
  status: 'active' | 'archived'
  /** ISO — ngày nhận. */
  receivedAt: string
  /** ISO — lần giao (chia) gần nhất. */
  lastDistributedAt: string | null
  /** ISO — hạn lô dataset; null = chưa đặt. */
  dueAt: string | null
  /** 0–100: tỉ lệ đã tiền xử lý. */
  preprocessedPct: number
  /** 0–100: tỉ lệ đã lên CVAT (≤ preprocessedPct). */
  onCvatPct: number
  sceneCount: number
  partnerNote: string
}

export type BatchStatus = 'pending' | 'in_progress' | 'in_audit' | 'ready' | 'delivered' | 'released'

/** Người phụ trách theo bước qc1/qc2 (user). Team gán nhãn nằm ở `Batch.teamId` (R2). */
export interface StepPic {
  qc1?: string
  qc2?: string
}

/** Batch ≈ 1 task CVAT. Danh sách job lấy bằng `jobsOfBatch(state, batchId)` (không lưu jobIds để khỏi lệch). */
export interface Batch {
  id: string
  name: string
  datasetId: string
  projectId: string
  cvatTaskId: number
  status: BatchStatus
  /** Team giữ batch (R2: một batch = một team). null = chưa giao (pending). */
  teamId: string | null
  stepPic: StepPic
  /** ISO. Khoá khi autoLockAt < state.now (xem `isBatchLocked`). */
  autoLockAt: string | null
  /** ISO — hạn giao đối tác. null = chưa đặt. Độc lập với autoLockAt (I2). */
  dueAt: string | null
  /** Số ngày dành cho mỗi bước kiểm tra, dùng để tính lùi hạn mặc định. */
  stepBufferDays: { qc1: number; qc2: number }
  /** Ưu tiên 1..5 (5 = cao nhất). */
  priority: 1 | 2 | 3 | 4 | 5
}

export type BatchEventType =
  | 'distribute' | 'reassign' | 'release' | 'autolock_set' | 'autolock_reset'
  | 'audit_create' | 'audit_job_pass' | 'audit_job_return' | 'audit_pass' | 'audit_fail'
  | 'due_set' | 'due_clear' | 'priority_set' | 'transfer'

/** Bất biến: chỉ append. */
export interface BatchEvent {
  id: string
  batchId: string
  at: string
  actorId: string
  type: BatchEventType
  detail: string
}

export type AuditStatus = 'open' | 'passed' | 'failed'

/** QC2 lấy mẫu. levels cố định [100,30,10]; mức gợi ý = levels[currentLevelIndex]; `percent` = % thực lấy mẫu (người tạo có thể đổi). */
export interface Audit {
  id: string
  createdAt: string
  createdBy: string
  projectId: string
  batchIds: string[]
  levels: number[]
  currentLevelIndex: number
  /** % job đủ điều kiện đã lấy mẫu (1–100). */
  percent: number
  sampledJobIds: string[]
  /** Kết quả chấm từng job mẫu (chưa chấm = không có khoá). */
  results: Record<string, 'passed' | 'returned'>
  status: AuditStatus
  closedAt: string | null
}

export type JobStage =
  | 'unassigned_pool'
  | 'team_pool'
  | 'anno_in_progress'
  | 'qc1_pending'
  | 'qc1_in_progress'
  | 'qc2_pending'
  | 'qc2_in_progress'
  | 'ready_to_deliver'
  | 'delivered'

export interface Job {
  id: string
  cvatJobId: number
  batchId: string
  projectId: string
  teamId: string | null
  annotatorId: string | null
  qc1Id: string | null
  qc2Id: string | null
  stage: JobStage
  /** Số cuboid/shape prelabel gốc của job. */
  prelabelCuboids: number
  /** Số cuboid đã sửa — chỉ ghi nhận ở lần nộp ĐẦU. */
  editedCuboids: number
  frames: number
  reworkCount: number
  firstSubmittedAt: string | null
  /** Mô tả lệch giữa dashboard và CVAT (nếu có). */
  cvatDrift?: string
  /** Ghi đè hạn theo bước (ISO). Thiếu khoá = dùng hạn mặc định tính từ batch. */
  due?: Partial<Record<WorkStep, string>>
}

export type JobEventType =
  | 'handover'
  | 'distribute'
  | 'assign'
  | 'reassign'
  | 'submit'
  | 'resubmit'
  | 'qc1_start'
  | 'qc1_pass'
  | 'qc1_return'
  | 'qc2_start'
  | 'qc2_pass'
  | 'qc2_return_qc1'
  | 'qc2_return_anno'
  | 'deliver'
  | 'due_override'

/** Bất biến: chỉ append, không sửa/xoá. */
export interface JobEvent {
  id: string
  jobId: string
  at: string
  actorId: string
  type: JobEventType
  fromStage: JobStage | null
  toStage: JobStage
  reason?: string
  errorCategory?: string
  /** Những người bị tính +1 rework. */
  reworkAgainst?: string[]
}

export type DeadlineStatus = 'none' | 'on_track' | 'due_soon' | 'overdue'

export interface KpiDaily {
  userId: string
  /** YYYY-MM-DD */
  date: string
  editedCuboids: number
}

export type DatasetPreset = 'default' | 'workflow_test'

export interface DashboardState {
  /** Phiên bản schema lưu localStorage (R10). */
  schemaVersion: 2
  users: User[]
  teams: Team[]
  dataTypes: DataType[]
  projects: Project[]
  jobs: Job[]
  events: JobEvent[]
  kpiDaily: KpiDaily[]
  datasets: Dataset[]
  batches: Batch[]
  batchEvents: BatchEvent[]
  audits: Audit[]
  /** Yêu thích của từng user (id batch hoặc project) cho Hàng đợi. */
  favorites: Record<string, string[]>
  currentUserId: string
  /** Mốc "bây giờ" cố định của mock (ISO) để số liệu ổn định. */
  now: string
  /** Bộ dữ liệu mẫu đang chọn. */
  datasetPreset?: DatasetPreset
}

export interface DistributionPreviewRow {
  teamId: string
  jobIds: string[]
  jobCount: number
  totalCuboids: number
}
