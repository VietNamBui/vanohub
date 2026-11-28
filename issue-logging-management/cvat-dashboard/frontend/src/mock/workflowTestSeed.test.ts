import { describe, expect, it } from 'vitest'
import { applyAction } from './logic'
import { createWorkflowTestSeedState } from './seed'

describe('createWorkflowTestSeedState (Plan 10)', () => {
  it('tạo đúng cấu trúc phân cấp: 2 Dự án, 6 Dataset, 30 Batch, 240 Job', () => {
    const s = createWorkflowTestSeedState()

    // 2 Dự án
    expect(s.projects.length).toBe(2)
    expect(s.projects.map((p) => p.id)).toEqual(['p1', 'p2'])

    // 6 Dataset (3 dataset / dự án)
    expect(s.datasets.length).toBe(6)
    expect(s.datasets.filter((d) => d.projectId === 'p1').map((d) => d.id)).toEqual(['d1', 'd2', 'd3'])
    expect(s.datasets.filter((d) => d.projectId === 'p2').map((d) => d.id)).toEqual(['d4', 'd5', 'd6'])

    // 30 Batch (5 batch / dataset)
    expect(s.batches.length).toBe(30)
    for (const d of s.datasets) {
      const batches = s.batches.filter((b) => b.datasetId === d.id)
      expect(batches.length).toBe(5)
    }

    // 240 Job (8 job / batch)
    expect(s.jobs.length).toBe(240)
    for (const b of s.batches) {
      const jobs = s.jobs.filter((j) => j.batchId === b.id)
      expect(jobs.length).toBe(8)
    }

    // Toàn bộ batch ở trạng thái pending, chưa chia team
    expect(s.batches.every((b) => b.status === 'pending')).toBe(true)
    expect(s.batches.every((b) => b.teamId === null)).toBe(true)

    // Toàn bộ job ở unassigned_pool, chưa giao ai
    expect(s.jobs.every((j) => j.stage === 'unassigned_pool')).toBe(true)
    expect(s.jobs.every((j) => j.teamId === null)).toBe(true)
    expect(s.jobs.every((j) => j.annotatorId === null)).toBe(true)
    expect(s.jobs.every((j) => j.qc1Id === null)).toBe(true)
    expect(s.jobs.every((j) => j.qc2Id === null)).toBe(true)

    // Mặc định ban đầu người dùng là Admin
    expect(s.currentUserId).toBe('u01')
    expect(s.datasetPreset).toBe('workflow_test')

    // Chưa có dữ liệu phát sinh
    expect(s.events.length).toBe(0)
    expect(s.kpiDaily.length).toBe(0)
    expect(s.batchEvents.length).toBe(0)
    expect(s.audits.length).toBe(0)
  })

  it('vận hành luồng thủ công từ Admin -> Team -> Lead -> Annotator -> QC1 -> QC2 -> Delivery', () => {
    let s = createWorkflowTestSeedState()

    // 1. Admin giao batch b01 cho Team Alpha (t1)
    s = applyAction(s, { kind: 'assignBatchTeam', batchId: 'b01', teamId: 't1' })
    const b01 = s.batches.find((b) => b.id === 'b01')!
    expect(b01.status).toBe('in_progress')
    expect(b01.teamId).toBe('t1')

    // Toàn bộ 8 job của b01 đã chuyển sang team_pool của t1
    const b01Jobs = s.jobs.filter((j) => j.batchId === 'b01')
    expect(b01Jobs.length).toBe(8)
    expect(b01Jobs.every((j) => j.stage === 'team_pool')).toBe(true)
    expect(b01Jobs.every((j) => j.teamId === 't1')).toBe(true)

    // 2. Chuyển sang Lead của Team Alpha (u05) để giao job đầu tiên j001
    const t1 = s.teams.find((t) => t.id === 't1')!
    const leadId = t1.leadId
    const annotators = s.users.filter((u) => t1.memberIds.includes(u.id) && u.role === 'annotator' && !u.isQc)
    const qcs = s.users.filter((u) => t1.memberIds.includes(u.id) && u.isQc)
    const anno = annotators[0]
    const qc = qcs[0]

    s = { ...s, currentUserId: leadId }
    s = applyAction(s, { kind: 'assignJob', jobId: 'j001', annotatorId: anno.id, qc1Id: qc.id })
    let j001 = s.jobs.find((j) => j.id === 'j001')!
    expect(j001.stage).toBe('anno_in_progress')
    expect(j001.annotatorId).toBe(anno.id)
    expect(j001.qc1Id).toBe(qc.id)

    // 3. Annotator nộp job
    s = { ...s, currentUserId: anno.id }
    s = applyAction(s, { kind: 'submitJob', jobId: 'j001', editedCuboids: 40 })
    j001 = s.jobs.find((j) => j.id === 'j001')!
    expect(j001.stage).toBe('qc1_pending')

    // 4. QC1 bắt đầu kiểm tra và duyệt đạt
    s = { ...s, currentUserId: qc.id }
    s = applyAction(s, { kind: 'startQc1', jobId: 'j001' })
    j001 = s.jobs.find((j) => j.id === 'j001')!
    expect(j001.stage).toBe('qc1_in_progress')

    s = applyAction(s, { kind: 'qc1Pass', jobId: 'j001' })
    j001 = s.jobs.find((j) => j.id === 'j001')!
    expect(j001.stage).toBe('qc2_pending')

    // 5. PM tạo Audit và duyệt QC2
    const pmId = t1.pmId
    s = { ...s, currentUserId: pmId }
    s = applyAction(s, { kind: 'createAudit', batchIds: ['b01'], percent: 100 })
    const audit = s.audits[0]
    expect(audit).toBeDefined()
    expect(audit.sampledJobIds).toContain('j001')

    s = applyAction(s, { kind: 'auditJobPass', auditId: audit.id, jobId: 'j001' })
    s = applyAction(s, { kind: 'closeAudit', auditId: audit.id })

    j001 = s.jobs.find((j) => j.id === 'j001')!
    expect(j001.stage).toBe('ready_to_deliver')

    // 6. Giao hàng (Delivery)
    s = applyAction(s, { kind: 'markDelivered', jobIds: ['j001'] })
    j001 = s.jobs.find((j) => j.id === 'j001')!
    expect(j001.stage).toBe('delivered')
  })
})
