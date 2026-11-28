import type {
  Audit, Batch, BatchEvent, Dataset, DashboardState, DataType, Job, JobEvent, JobStage, KpiDaily, Partner, Project, Team, User, WorkStep,
} from './types'

export const AUDIT_LEVELS = [100, 30, 10]
export const SEED_NOW = '2026-11-18T09:00:00.000Z'

const DAY_MS = 86_400_000
const HOUR_MS = 3_600_000

/**
 * Hash ổn định (FNV-1a 32-bit + bước trộn fmix32 của MurmurHash3) — cùng chuỗi luôn ra cùng số.
 * Bước trộn cần thiết: id chỉ khác một ký tự (d1/d2) với hash nhân-cộng đơn giản cho số gần nhau
 * ⇒ các dataset/dự án có cùng hạn, cùng số scene.
 */
export function stableHash(text: string): number {
  let h = 0x811c9dc5
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  h ^= h >>> 16
  h = Math.imul(h, 0x85ebca6b)
  h ^= h >>> 13
  h = Math.imul(h, 0xc2b2ae35)
  h ^= h >>> 16
  return h >>> 0
}

/** ISO cách SEED_NOW `days` ngày + `hours` giờ — hạn có giờ lẻ (không tròn) cho số liệu thực tế hơn. */
const addIso = (days: number, hours = 0): string =>
  new Date(new Date(SEED_NOW).getTime() + days * DAY_MS + hours * HOUR_MS).toISOString()

const PARTNERS: Partner[] = [
  { name: 'Đối tác A – AutoDrive Lab', contact: 'Chị Minh Anh', email: 'contact.a@partner-a.example', contractNote: 'Hợp đồng khung 12 tháng, giao theo lô hằng tuần.' },
  { name: 'Đối tác B – Smart Mobility', contact: 'Anh Quốc Bảo', email: 'contact.b@partner-b.example', contractNote: 'Ưu tiên chất lượng; kiểm thu mẫu 30% mỗi lô.' },
  { name: 'Đối tác C – Urban Vision', contact: 'Ms. Lan Nguyen', email: 'contact.c@partner-c.example', contractNote: 'Giao hàng theo đợt, có phạt trễ hạn.' },
  { name: 'Đối tác D – RoadSense Group', contact: 'Mr. Daniel Tran', email: 'contact.d@partner-d.example', contractNote: 'Dữ liệu nhạy cảm, chỉ truy cập qua VPN.' },
  { name: 'Đối tác E – MapWorks Studio', contact: 'Chị Thu Hà', email: 'contact.e@partner-e.example', contractNote: 'Thanh toán theo khối lượng đã nghiệm thu.' },
]
const PARTNER_NOTES = [
  'Ưu tiên cảnh ban đêm.', 'Đối tác yêu cầu giao sớm các cảnh có người đi bộ.', 'Cần kiểm tra lại nhãn xe máy.',
  'Chưa có ghi chú đặc biệt.', 'Bổ sung thêm cảnh mưa trong lần giao sau.', 'Chốt danh sách lớp đối tượng với đối tác trước khi chia job.',
]

/** Trường mới của Project (đối tác, mã, hạn, trạng thái) — xác định theo id. */
function projectExtras(projectId: string): Pick<Project, 'code' | 'partner' | 'assignedAt' | 'dueAt' | 'status'> {
  const h = stableHash(`project:${projectId}`)
  const r = h % 10
  return {
    partner: PARTNERS[h % PARTNERS.length],
    // giao cho PM 20–44 ngày trước mốc seed, 09:00 giờ VN (SEED_NOW là 16:00 VN ⇒ lùi 7 giờ)
    assignedAt: addIso(-(20 + ((h >>> 9) % 25)), -7),
    dueAt: addIso(18 + ((h >>> 3) % 40), (h >>> 6) % 20),
    status: r === 9 ? 'paused' : r === 8 ? 'done' : 'running',
    code: `PRJ-${projectId.toUpperCase()}-${String(100 + (h >>> 5) % 900)}`,
  }
}

/** Trường mới của Dataset (hạn lô, tiền xử lý, lên CVAT, scene, ghi chú đối tác) — xác định theo id. */
function datasetExtras(datasetId: string): Pick<Dataset, 'dueAt' | 'preprocessedPct' | 'onCvatPct' | 'sceneCount' | 'partnerNote'> {
  const h = stableHash(`dataset:${datasetId}`)
  const preprocessedPct = 60 + (h % 41)
  let sceneCount = 20 + ((h >>> 6) % 180)
  if (sceneCount % 10 === 0) sceneCount += 1 // chống số tròn (bội số 10)
  return {
    dueAt: h % 5 === 0 ? null : addIso(6 + ((h >>> 2) % 26), (h >>> 5) % 20),
    preprocessedPct,
    onCvatPct: Math.floor((preprocessedPct * (30 + ((h >>> 4) % 71))) / 100),
    sceneCount,
    partnerNote: PARTNER_NOTES[(h >>> 7) % PARTNER_NOTES.length],
  }
}

/**
 * ★ ưu tiên batch — bảng tường minh, xác định (thay cho hash) để mỗi dataset không có quá 2 batch cùng mức
 * (đa dạng theo Task W1-C): d1 4,5 · d2 2,3,1 · d3 3 · d4 4,2,5,3. Mức cao cho batch đang gấp
 * (b02 sắp hết hạn, b09 quá hạn khoá), thấp cho batch đã giao / xuất kho.
 */
const BATCH_PRIORITY: Record<string, Batch['priority']> = {
  b01: 4, b02: 5, b03: 2, b04: 3, b05: 3, b06: 1, b07: 4, b08: 2, b09: 5, b10: 3,
}
const batchPriority = (batchId: string): Batch['priority'] => BATCH_PRIORITY[batchId] ?? 3

/** mulberry32 — PRNG xác định theo seed. */
export function createRng(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export function seededShuffle<T>(arr: readonly T[], seed: number): T[] {
  const rng = createRng(seed)
  const out = arr.slice()
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1))
    ;[out[i], out[j]] = [out[j], out[i]]
  }
  return out
}

const LAST = ['Nguyễn', 'Trần', 'Lê', 'Phạm', 'Hoàng', 'Vũ', 'Đặng', 'Bùi', 'Đỗ', 'Ngô']
const MID = ['Văn', 'Thị', 'Minh', 'Quốc', 'Thu', 'Hữu', 'Ngọc', 'Gia']
const FIRST = ['An', 'Bình', 'Cường', 'Dũng', 'Giang', 'Hà', 'Hải', 'Hùng', 'Khoa', 'Lan', 'Linh', 'Long',
  'Mai', 'Nam', 'Phong', 'Quân', 'Sơn', 'Thảo', 'Trang', 'Tuấn', 'Vy', 'Yến']

const RETURN_REASONS = [
  'Thiếu object ở các frame cuối', 'Box lệch so với điểm mây', 'Sai hướng xe ở frame 12',
  'Gán sai nhãn xe tải/xe buýt', 'Thiếu thuộc tính occluded', 'Cuboid chưa khít, cần chỉnh lại',
]

export const TEAM_NAMES = ['Team Alpha', 'Team Beta', 'Team Gamma', 'Team Delta', 'Team Epsilon', 'Team Eta']

function isoDay(offsetDays: number): string {
  const d = new Date(SEED_NOW)
  d.setUTCDate(d.getUTCDate() - offsetDays)
  return d.toISOString().slice(0, 10)
}

/** Khởi tạo danh sách người dùng và các team mặc định (chuẩn chung cho cả 2 bộ dữ liệu). */
function createBaseOrg(rng: () => number) {
  const pick = <T,>(a: readonly T[]): T => a[Math.floor(rng() * a.length)]

  const dataTypes: DataType[] = [
    {
      id: 'dt-lidar', name: 'LiDAR 3D', shapeType: 'cuboid', kpiPerDay: 1200, thresholdCm: 1, thresholdDeg: 0.5,
      errorCategories: ['Sai nhãn', 'Thiếu object', 'Box lệch', 'Sai hướng', 'Sai thuộc tính'],
    },
    {
      id: 'dt-bbox', name: '2D Bounding Box', shapeType: 'rectangle', kpiPerDay: 3000, thresholdCm: 0, thresholdDeg: 0,
      errorCategories: ['Sai nhãn', 'Thiếu object', 'Box lệch', 'Sai thuộc tính'],
    },
  ]

  const users: User[] = []
  let uSeq = 0
  const mkName = () => `${pick(LAST)} ${pick(MID)} ${pick(FIRST)}`
  const addUser = (role: User['role'], teamIds: string[], isQc = false, name?: string): User => {
    uSeq++
    const u: User = {
      id: `u${String(uSeq).padStart(2, '0')}`, name: name ?? mkName(), cvatUsername: `cvat_user_${uSeq}`,
      role, teamIds, isQc, employeeId: 2826 + uSeq,
    }
    users.push(u)
    return u
  }
  const admin = addUser('admin', [], false, 'Quản Trị Viên')
  const pms = [addUser('pm', [], false, 'Trần Minh PM'), addUser('pm', [], false, 'Lê Thu PM'), addUser('pm', [], false, 'Phạm Quốc PM')]

  // Team thuộc đúng một PM (R1): Trần Minh → t1,t2 · Lê Thu → t3,t4 · Phạm Quốc → t5,t6.
  const TEAM_PM = [0, 0, 1, 1, 2, 2]
  const teams: Team[] = TEAM_NAMES.map((name, i) => ({
    id: `t${i + 1}`, name, leadId: '', memberIds: [],
    allowedSteps: i === 0 || i === 3 ? ['annotate', 'qc1', 'qc2'] : ['annotate', 'qc1'], canQa: i === 0 || i === 3,
    pmId: pms[TEAM_PM[i]].id,
  }))
  teams.forEach((t, i) => {
    const lead = addUser('lead', [t.id])
    t.leadId = lead.id
    t.memberIds.push(lead.id)
    const memberCount = 7 + (i % 3) // 1 lead + 2 QC + 7–9 annotator = 10–12 người
    for (let k = 0; k < 2; k++) t.memberIds.push(addUser('annotator', [t.id], true).id)
    for (let k = 0; k < memberCount; k++) t.memberIds.push(addUser('annotator', [t.id]).id)
  })

  return { dataTypes, users, admin, pms, teams }
}

export function createSeedState(): DashboardState {
  const rng = createRng(20261118)
  const pick = <T,>(a: readonly T[]): T => a[Math.floor(rng() * a.length)]
  const int = (lo: number, hi: number) => lo + Math.floor(rng() * (hi - lo + 1))
  const { dataTypes, users, pms, teams } = createBaseOrg(rng)

  // ---- Projects
  const projects: Project[] = [
    {
      id: 'p1', name: 'Dự án LiDAR Đô thị', dataTypeId: 'dt-lidar', pmIds: [pms[0].id, pms[1].id], ...projectExtras('p1'),
    },
    { id: 'p2', name: 'Dự án Camera Giao thông', dataTypeId: 'dt-bbox', pmIds: [pms[2].id], ...projectExtras('p2') },
  ]

  // ---- Datasets & Batches (khai báo trước; job sinh theo batch)
  const D = (id: string, name: string, nas: string, projectId: string, files: number, frames: number, rec: number, last: number | null): Dataset => ({
    id, name, nasPath: nas, dataTypeId: projects.find((p) => p.id === projectId)!.dataTypeId, projectId,
    fileCount: files, frameCount: frames, status: 'active',
    receivedAt: new Date(new Date(SEED_NOW).getTime() - rec * 86400000).toISOString(),
    lastDistributedAt: last === null ? null : new Date(new Date(SEED_NOW).getTime() - last * 86400000).toISOString(),
    ...datasetExtras(id),
  })
  const datasets: Dataset[] = [
    D('d1', 'LiDAR Quận 1', '/nas/lidar/q1_2026-10', 'p1', 1843, 36784, 40, 28),
    D('d2', 'LiDAR Quận 7', '/nas/lidar/q7_2026-10', 'p1', 1617, 32291, 34, 22),
    D('d3', 'LiDAR Thủ Đức', '/nas/lidar/thuduc_2026-11', 'p1', 1198, 23963, 4, null),
    D('d4', 'Camera Giao thông', '/nas/camera/traffic_2026-10', 'p2', 5196, 103918, 30, 21),
  ]
  type Profile = 'default' | 'brisk' | 'audit' | 'mixed' | 'ready' | 'delivered' | 'pending' | 'released'
  const LOCK_PAST = '2026-11-15T17:00:00.000Z'
  const LOCK_FUTURE = '2026-11-25T17:00:00.000Z'
  const B = (id: string, name: string, datasetId: string, cvat: number, status: Batch['status'], profile: Profile, lock: string | null = null) =>
    ({ batch: { id, name, datasetId, projectId: datasets.find((d) => d.id === datasetId)!.projectId, cvatTaskId: cvat, status, teamId: null, stepPic: {}, autoLockAt: lock, dueAt: null, stepBufferDays: { qc1: 2, qc2: 1 }, priority: batchPriority(id) } as Batch, profile })
  const batchDefs = [
    B('b01', 'Quận 1 – đợt 1', 'd1', 101, 'in_progress', 'brisk', LOCK_FUTURE),
    B('b02', 'Quận 1 – đợt 2', 'd1', 102, 'in_progress', 'mixed'),
    B('b03', 'Quận 7 – đợt 1', 'd2', 103, 'delivered', 'delivered'),
    B('b04', 'Quận 7 – đợt 2', 'd2', 104, 'ready', 'ready'),
    B('b05', 'Thủ Đức – chưa chia', 'd3', 105, 'pending', 'pending'),
    B('b06', 'Quận 7 – đợt 0 (đã release)', 'd2', 106, 'released', 'released'),
    B('b07', 'Ngã tư A – đợt 1', 'd4', 201, 'in_audit', 'audit'),
    B('b08', 'Ngã tư A – đợt 2', 'd4', 202, 'delivered', 'delivered'),
    B('b09', 'Cao tốc – đợt 1', 'd4', 203, 'in_progress', 'default', LOCK_PAST),
    B('b10', 'Cao tốc – đợt 2', 'd4', 204, 'in_progress', 'default'),
  ]
  const batches: Batch[] = batchDefs.map((b) => b.batch)

  // ---- Jobs
  const jobs: Job[] = []
  const events: JobEvent[] = []
  const kpiMap = new Map<string, number>()
  let jSeq = 0
  let eSeq = 0
  const baseTime = new Date(SEED_NOW).getTime()
  const ev = (e: Omit<JobEvent, 'id'>) => { eSeq++; events.push({ id: `ev${String(eSeq).padStart(5, '0')}`, ...e }) }
  const addKpi = (userId: string, date: string, n: number) => {
    const k = `${userId}|${date}`
    kpiMap.set(k, (kpiMap.get(k) ?? 0) + n)
  }
  const qcCandidates = (team: Team) => users.filter((u) => team.memberIds.includes(u.id) && (u.isQc || u.role === 'lead'))
  const annoOf = (team: Team) => users.filter((u) => team.memberIds.includes(u.id) && u.role === 'annotator' && !u.isQc)

  const stageWeights: [JobStage, number][] = [
    ['team_pool', 14], ['anno_in_progress', 20], ['qc1_pending', 10], ['qc1_in_progress', 8],
    ['qc2_pending', 12], ['qc2_in_progress', 6], ['ready_to_deliver', 12], ['delivered', 18],
  ]
  /** b01 chạy nhanh: phần lớn đã xong gần đây, còn vài job đang gán nhãn / chờ QC1. */
  const BRISK_STAGES: JobStage[] = [
    'ready_to_deliver', 'anno_in_progress', 'qc1_pending', 'ready_to_deliver', 'anno_in_progress',
    'delivered', 'ready_to_deliver', 'qc1_in_progress', 'ready_to_deliver', 'anno_in_progress',
  ]
  const totalW = stageWeights.reduce((s, [, w]) => s + w, 0)
  const pickStage = (profile: Profile): JobStage => {
    if (profile === 'ready') return 'ready_to_deliver'
    if (profile === 'delivered') return 'delivered'
    if (profile === 'mixed') {
      const r = rng()
      return r < 0.6 ? 'qc2_pending' : r < 0.75 ? 'qc2_in_progress' : r < 0.9 ? 'qc1_in_progress' : 'qc1_pending'
    }
    if (profile === 'audit') return rng() < 0.75 ? 'qc2_pending' : 'qc2_in_progress'
    let r = rng() * totalW
    if (profile === 'brisk') { // batch chạy nhanh: phần lớn đã xong gần đây, còn vài job ở mọi bước
      const x = r / totalW
      return x < 0.5 ? 'ready_to_deliver' : x < 0.62 ? 'delivered' : x < 0.7 ? 'qc2_pending' : x < 0.8 ? 'qc1_pending' : x < 0.86 ? 'qc1_in_progress' : x < 0.95 ? 'anno_in_progress' : 'team_pool'
    }
    for (const [s, w] of stageWeights) { if ((r -= w) < 0) return s }
    return 'delivered'
  }

  const newJob = (project: Project, batch: Batch, stage: JobStage, team: Team | null): Job => {
    jSeq++
    const dt = dataTypes.find((d) => d.id === project.dataTypeId)!
    const prelabel = dt.shapeType === 'cuboid' ? int(300, 1500) : int(800, 3500)
    const job: Job = {
      id: `j${String(jSeq).padStart(3, '0')}`, cvatJobId: 5000 + jSeq, batchId: batch.id, projectId: project.id,
      teamId: team?.id ?? null, annotatorId: null, qc1Id: null, qc2Id: null, stage,
      prelabelCuboids: prelabel, editedCuboids: 0, frames: int(20, 60), reworkCount: 0, firstSubmittedAt: null,
    }
    jobs.push(job)
    return job
  }

  const advance = (job: Job, team: Team, target: JobStage) => {
    const annos = annoOf(team)
    const qcs = qcCandidates(team)
    const pm = users.find((u) => u.id === team.pmId)! // R4: QC2 do PM của team giữ batch
    // Job đã xong rải trên ~5 tuần để biểu đồ rework theo tuần có dữ liệu; job đang dở thì gần đây
    const finished = target === 'ready_to_deliver' || target === 'delivered'
    const brisk = job.batchId === 'b01' // job xong gần đây (≤6 ngày) để dự báo tốc độ có số liệu
    let t = baseTime - (finished ? (brisk ? int(4, 6) : int(4, 34)) : int(3, 13)) * 86400000
    let lastAt = ''
    const advanceTime = () => { t += int(1, 8) * 3600000; lastAt = new Date(t).toISOString(); return lastAt }
    let cur: JobStage = 'unassigned_pool'
    const step = (type: JobEvent['type'], actor: string, to: JobStage, extra: Partial<JobEvent> = {}) => {
      ev({ jobId: job.id, at: advanceTime(), actorId: actor, type, fromStage: cur, toStage: to, ...extra })
      cur = to
    }
    step('distribute', pm.id, 'team_pool')
    if (target === 'team_pool') return
    job.annotatorId = pick(annos).id
    job.qc1Id = pick(qcs.filter((q) => q.id !== job.annotatorId)).id
    step('assign', team.leadId, 'anno_in_progress')
    // Rework giả lập (không áp cho job vừa nộp lần đầu)
    const willRework = target !== 'anno_in_progress' && rng() < 0.3
    const submit = (resubmit: boolean) => {
      step(resubmit ? 'resubmit' : 'submit', job.annotatorId!, 'qc1_pending')
      if (!resubmit) {
        job.editedCuboids = Math.round(job.prelabelCuboids * (0.2 + rng() * 0.5))
        job.firstSubmittedAt = lastAt
        addKpi(job.annotatorId!, lastAt.slice(0, 10), job.editedCuboids)
      }
    }
    if (target === 'anno_in_progress') {
      if (rng() < 0.35) { // job đang bị trả về
        submit(false)
        step('qc1_start', job.qc1Id, 'qc1_in_progress')
        job.reworkCount += 1
        step('qc1_return', job.qc1Id, 'anno_in_progress', {
          reason: pick(RETURN_REASONS), errorCategory: pick(dataTypes.find((d) => d.id === projects.find((p) => p.id === job.projectId)!.dataTypeId)!.errorCategories),
          reworkAgainst: [job.annotatorId],
        })
      }
      job.stage = cur
      return
    }
    submit(false)
    if (willRework) {
      const cats = dataTypes.find((d) => d.id === projects.find((p) => p.id === job.projectId)!.dataTypeId)!.errorCategories
      step('qc1_start', job.qc1Id, 'qc1_in_progress')
      job.reworkCount += 1
      step('qc1_return', job.qc1Id, 'anno_in_progress', { reason: pick(RETURN_REASONS), errorCategory: pick(cats), reworkAgainst: [job.annotatorId] })
      submit(true)
    }
    if (target === 'qc1_pending') { job.stage = cur; return }
    step('qc1_start', job.qc1Id, 'qc1_in_progress')
    if (target === 'qc1_in_progress') { job.stage = cur; return }
    step('qc1_pass', job.qc1Id, 'qc2_pending')
    // Một số job bị QC2 trả về
    if ((target === 'qc2_in_progress' || target === 'ready_to_deliver' || target === 'delivered') && rng() < 0.28) {
      const cats = dataTypes.find((d) => d.id === projects.find((p) => p.id === job.projectId)!.dataTypeId)!.errorCategories
      step('qc2_start', pm.id, 'qc2_in_progress')
      if (rng() < 0.5) {
        job.reworkCount += 1
        step('qc2_return_qc1', pm.id, 'qc1_in_progress', { reason: 'QC1 bỏ sót lỗi: ' + pick(RETURN_REASONS), errorCategory: pick(cats), reworkAgainst: [job.qc1Id] })
        step('qc1_pass', job.qc1Id, 'qc2_pending')
      } else {
        job.reworkCount += 1
        step('qc2_return_anno', pm.id, 'anno_in_progress', { reason: pick(RETURN_REASONS), errorCategory: pick(cats), reworkAgainst: [job.annotatorId, job.qc1Id] })
        submit(true)
        step('qc1_start', job.qc1Id, 'qc1_in_progress')
        step('qc1_pass', job.qc1Id, 'qc2_pending')
      }
    }
    if (target === 'qc2_pending') { job.stage = cur; return }
    step('qc2_start', pm.id, 'qc2_in_progress')
    job.qc2Id = pm.id
    if (target === 'qc2_in_progress') { job.stage = cur; return }
    step('qc2_pass', pm.id, 'ready_to_deliver')
    if (target === 'delivered') step('deliver', pm.id, 'delivered')
    job.stage = cur
  }

  const teamById = (id: string) => teams.find((t) => t.id === id)!
  for (const { batch, profile } of batchDefs) {
    if (profile === 'released') continue
    const project = projects.find((p) => p.id === batch.projectId)!
    const n = profile === 'pending' || profile === 'brisk' ? 10 : 8 + (Number(batch.id.slice(1)) % 3) // 8–10 job/batch
    const idx = batches.filter((b) => b.projectId === project.id && b.status !== 'pending' && b.status !== 'released').indexOf(batch)
    const projectTeams = teams.filter((t) => project.pmIds.includes(t.pmId)) // R1
    const team = profile === 'pending' ? null : projectTeams[idx % projectTeams.length]
    for (let i = 0; i < n; i++) {
      if (!team) { newJob(project, batch, 'unassigned_pool', null); continue }
      // brisk: mẫu cố định (batch chỉ 10 job, rng không bảo đảm đủ bước cho các ca demo hạn)
      const target = profile === 'brisk' ? BRISK_STAGES[i] : pickStage(profile)
      const job = newJob(project, batch, target, team)
      advance(job, team, target)
    }
    if (team) {
      batch.teamId = team.id
      batch.stepPic = {
        qc1: users.find((u) => team.memberIds.includes(u.id) && u.isQc)!.id,
        qc2: team.pmId,
      }
    }
  }
  // cvatDrift: vài job lệch
  const drifts = [
    'Dashboard: QC2 đạt — CVAT: vẫn ở trạng thái validation',
    'Dashboard: anno đang làm — CVAT: đã chuyển completed',
    'Người được giao trên CVAT khác với dashboard',
    'Dashboard: Sẵn sàng giao — CVAT: job quay lại in progress',
  ]
  const driftTargets = jobs.filter((j) => j.stage !== 'unassigned_pool' && j.stage !== 'team_pool')
  for (let i = 0; i < drifts.length; i++) driftTargets[(i * 17 + 3) % driftTargets.length].cvatDrift = drifts[i]

  // ---- Hạn giao (deadline): xác định, không dùng rng. Giờ tính từ SEED_NOW.
  const HOUR = 3600000
  const atH = (h: number) => new Date(baseTime + h * HOUR).toISOString()
  // Hạn giờ không tròn (8 ngày 6 giờ, 20 giờ 15 phút…) — sát thực tế hơn giờ chẵn.
  const DUE_HOURS: Record<string, number | null> = {
    b01: 8 * 24 + 6, b02: 20.25, b03: -(9 * 24 + 15), b04: 5 * 24 + 8, b05: 14 * 24 + 10, b06: null,
    b07: -46.5, b08: -(2 * 24 + 22), b09: 4 * 24 + 6, b10: null,
  }
  for (const b of batches) { const h = DUE_HOURS[b.id]; b.dueAt = h === undefined || h === null ? null : atH(h) }
  // Ghi đè hạn riêng của job (cả lùi và đẩy sớm). Mỗi ghi đè có JobEvent `due_override`.
  const overrideDue = (job: Job | undefined, step: WorkStep, hoursFromNow: number, actorId: string) => {
    if (!job) return
    const iso = atH(hoursFromNow)
    job.due = { ...(job.due ?? {}), [step]: iso }
    ev({ jobId: job.id, at: atH(-1), actorId, type: 'due_override', fromStage: job.stage, toStage: job.stage,
      reason: `Hạn ${step}: ${fmtLockTime(iso)}` })
  }
  const inBatch = (batchId: string, stage: JobStage, skip = 0) => jobs.filter((j) => j.batchId === batchId && j.stage === stage)[skip]
  const leadOf = (job: Job | undefined) => job?.teamId ? teams.find((t) => t.id === job.teamId)!.leadId : pms[0].id
  const ov = (job: Job | undefined, step: WorkStep, h: number) => overrideDue(job, step, h, leadOf(job))
  ov(inBatch('b01', 'anno_in_progress', 1), 'annotate', 6)     // sắp trễ
  ov(inBatch('b01', 'qc1_pending', 0), 'qc1', 24 * 12)         // lùi muộn hơn mặc định
  ov(inBatch('b02', 'qc1_in_progress', 0), 'qc1', 24 * 3)      // cứu: lùi hạn QC1
  ov(inBatch('b02', 'qc2_pending', 0), 'qc2', -2)              // trễ do đẩy sớm
  ov(inBatch('b02', 'qc2_pending', 1), 'qc2', 5)               // sắp trễ
  ov(inBatch('b07', 'qc2_pending', 0), 'qc2', 48)              // lùi hạn so với batch quá hạn
  ov(inBatch('b09', 'anno_in_progress', 0), 'annotate', -26)   // trễ hơn 1 ngày
  ov(inBatch('b10', 'anno_in_progress', 0), 'annotate', -24)   // batch không hạn nhưng job có hạn riêng
  ov(inBatch('b10', 'team_pool', 0), 'annotate', 10)
  ov(inBatch('b10', 'anno_in_progress', 1), 'annotate', -3)    // trễ do đẩy sớm
  // Annotator demo có job trễ (b09/b10 ở trên) + cvat_user_6 (u06, QC1 của t1) có job QC1 trễ.
  // Plan 09: batch chỉ 8–10 job nên bỏ ca "job anno bất kỳ" để b01 vẫn đa số đúng hạn.
  const u06 = users.find((u) => u.cvatUsername === 'cvat_user_6')!
  const u06Job = jobs.find((j) => j.teamId === 't1' && (j.stage === 'qc1_pending' || j.stage === 'qc1_in_progress') && !j.due)
  if (u06Job) { u06Job.qc1Id = u06.id; ov(u06Job, 'qc1', -2) }

  // ---- KPI 14 ngày: nền ngẫu nhiên + dữ liệu từ job
  const kpiDaily: KpiDaily[] = []
  const annotators = users.filter((u) => u.role === 'annotator')
  for (const u of annotators) {
    for (let d = 13; d >= 0; d--) {
      const date = isoDay(d)
      const dtTarget = u.teamIds.some((t) => t === 't5') ? 3000 : 1200
      const base = Math.round(dtTarget * (0.35 + rng() * 0.85))
      const fromJobs = kpiMap.get(`${u.id}|${date}`) ?? 0
      kpiDaily.push({ userId: u.id, date, editedCuboids: Math.max(base, fromJobs) })
    }
  }

  // ---- Audits (lịch sử) + batch events
  const batchEvents: BatchEvent[] = []
  const bev = (batchId: string, daysAgo: number, actorId: string, type: BatchEvent['type'], detail: string) =>
    batchEvents.push({
      id: `be${String(batchEvents.length + 1).padStart(4, '0')}`, batchId,
      at: new Date(baseTime - daysAgo * 86400000).toISOString(), actorId, type, detail,
    })
  for (const { batch } of batchDefs) {
    if (batch.status === 'pending') continue
    const team = teams.find((t) => t.id === batch.teamId)
    if (team) bev(batch.id, 25, team.pmId, 'distribute', `Chia cho ${team.name}`)
  }
  bev('b01', 3, pms[0].id, 'autolock_set', `Đặt khoá tự động lúc ${fmtLockTime(LOCK_FUTURE)}`)
  bev('b09', 12, pms[2].id, 'autolock_set', `Đặt khoá tự động lúc ${fmtLockTime(LOCK_PAST)}`)
  bev('b06', 9, pms[0].id, 'release', 'Release batch: xoá 22 job, trả dữ liệu về kho')

  for (const b of batches) {
    if (b.dueAt) bev(b.id, 14, b.projectId === 'p1' ? pms[0].id : pms[2].id, 'due_set', `Đặt hạn giao ${fmtLockTime(b.dueAt)}`)
  }

  const sample = (batchId: string, k: number) => jobs.filter((j) => j.batchId === batchId).slice(0, k).map((j) => j.id)
  const audit = (n: number, daysAgo: number, projectId: string, batchIds: string[], lvl: number, status: Audit['status'], ids: string[], returnedIdx: number[] = []): Audit => {
    const results: Audit['results'] = {}
    if (status !== 'open') ids.forEach((id, i) => { results[id] = returnedIdx.includes(i) ? 'returned' : 'passed' })
    const createdAt = new Date(baseTime - daysAgo * 86400000).toISOString()
    const owner = teamById(batches.find((b) => b.id === batchIds[0])!.teamId!).pmId // R4
    for (const b of batchIds) bev(b, daysAgo, owner, 'audit_create', `Tạo audit au${n} (mức ${AUDIT_LEVELS[lvl]}%)`)
    return {
      id: `au${n}`, createdAt, createdBy: owner, projectId, batchIds,
      levels: AUDIT_LEVELS, currentLevelIndex: lvl, percent: AUDIT_LEVELS[lvl], sampledJobIds: ids, results, status,
      closedAt: status === 'open' ? null : new Date(new Date(createdAt).getTime() + 86400000).toISOString(),
    }
  }
  const b07Qc2 = jobs.filter((j) => j.batchId === 'b07' && j.stage === 'qc2_pending').map((j) => j.id)
  const audits: Audit[] = [
    audit(1, 20, 'p1', ['b03'], 0, 'passed', sample('b03', 22)),
    audit(2, 12, 'p1', ['b04'], 1, 'passed', sample('b04', 7)),
    audit(3, 6, 'p1', ['b02'], 0, 'failed', sample('b02', 6), [2]),
    audit(4, 1, 'p2', ['b07'], 0, 'open', b07Qc2),
  ]
  batchEvents.push(
    { id: 'be-au3', batchId: 'b02', at: audits[2].closedAt!, actorId: audits[2].createdBy, type: 'audit_fail', detail: 'Audit au3 trượt: 1 job bị trả' },
  )
  batchEvents.forEach((e, i) => { e.id = `be${String(i + 1).padStart(4, '0')}` })

  return {
    schemaVersion: 2, users, teams, dataTypes, projects, jobs, events, kpiDaily, datasets, batches, batchEvents, audits, favorites: {},
    currentUserId: pms[0].id, now: SEED_NOW, datasetPreset: 'default',
  }
}

/**
 * Bộ dữ liệu mẫu kiểm thử luồng từ cấp cao đến thấp (Plan 10):
 * - 2 Dự án (p1 LiDAR, p2 Camera).
 * - Mỗi dự án 3 Dataset (tổng 6 Dataset: d1..d6).
 * - Mỗi dataset 5 Batch (tổng 30 Batch: b01..b30).
 * - Mỗi batch 8 Job (tổng 240 Job: j001..j240).
 * - Không rải dữ liệu mà toàn bộ để ở kho chờ Admin (batch 'pending', job 'unassigned_pool').
 * - Người dùng mặc định là Admin (u01) để tự tay chia thủ công và kiểm thử luồng.
 */
export function createWorkflowTestSeedState(): DashboardState {
  const rng = createRng(20261118)
  const { dataTypes, users, admin, pms } = createBaseOrg(rng)

  // 2 Dự án (p1: LiDAR, p2: Camera)
  const projects: Project[] = [
    {
      id: 'p1',
      name: 'Dự án LiDAR Xe Tự Hành (Test)',
      dataTypeId: 'dt-lidar',
      pmIds: [pms[0].id],
      code: 'PRJ-LIDAR-TEST',
      partner: PARTNERS[0],
      assignedAt: addIso(-10),
      dueAt: addIso(30),
      status: 'running',
    },
    {
      id: 'p2',
      name: 'Dự án Camera Giao Thông (Test)',
      dataTypeId: 'dt-bbox',
      pmIds: [pms[2].id],
      code: 'PRJ-CAM-TEST',
      partner: PARTNERS[1],
      assignedAt: addIso(-10),
      dueAt: addIso(30),
      status: 'running',
    },
  ]

  // 6 Datasets (mỗi dự án 3 dataset)
  const datasetDefs = [
    { id: 'd1', name: 'LiDAR Ngoại Thành – Tuyến A', projectId: 'p1', nas: '/nas/lidar/test_a', files: 1500, frames: 30000, scenes: 60 },
    { id: 'd2', name: 'LiDAR Đô Thị – Tuyến B', projectId: 'p1', nas: '/nas/lidar/test_b', files: 1800, frames: 36000, scenes: 75 },
    { id: 'd3', name: 'LiDAR Hầm Vượt – Tuyến C', projectId: 'p1', nas: '/nas/lidar/test_c', files: 1200, frames: 24000, scenes: 50 },
    { id: 'd4', name: 'Camera Giám Sát Tuyến 01', projectId: 'p2', nas: '/nas/camera/test_01', files: 4000, frames: 80000, scenes: 100 },
    { id: 'd5', name: 'Camera Giám Sát Tuyến 02', projectId: 'p2', nas: '/nas/camera/test_02', files: 4200, frames: 84000, scenes: 105 },
    { id: 'd6', name: 'Camera Giao Lộ Trọng Điểm', projectId: 'p2', nas: '/nas/camera/test_03', files: 3600, frames: 72000, scenes: 90 },
  ]

  const datasets: Dataset[] = datasetDefs.map((def, i) => ({
    id: def.id,
    name: def.name,
    nasPath: def.nas,
    dataTypeId: projects.find((p) => p.id === def.projectId)!.dataTypeId,
    projectId: def.projectId,
    fileCount: def.files,
    frameCount: def.frames,
    status: 'active',
    receivedAt: addIso(-(10 - i)),
    lastDistributedAt: null,
    dueAt: null,
    preprocessedPct: 100,
    onCvatPct: 100,
    sceneCount: def.scenes,
    partnerNote: 'Dữ liệu đã sẵn sàng trên CVAT, đang chờ Admin hoặc PM giao cho team.',
  }))

  const batches: Batch[] = []
  const jobs: Job[] = []

  let bSeq = 0
  let jSeq = 0

  // Mỗi dataset gồm 5 batch (tổng 30 batch)
  for (const ds of datasets) {
    for (let b = 1; b <= 5; b++) {
      bSeq++
      const batchId = `b${String(bSeq).padStart(2, '0')}`
      const batch: Batch = {
        id: batchId,
        name: `${ds.name} – Đợt ${b}`,
        datasetId: ds.id,
        projectId: ds.projectId,
        cvatTaskId: 300 + bSeq,
        status: 'pending',
        teamId: null,
        stepPic: {},
        autoLockAt: null,
        dueAt: null,
        stepBufferDays: { qc1: 2, qc2: 1 },
        priority: 3,
      }
      batches.push(batch)

      // Mỗi batch gồm 8 job (tổng 240 job)
      const isLidar = ds.dataTypeId === 'dt-lidar'
      for (let j = 1; j <= 8; j++) {
        jSeq++
        const jobId = `j${String(jSeq).padStart(3, '0')}`
        jobs.push({
          id: jobId,
          cvatJobId: 5000 + jSeq,
          batchId: batch.id,
          projectId: batch.projectId,
          stage: 'unassigned_pool',
          teamId: null,
          annotatorId: null,
          qc1Id: null,
          qc2Id: null,
          reworkCount: 0,
          prelabelCuboids: isLidar ? 800 : 2000,
          editedCuboids: 0,
          frames: 100,
          firstSubmittedAt: null,
        })
      }
    }
  }

  // Re-generate teams to ensure fresh state
  const { teams } = createBaseOrg(rng)

  return {
    schemaVersion: 2,
    users,
    teams,
    dataTypes,
    projects,
    jobs,
    events: [],
    kpiDaily: [],
    datasets,
    batches,
    batchEvents: [],
    audits: [],
    favorites: {},
    currentUserId: admin.id,
    now: SEED_NOW,
    datasetPreset: 'workflow_test',
  }
}

/** Hiển thị thời điểm khoá trong mô tả sự kiện: DD/MM/YYYY HH:mm (giờ máy). */
export function fmtLockTime(iso: string): string {
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`
}
