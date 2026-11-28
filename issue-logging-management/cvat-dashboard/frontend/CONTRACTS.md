# CONTRACTS — Wave 0 + Foundation PDF-features (đọc file này + spec là đủ)

Stack: Vite + React 18 + TS strict + AntD 5 (`vi_VN`) + react-router v6 + dayjs + Vitest. Chạy: `npm run dev|build|lint|test`.
Mỗi agent wave 1 CHỈ sửa thư mục page của mình; cần đổi `src/mock`, `src/components`, `routes.tsx`, `layouts` → báo lại, KHÔNG tự sửa.

## 1. Types (`src/mock/types.ts`)
`Role` = admin|pm|lead|annotator · `User {id,name,cvatUsername,role,teamIds,isQc}` · `Team {id,name,leadId,memberIds}` (memberIds gồm cả lead) ·
`DataType {id,name,shapeType:'cuboid'|'rectangle',kpiPerDay,thresholdCm,thresholdDeg,errorCategories}` · `Project {id,name,dataTypeId,pmIds,teamIds}` (KHÔNG còn `cvatTasks` — thay bằng Batch) ·
`User` thêm `employeeId:number` (ID cá nhân, vd 2828) · `Team` thêm `allowedSteps:WorkStep[]`, `canQa:boolean` (`leadId` có thể '' với team mới) · `Job {id,cvatJobId,batchId,projectId,teamId|null,annotatorId|null,qc1Id|null,qc2Id|null,stage,prelabelCuboids,editedCuboids,frames,reworkCount,firstSubmittedAt|null,cvatDrift?}` ·
`JobStage` = unassigned_pool|team_pool|anno_in_progress|qc1_pending|qc1_in_progress|qc2_pending|qc2_in_progress|ready_to_deliver|delivered ·
`JobEvent {id,jobId,at(ISO),actorId,type,fromStage|null,toStage,reason?,errorCategory?,reworkAgainst?:userId[]}` (type: distribute|assign|reassign|submit|resubmit|qc1_start|qc1_pass|qc1_return|qc2_start|qc2_pass|qc2_return_qc1|qc2_return_anno|deliver) ·
`KpiDaily {userId,date:'YYYY-MM-DD',editedCuboids}` · `DashboardState {users,teams,dataTypes,projects,jobs,events,kpiDaily,currentUserId,now}` · `DistributionPreviewRow {teamId,jobIds,jobCount,totalCuboids}`.

Seed: `createSeedState()` (deterministic). `state.now` = mốc "bây giờ" cố định (2026-11-18T09:00Z), mỗi action tiến 1 phút; "hôm nay" = `state.now.slice(0,10)`. Dữ liệu: 2 project (p1 LiDAR 3D cuboid 1200/ngày, 4 team t1–t4, task `p1-task3` CHƯA chia với 30 job; p2 2D Bounding Box 3000/ngày, team t4,t5), 5 team, 42 user (1 admin, 3 PM, mỗi team 1 lead + 2 QC (isQc) + 4–5 annotator), ~200 job đủ 9 stage, KPI 14 ngày, 4 job có `cvatDrift`. User mặc định: PM đầu tiên.
Bộ dữ liệu kiểm thử luồng (Plan 10): `createWorkflowTestSeedState()` — 2 dự án, 6 dataset, 30 batch (`pending`), 240 job (`unassigned_pool`), tập trung ở kho Admin; chọn 1 trong 2 qua `setDatasetPreset('default' | 'workflow_test')`.

## 2. Store (`src/mock/store.tsx`)
`<StoreProvider>` đã bọc app. `const s = useStore()` → `DashboardState` + `currentUser` + actions. Action chạy ĐỒNG BỘ, mỗi action thêm `JobEvent` (actor = currentUser), THROW `Error` (tiếng Việt) khi sai bước/thiếu lý do → bọc try/catch + `message.error(e.message)`.

| Action | Luật |
|---|---|
| `setCurrentUser(userId)` | đổi vai |
| `assignJob(jobId, annotatorId, qc1Id)` | team_pool → anno_in_progress |
| `submitJob(jobId, editedCuboids?)` | anno_in_progress → qc1_pending. LẦN ĐẦU: set editedCuboids (mặc định 40% prelabel) + firstSubmittedAt + cộng KpiDaily hôm nay cho annotator. Nộp lại sau rework: event `resubmit`, KHÔNG cộng KPI |
| `startQc1(jobId)` | qc1_pending → qc1_in_progress |
| `qc1Pass(jobId)` | qc1_pending\|qc1_in_progress → qc2_pending |
| `qc1Return(jobId, reason, cat)` | → anno_in_progress, reworkCount+1, reworkAgainst=[annotator] |
| `startQc2(jobId)` | qc2_pending → qc2_in_progress (set qc2Id) |
| `qc2Pass(jobId)` | qc2_pending\|qc2_in_progress → ready_to_deliver |
| `qc2ReturnToQc1(jobId, reason, cat)` | → qc1_in_progress, +1, against=[qc1] |
| `qc2ReturnToAnno(jobId, reason, cat)` | → anno_in_progress, +1, against=[annotator, qc1]; sau đó nộp lại phải qua QC1 (luồng thường) |
| `markDelivered(jobIds[])` | ready_to_deliver → delivered (tất cả phải hợp lệ) |
| `reassignJob(jobId, {annotatorId?, qc1Id?})` | giữ stage, event `reassign`, lịch sử giữ |
| `previewDistribution(taskId, teamIds)` | THUẦN → `DistributionPreviewRow[]` (xáo seed, greedy cuboid lớn nhất vào team ít cuboid nhất, số job lệch ≤1) |
| `distributeJobs(taskId, teamIds)` | áp preview: unassigned_pool → team_pool + `teamId`, task.distributed=true, thêm team vào project |
| `updateDataType(dt)` | cập nhật cấu hình KPI |

Lý do + loại lỗi BẮT BUỘC cho mọi return (trim rỗng ⇒ throw). Logic thuần: `src/mock/logic.ts` (`applyAction`, `previewDistribution`).

## 3. Selectors (`src/mock/selectors.ts`) — hàm thuần, truyền `s` từ `useStore()`; % là 0–100
Hằng: `STAGES`, `STAGE_LABEL`, `ROLE_LABEL`, `HOME_ROUTE`. Lookup: `userById/teamById/projectById/jobById(s,id)`, `dataTypeOfProject(s,projectId)`, `eventsOfJob(s,jobId)` (cũ→mới).
Phạm vi: `visibleProjects(s,user)`, `visibleTeams(s,user)`, `visibleJobs(s,user)` (admin tất cả; pm theo pmIds; lead theo team; annotator job của mình), `qcCandidatesOfTeam(s,teamId)` (lead+isQc), `annotatorsOfTeam(s,teamId)`.
Số liệu: `jobsByStage(s, projectId?)` → Record<JobStage,Job[]> · `projectStats(s,pid)` {totalJobs,assignedJobs,completionPct,editedCuboids,reworkRate} · `teamStats(s,teamId,pid?)` (+memberCount,reworkCount,byStage) · `userStats(s,uid)` {kpiToday,kpiTarget,kpiWeek[7]{date,editedCuboids,target},assignedJobs,submittedJobs,completionPct,reworkCount,reworkRate} · `kpiTargetOfUser` · `reworkByTeam(s,pid)` [{teamId,teamName,reworkCount,submittedJobs,reworkRate}] · `topErrorCategories(s,pid,limit=5)` · `qcStats(s,uid)` {qc1Passed,qc2Returned,missRate} · `driftedJobs(s)`.
Định nghĩa: completionPct = job ready_to_deliver|delivered / job đã có annotator; reworkRate = số event rework nhắm vào (user|team|project) / số job đã nộp lần đầu.

## 4. Components (`src/components`, import từ `'../../components'`)
- `StageTag {stage}` · `STAGE_COLOR`
- `KpiCard {title,value,suffix?,target?,trend?}` — có `target` ⇒ thanh tiến độ; `trend` % (+/−)
- `StageFunnel {counts: Partial<Record<JobStage,number>>, stages?, onStageClick?}` — thanh ngang; mặc định từ Kho team → Đã giao
- `JobTable {jobs, columns?: JobColumnKey[], renderActions?: (job)=>ReactNode, actionsTitle?, pageSize?, loading?}` — cột: job(link /jobs/:id) task team annotator qc1 stage prelabel edited frames rework drift
- `ReworkDialog {open,onCancel,onSubmit({reason,errorCategory,target?}),errorCategories,showReturnTarget?,title?}` — `target`: 'qc1'|'annotator' (chỉ khi showReturnTarget, dùng cho QC2). Lấy `errorCategories` từ `dataTypeOfProject(s, job.projectId)`
- `JobTimeline {events, reverse?}`

## 5. Routes (`src/routes.tsx`, `ROUTE_PATHS`) — page = default export, cùng tên file
/pm ProjectOverviewPage · /pm/teams/:teamId TeamDetailPage · /pm/users/:userId AnnotatorDetailPage · /pm/qc2 Qc2QueuePage · /pm/distribute DistributePage · /pm/config (pages/pm/config) DataTypeConfigPage · /pm/drift (pages/pm/config) DriftListPage · /lead, /lead/qc1 ⇒ redirect `/queue` (W1-A, §15) · /lead/members TeamMembersPage · /me MyKpiPage ("KPI của tôi") · /me/kpi MyKpiPage · /jobs/:jobId JobDetailPage · /admin UsersTeamsPage · /login LoginPage (ngoài layout) · `/` → home theo vai (`HOME_ROUTE`).
Giao diện CHỈ chế độ sáng (như CVAT). `useThemeMode()` trong `src/theme.tsx` chỉ là shim trả `{mode:'light'}` cho page cũ — page mới KHÔNG dùng; biểu đồ dùng widget thiết kế (mục 6), không dùng `@ant-design/charts`.

## 6. Design system (`src/design`, import `from '../../design'`)
Port từ trang Dashboard CVAT (`cvat-ui/.../dashboard-page`), class prefix `cvd-`. Token: `tokens.scss` (`$dash-*`, `stripes` mixin). Style: `dashboard.scss` (import sẵn trong `main.tsx`/widgets). Canvas `#efefef`, thẻ `#f8f8f8` bo 24px, chỉ giao diện sáng. **CẤM dùng AntD `Card`/`Statistic`/`Progress`/`Tag`/`Timeline` trên page — dùng widget bên dưới.** AntD vẫn dùng cho form/Select/Modal/Table (qua `DashTable`).

| Widget | Props chính | Dùng khi |
|---|---|---|
| `fmt(n)`, `pct(rate01)` | vi-VN / "12%" | mọi số hiển thị |
| `PageTitle<T>` | `title`, `tabs?{options,value,onChange}`, `controls?` | đầu mọi page (h1 52px + tab pill + điều khiển phải) |
| `Segmented<T>` | `options,value,onChange` | tab pill đứng riêng |
| `Pill` | `children, disabled?, onClick?` | điều khiển bo tròn (bọc Select/Button; `disabled` = "Xuất CSV" sắp có) |
| `Card` | `title?, extra?, className?, onMore?, children` | khung mọi khối; có `title` ⇒ header h3 (+ `extra`); nút ⋯ chỉ vẽ khi có `onMore` |
| `StatCard` | `label, value, suffix?, foot?, badge?, progress?{value,max,tone}` | số headline (hàng `cvd-row-stats`) |
| `Badge` / `Delta` | `tone: up\|down\|plain` / `current, previous` | ▲ xanh / ▼ hồng so kỳ trước |
| `StripedBar` | `value,max,tone:blue\|green\|pink,thin?` | tiến độ, bảng xếp hạng, funnel |
| `DailyBars` | `data:{date,value,secondary?}[], target, today, unit?, secondaryUnit?, targetLabel?` | **KPI theo ngày** (đường KPI xanh đứt, legend Đạt KPI/Chưa đạt/Hôm nay, tooltip) |
| `StepLine` | `points:{label,value 0–1}[], format?` | **xu hướng rework** |
| `DotMatrix` | `columns:number[], tone:green\|blue` | phân bố nhỏ theo cột |
| `InsightCard` | `title?, slides:{title,text?,value?,chip?}[], intervalMs?` | **thông báo / dự báo** (gradient cam→xanh, tự xoay) |
| `Tag` | `tone: blue\|pink\|gray\|green\|orange\|purple, solid?` | nhãn trạng thái |
| `Rank` / `Who` | `n` / `name, sub?` | **bảng xếp hạng** = `DashTable`+`Rank`+`Who`+`StripedBar` |
| `DashTable<T>` | như AntD `TableProps`; mặc định không phân trang, cuộn ngang | mọi bảng; dòng "tôi": `rowClassName` trả `'cvd-me'`; có `onRow` ⇒ con trỏ tay |
| `Footnote` | `children` | dòng ghi chú cuối page |

Component dùng chung (`src/components`) đã mang giao diện này, props giữ nguyên: `StageTag` (gray/blue/orange/purple/green, Đã giao = green đặc), `KpiCard` (= StatCard), `StageFunnel` (thanh sọc), `JobTable` (= DashTable), `JobTimeline`, `ReworkDialog` (modal `cvd-modal`).

**Khung page:** `<PageTitle title=… tabs? controls? />` rồi các hàng lưới (bọc sẵn trong `.cvd-page > .cvd-inner` bởi `AppLayout`, page KHÔNG tự thêm canvas/padding):
- `<div className="cvd-grid cvd-row-main">` — 2.25fr / 1fr (biểu đồ chính + InsightCard hoặc `cvd-stack` các thẻ nhỏ)
- `<div className="cvd-grid cvd-row-secondary">` — 1fr 1.25fr 1fr
- `<div className="cvd-grid cvd-row-stats">` — 4 cột `StatCard`
- `<div className="cvd-row-full">` — thẻ bảng full-width; `<div className="cvd-stack">` xếp dọc nhiều thẻ
Responsive: ≤1200px main/secondary về 1 cột, stats 2 cột; ≤640px stats 1 cột. Header `AppLayout`: nav ẩn thành menu ≤1100px.
Class phụ: `cvd-big`(72px) `cvd-mid`(52px) `cvd-muted` `cvd-danger` `cvd-separator` `cvd-progress-row` `cvd-cell-progress` `cvd-empty`.


---
# Bổ sung (foundation wave cho spec `docs/superpowers/specs/2026-11-18-pdf-features-addendum.md`)

## 7. Types mới (`src/mock/types.ts`)
- `WorkStep` = 'annotate'|'qc1'|'qc2'.
- `Dataset {id,name,nasPath,dataTypeId,projectId,fileCount,frameCount,status:'active'|'archived',receivedAt,lastDistributedAt|null}`.
- `Batch {id,name,datasetId,projectId,cvatTaskId:number,status,stepPic,autoLockAt|null}`; `BatchStatus` = pending|in_progress|in_audit|ready|delivered|released; `StepPic {annotate?:teamId[], qc1?:userId, qc2?:userId}`. **Không lưu `jobIds`/`batchIds`** (tránh lệch): dùng `jobsOfBatch(s,id)`, `batchesOfDataset(s,id)`.
- `BatchEvent {id,batchId,at,actorId,type,detail}` (type: distribute|reassign|release|autolock_set|autolock_reset|audit_create|audit_job_pass|audit_job_return|audit_pass|audit_fail). `Audit {id,createdAt,createdBy,projectId,batchIds,levels:[100,30,10],currentLevelIndex,sampledJobIds,results:Record<jobId,'passed'|'returned'>,status:'open'|'passed'|'failed',closedAt|null}`.
- `DashboardState` thêm `datasets, batches, batchEvents, audits, favorites: Record<userId,string[]>`.
- Seed: 4 dataset (d1–d4), 10 batch b01–b10: b01 lock tương lai; b02 'mixed' (nhiều qc2_pending, có audit trượt lịch sử); b03 delivered; b04 ready; **b05 pending (30 job unassigned_pool, dùng cho Chia job)**; b06 released (0 job); b07 in_audit (audit mở au4); b08 delivered; **b09 lock quá hạn**; b10 đang làm. Audit lịch sử p1: au1 đạt 100% → au2 đạt 30% → au3 trượt (⇒ mức kế tiếp 100%). Mỗi batch gán 1 team (stepPic.annotate=[teamId]), qc1 = một QC của team, qc2 = PM đầu của dự án. Seed vẫn xác định.

## 8. Actions mới (store; đồng bộ, throw Vietnamese)
`distributeJobs(batchId, teamIds)` / `previewDistribution(batchId, teamIds)` (batch phải 'pending'; sau chia → 'in_progress', stepPic.annotate=teamIds, BatchEvent, dataset.lastDistributedAt) ·
Teams: `createTeam({name,allowedSteps,canQa})` (tên rỗng/trùng, 0 bước ⇒ throw) · `updateTeam(id,{name?,allowedSteps?,canQa?})` · `deleteTeam(id)` (còn job đang xử lý — mọi stage trừ unassigned/delivered — ⇒ throw "còn N job đang xử lý") · `addTeamMember/removeTeamMember(teamId,userId)` (đồng bộ `user.teamIds`; không xoá được lead) · `updateUser(id,patch)`.
Batches: `reassignBatch(batchId, step, picId)` (annotate: picId=teamId, thay `stepPic.annotate=[picId]` + job còn ở team_pool đổi team; qc1/qc2: picId=userId, đẩy xuống job chưa qua bước; chỉ khi batch không pending/released; +BatchEvent) · `releaseBatch(id)` (**xoá job + JobEvent của batch**, status released; chặn khi in_audit/delivered/đã release) · `setAutoLock(id, iso|null)` (BatchEvent autolock_set khi đặt mới, autolock_reset khi sửa/gỡ).
Audits: `createAudit(batchIds)` · `auditJobPass(auditId,jobId)` · `auditJobReturn(auditId,jobId,'qc1'|'anno',reason,cat)` (đi qua qc2ReturnToQc1/ToAnno ⇒ rework, qc2Id, reason bắt buộc) · `closeAudit(auditId)`. `toggleFavorite(batchOrProjectId)`. Action per-job `startQc2/qc2Pass/qc2Return*` vẫn dùng được (tương thích).

## 9. Luật
- **Khoá (locked):** `isBatchLocked(state,batch)` = `autoLockAt < state.now`; selector `isJobLocked(s,jobId)`. Job khoá ⇒ `submitJob/startQc1/qc1Pass/qc1Return/startQc2/qc2Pass/qc2Return*/auditJobPass/auditJobReturn` THROW `'Batch đã bị khoá'` (assign/reassign/audit tạo/đóng không bị chặn). UI: nút làm việc disabled + `<Tag tone="orange">Đã khoá</Tag>`; PM gỡ bằng `setAutoLock(id,null)`.
- **Audit:** chỉ batch `in_progress` có ≥1 job `qc2_pending` (`auditableBatches`), cùng dự án. Mẫu = `ceil(level% × job qc2_pending)` xáo seed (xác định). Mức = `nextAuditLevel(s,projectId)`: chưa có audit đóng/lần trước trượt → 100; lần trước đạt → 30 → 10 (giữ 10). Tạo → batch `in_audit`. `closeAudit` yêu cầu mọi job mẫu đã chấm. Có job 'returned' ⇒ audit `failed`, batch về `in_progress`; ngược lại audit `passed`, mọi job `qc2_pending|qc2_in_progress` của các batch → `ready_to_deliver`, batch → `ready` nếu mọi job của nó đã ready/delivered (nếu còn job ở bước khác thì về `in_progress` — lệch nhẹ so với spec để không gắn nhãn 'ready' sai). `markDelivered` tự chuyển batch sang `delivered` khi mọi job đã giao.
- ~~Hiển thị QC trong Hàng đợi (hàng QC1/QC2)~~ — bị thay thế bởi §14 (Hàng đợi bấm sâu). `canQc/canAudit` vẫn là selector dùng chỗ khác.
- Home route mọi vai = `/queue` (`HOME_ROUTE`).

## 10. Selectors mới (`selectors.ts`)
Lookup: `datasetById, batchById, auditById, jobsOfBatch, batchesOfDataset, batchOfJob(s,job)`; phạm vi: `visibleBatches(s,user), visibleDatasets(s,user)`; hằng: `BATCH_STATUS_LABEL, STEP_LABEL`.
- `isJobLocked(s,jobId)`, `isBatchLockedById(s,batchId)`.
- `datasetStats(s,id)` → `{batchTotal,batchPending,batchActive(in_progress|in_audit),batchDone(ready|delivered),jobTotal}`.
- `batchStats(s,id)` → `{totalJobs,doneJobs,progressPct,byStage,picNames:{annotate:string[],qc1,qc2},locked}`; `batchHistory(s,id)` (mới→cũ).
- `nextAuditLevel(s,projectId)` → `{index,percent}`; `auditableBatches(s,user)`; `isFavorite(s,userId,targetId)`.
- `queueRowsForUser(s,userId)` (KHÔNG còn page nào dùng sau §14, giữ lại vì có test) → `QueueRow[] {batch,project,dataset,steps:{step,pending,processing,rework}[],locked,favorite}`. annotate: pending=team_pool, processing=anno_in_progress (annotator: của mình), rework=job đang bị trả (ưu tiên); qc1: qc1_pending/qc1_in_progress; qc2: qc2_pending/qc2_in_progress (toàn batch). Scope job theo team của user (pm/admin: tất cả).
- `statsByStage(s,{projectId?,batchId?,from,to,stage:'annotate'|'qc1'|'qc2'})` → `StageStatRow[] {user,jobs,cuboids,cuboidPerHour,fpy(0–100),reworkJobs,repairTime(giờ),avgRepairTime(giờ)}`. `from/to` là 'YYYY-MM-DD' (to tính hết ngày) hoặc ISO. Job của người = job họ nộp (annotate) / duyệt-trả (qc1, qc2) trong khoảng; giờ làm = Σ khoảng cách giữa event của họ ≤3h + 0,5h mỗi phiên (`workingHours`); fpy(annotate|qc1)=1−job bị trả chống lại họ/job, fpy(qc2)=duyệt/(duyệt+trả); thời gian sửa = từ lúc bị trả tới lần nộp lại (annotate) / duyệt QC1 lại (qc1).
- `keyMetrics(s,{projectId?,batchId?,from,to})` → `{activeWorkers, annotate:{jobs,cuboids}, qc1:{jobs,cuboids}, ready:{jobs,cuboids}, reworkRate, errorRate}` (%; reworkRate = lần trả/lần nộp; errorRate = lần trả/lần kiểm).

## 11. Routes mới
/queue, /queue/:projectId, /queue/:projectId/:datasetId, /queue/:projectId/:datasetId/:batchId QueuePage (Hàng đợi bấm sâu, xem §14) · /profile ProfilePage · /datasets, /batches ⇒ redirect `/queue` · /batches/:batchId ⇒ `BatchRedirect` (cấp Job của Hàng đợi, §15) · /audits AuditsPage · /audits/:auditId AuditDetailPage · /stats DataStatisticPage · /admin/teams TeamsMembersPage (`/admin` giữ UsersTeamsPage = "Người dùng"). `/pm/qc2` redirect → `/audits` (khỏi nav; Qc2QueuePage không còn route). Nav theo vai: xem `MENU` trong `layouts/AppLayout.tsx` (admin có thêm "Hàng đợi" đầu tiên vì /queue là home).
Menu người dùng (góc phải): avatar + tên + "ID: n"; Đổi mật khẩu (modal giả), Năng suất của tôi (annotator/lead → /me/kpi, pm/admin → /stats), Hồ sơ (/profile), Đăng xuất (/login), "Đổi người dùng (demo)".

## 12. Components mới (`src/components`)
`RowActionsMenu {items:(RowAction|null)[]}` — nút ⋯ (`{key,label,danger?,disabled?,onClick}`, null = đường kẻ) · `ConfirmDanger {open,title,children?,okText?,onOk,onCancel}` — modal nút đỏ (release…) · `DateRangePill {value:{from,to},onChange}` ('YYYY-MM-DD') · `FilterBar {search?,onSearch?,placeholder?,children?,extra?}`. `JobTable` cột `'task'` giờ hiển thị tên **Batch**.

## 13. Deadline (hạn batch / job) — nguồn: `planning/01_2026-11-18_job-deadlines/specs/01-CONTRACTS.md`
**Types (`types.ts`):** `Batch.dueAt: string|null` (ISO hạn giao đối tác) · `Batch.stepBufferDays {qc1,qc2}` (mặc định 2/1) · `Job.due?: Partial<Record<WorkStep,string>>` (ghi đè theo bước) · `BatchEventType` += `due_set|due_clear` · `JobEventType` += `due_override` · `DeadlineStatus = none|on_track|due_soon|overdue`.

**Actions (store, đồng bộ, throw tiếng Việt; caller bọc try/catch → `message.error`):**
| Action | Ai | Hiệu ứng / lỗi |
|---|---|---|
| `setBatchDue(batchId, dueAt\|null, stepBufferDays?)` | pm, admin | cập nhật batch + BatchEvent `due_set` (`Đặt hạn giao DD/MM/YYYY HH:mm`) hoặc `due_clear` (`Bỏ hạn giao`). Throw: không quyền, batch released/delivered, ISO sai, buffer âm |
| `setJobDue(jobId, step, dueAt\|null)` | lead (team của job), pm, admin | ghi/xoá `job.due[step]` + JobEvent `due_override` (from=to=stage hiện tại, reason `Hạn <step>: DD/MM/YYYY HH:mm` hoặc `Bỏ hạn riêng <step>`). Throw: không quyền, job delivered |

**Selectors (`src/mock/deadline.ts`, re-export từ `selectors.ts`; "bây giờ" = `s.now`):** `DUE_SOON_HOURS=24` · `stepOfStage(stage)` · `defaultStepDue(batch, step)` · `stepDue(s, job, step)` / `jobDeadline(s, job)` → `EffectiveDue {step,dueAt,source:'job'|'batch'}|null` · `deadlineStatus(s, job)` (`overdue` khi còn ≤ 0; `due_soon` khi < 24h thực) · `hoursLeft(s, job)` (âm khi trễ) · `onTimeStats(s, {userIds?,teamId?,projectId?,batchId?,from?,to?,step?})` → `{total,onTime,late,rate}` (total=0 ⇒ rate 1; from/to 'YYYY-MM-DD' hoặc ISO; bước không có hạn hiệu lực bị bỏ qua) · `batchForecast(s, batchId)` → `BatchForecast {dueAt,remainingJobs,throughputPerDay,etaAt,verdict,daysLate}` · `overdueJobs(s, {userId?,teamId?,projectId?,batchIds?})` (trễ nhất trước; `userId` = người chịu trách nhiệm bước hiện tại: annotatorId/qc1Id/qc2Id).
Quy ước: `remainingJobs` = job chưa `ready_to_deliver|delivered` (kể cả chưa chia); throughput = số event vào `ready_to_deliver` trong 7 ngày trước `now` / 7; verdict ưu tiên `no_due` → `done` → `late` → `at_risk` → `on_track`; `etaAt` null khi throughput 0 hoặc hết job. Hoàn thành bước (bảng D): annotate = `submit` đầu; qc1 = `qc1_pass` cuối; qc2 = `qc2_pass` cuối (cả khi do `closeAudit`).

**Components (`src/components`):**
- `DeadlineTag {status, dueAt, hoursLeft, compact?, source?}` — pill: overdue hồng "Trễ 5 giờ"/"Trễ 2 ngày", due_soon cam "Còn 6 giờ", on_track xám "Hạn 26/11", none ⇒ không render. Tooltip: `DD/MM/YYYY HH:mm` + nguồn nếu truyền `source` (`jobDeadline(...).source`). `compact` ⇒ "Trễ 5g"/"Còn 6g"/"26/11". Cũng export `deadlineText(...)`.
- `ForecastBadge {forecast}` — on_track xanh "Kịp hạn", at_risk cam "Có nguy cơ trễ", late hồng "Trễ x ngày", done xanh "Đã xong", no_due xám "Chưa đặt hạn"; tooltip ETA / job/ngày / còn lại / hạn giao.
- `DueEditor {value: ISO|null, onChange(iso|null), allowClear?}` — DatePicker + TimePicker (giờ mặc định 17:00 khi mới chọn ngày; chọn giờ bị khoá tới khi có ngày).
- Nhãn lịch sử: `JobTimeline` hiện sự kiện `due_override` là tag "Đổi hạn" + reason; nhãn batch `due_set` = "Đặt hạn giao", `due_clear` = "Bỏ hạn giao" (map `EVENT_LABEL` trong `pages/queue/BatchActions.tsx`).

**Luật bất biến:** I1 mọi hạn/trạng thái lấy qua selector, CẤM page tự tính · I2 `dueAt` và `autoLockAt` độc lập · I3 `job.due[step]` thắng mặc định; batch không `dueAt` và không ghi đè ⇒ `none` · I4 đúng hạn = thời điểm hoàn thành bước so với hạn hiệu lực HIỆN TẠI (không snapshot) · I5 mọi đổi hạn ghi 1 sự kiện (append-only). Vùng cấm: annotator không sửa hạn; không tô đỏ cả batch vì một job trễ (dùng `batchForecast`); không thêm thư viện thời gian (dùng `dayjs`).


## 14. Hàng đợi bấm sâu (plan `planning/05_2026-11-18_queue-drilldown-live`)
`/queue` của admin/pm/lead = Dự án › Dataset › Batch › Job (4 route lồng, `pages/queue/QueuePage.tsx`; annotator: danh sách job được giao — plan 06). Hàng đợi cũ (Luồng/Danh sách/Kanban, MyWork) và `/demo/*` đã xoá.
- **Types mới:** `Partner {name,contact,email,contractNote}` · `ProjectStatus` = running|paused|done · `Project` += `code, partner, dueAt(ISO), status` · `Dataset` += `dueAt|null, preprocessedPct, onCvatPct (≤ preprocessedPct), sceneCount, partnerNote` · `Batch` += `priority: 1|2|3|4|5` (5 = cao nhất) · `BatchEventType` += `priority_set` (nhãn "Đổi ưu tiên").
- **Action:** `setBatchPriority(batchId, priority)` — chỉ admin / pm của dự án; batch `released` ⇒ throw; cùng mức ⇒ no-op (không sự kiện); khác ⇒ cập nhật + đúng 1 `BatchEvent` `priority_set` (`Đổi ưu tiên ★a → ★b`).
- **Seed:** trường mới sinh xác định bằng `stableHash` (FNV-1a + fmix32, export từ `seed.ts`).
- **Phạm vi (Q-I1):** admin tất cả · pm `visibleProjects` · lead: dự án có team của lead, chỉ batch `visibleBatches`, chỉ job `teamId ∈ user.teamIds` (số liệu từng cấp tính trên phạm vi đó). URL ngoài phạm vi ⇒ "Không tìm thấy" + link về `/queue`.
- **UI:** nút quay lại (‹ tròn 40px, `aria-label="Quay lại <cấp trên>"`) nằm ở chỗ nút ⋯ của thẻ danh sách Dataset/Batch/Job (`ListCard` trong `queueShared.tsx`); cấp Dự án không có. ★ chỉ bấm được với pm/admin (lead thấy sao tĩnh). Hạn/dự báo vẫn qua selector `deadline.ts` (Q-I2).

## 15. Tìm nhanh & Thông báo
- `searchFor(state, userId, query): SearchResult[]` (`mock/search.ts`): tìm không phân biệt hoa/thường, dấu; rỗng hoặc user không tồn tại trả `[]`. Kết quả `{id,type,title,link}` nhóm Job/Batch/Dự án/Dataset. Job theo `visibleJobs`; batch theo `visibleBatches`; dự án/dataset theo `visibleProjects`. Annotator chỉ Job; lead chỉ Job/Batch vì không có cấp queue dự án/dataset.
- `notificationsFor(state,userId): Notification[]` (`mock/notifications.ts`): `{id,type,title,at,link}`, mới trước, không ghi state. Return gần nhất nhắm vào user trong 7 ngày (không nhận tương lai); deadline theo người phụ trách bước hiện tại; QC1 theo `qc1Id`; chia batch trong 7 ngày theo team lead hiện tại; risk/drift chỉ PM/admin trong phạm vi. Dùng `deadlineStatus`, `jobDeadline`, `batchForecast`; thời điểm cảnh báo hiện trạng lấy event gần nhất hoặc `state.now` khi không có event. ID theo sự kiện hoặc thực thể + hạn + trạng thái, không theo thời gian render.
- `QuickSearch`: nút header mở ô tìm; `/` ngoài ô nhập hoặc Ctrl/Cmd+K mở/đóng, Esc đóng; link bàn phím Tab/Enter. `NotificationBell`: nhóm ngày UTC theo `state.now`, badge chưa đọc, đọc khi chọn hoặc đánh dấu tất cả. Lưu danh sách ID ở `localStorage` key `cvd-notifications-read:<userId>`, parse/ghi lỗi được bỏ qua; đổi user remount trạng thái đọc. Không backend, không polling, không dependency mới.

## 16. Hàng đợi là nơi làm việc chính (W1-A)
Trang trùng đã xoá: `BatchesPage`, `BatchDetailPage`, `DatasetsPage`, `TeamPoolPage`, `Qc1QueuePage`, `MyJobsPage`, `MyWorkPage`. Route cũ: `/datasets`, `/batches`, `/lead`, `/lead/qc1` ⇒ `/queue`; `/batches/:batchId` ⇒ `queueBatchPath(batch)` = `/queue/:projectId/:datasetId/:batchId` (batch không tồn tại ⇒ `/queue`; annotator bị chặn cấp 3 ⇒ `/queue`). `/me` = `MyKpiPage`.
- **Thao tác job** (`pages/queue/JobActions.tsx`, hook `useJobActions(s) → {render(job), holder}`; mọi action bọc try/catch → `message.error`), cột "Thao tác" ở cấp Job và danh sách job của annotator:

| Vai | Điều kiện | Nút → action |
|---|---|---|
| lead (team của job) | `team_pool` | Giao → modal annotator + QC1 → `assignJob` |
| lead (team của job) | `anno_in_progress`, `qc1_*`, `qc2_*` | Chuyển người → `reassignJob` (chỉ gửi trường đổi) |
| lead (team của job), pm, admin | bước có hạn, chưa `delivered` | Đổi hạn → `JobDueModal` (`DueEditor`) → `setJobDue(step hiện tại)` |
| `canCheckQc1(user, job)` = lead của team hoặc `isQc && qc1Id === user.id`, job `qc1_*` | batch chưa khoá | Check ▾ Đạt → `qc1Pass` · Trả về → `ReworkDialog` → `qc1Return` |
| pm, admin | `qc2_*` | Audit → `/audits` |
| annotator (`annotatorId === me`) | `anno_in_progress`, chưa khoá | Nộp (xác nhận) → `submitJob` · Mở trên CVAT (giả) |

- **Bộ lọc nhanh cấp Job:** `Segmented` Tất cả · Chờ giao (`team_pool`) · Chờ QC1 (`qc1_*`) · Trễ (`deadlineStatus === 'overdue'`), kèm số đếm; áp chồng với ô tìm + Select trạng thái.
- **Bắt đầu job tiếp theo:** đầu danh sách job của annotator và ở cấp Job của lead ⇒ `/jobs/:id` của `nextJob(s, user, jobs)` (`queueScope.ts`, thuần, có test `nextJob.test.ts`); disabled khi không còn job. Thứ tự `rankNextJobs`: chỉ job `canWorkOn` (annotator: job của mình `anno_in_progress`; QC1: `canCheckQc1`) và batch chưa khoá ⇒ trễ → sắp trễ → còn lại; cùng mức ⇒ `batch.priority` cao trước ⇒ `hoursLeft` nhỏ trước (không hạn cuối) ⇒ `cvatJobId`.
- **Dải cảnh báo annotator:** đầu Hàng đợi khi job mình đang làm trễ/sắp trễ; nút "Xem job trễ" đặt bộ lọc trạng thái = trễ.
- **Thao tác batch** (`pages/queue/BatchActions.tsx`, hook `useBatchActions(s) → {menu(batch), holder}`; chỉ pm/admin — `canManageBatch`): cột ⋯ cuối mỗi dòng cấp Batch gồm Reassign (`reassignBatch`, không khi pending/released) · Release (`ConfirmDanger` → `releaseBatch`) · Xem lịch sử (drawer `batchHistory`, nhãn `EVENT_LABEL`) · Đặt/Sửa/Bỏ hạn giao (`BatchDueModal` → `setBatchDue`) · Đặt/Sửa/Gỡ khoá tự động (`setAutoLock`). `DueModals.tsx` chuyển từ `pages/batches/` sang `pages/queue/`.
- Vùng cấm: không dựng lại trang Batches/Datasets/Kho job/Hàng chờ QC1 riêng — mọi thao tác đi qua Hàng đợi; không tự tính thứ tự ưu tiên trong page (dùng `rankNextJobs`).

## 17. Danh sách dòng-thẻ `RowList` (W2-A, `src/components/RowList.tsx`)
- `RowList {heads:string[], cols:string, rows:ListRow[], emptyText, emptyHint?, onClear?, resetKey?}` — `cols` = CSS `grid-template-columns` (chưa gồm cột mũi tên ›); `heads[i]` là nhãn cột và nhãn ô trên mobile (≤900px xếp dọc).
- `ListRow {key, tone:RowTone, label, onOpen, cells:ReactNode[]}` — cả dòng `role="link"`, Enter/Space mở, focus-visible; `label` = aria-label ("Mở …"). Nút trong ô bọc `onClick={stopRow}` để không mở dòng.
- `RowTone = 'ok'|'warn'|'bad'|'idle'` → vạch mép trái xanh/cam/hồng/xám. `kpiTone(today,target)`: không mục tiêu ⇒ idle, đạt ⇒ ok, dưới 50% ⇒ bad, còn lại warn.
- Phân trang cố định `ROWLIST_PAGE_SIZE = 10`; đổi `resetKey` ⇒ về trang 1. Rỗng: `emptyText` + `emptyHint` (mặc định gợi ý bỏ lọc khi có `onClear`) + nút "Xoá bộ lọc" chỉ khi có `onClear`.
- Style: khối `cvd-rowlist-*` cuối `design/dashboard.scss`; `cvd-rowlist-inline` (nhóm tên + thẻ), `cvd-rowlist-actions` (nhóm nút).
- **Dùng khi** dòng dẫn tới trang chi tiết: Hàng đợi (Dự án/Dataset/Batch, re-export qua `queueShared.tsx`), danh sách audit (Đạt xanh · Trượt hồng · Đang mở cam), người dùng/team ở Quản trị, thành viên team (Quản trị, Team lead, PM › team — theo `kpiTone`), job lệch CVAT (chưa xử lý hồng · đã xử lý xanh).
- **Không dùng** cho bảng dày không điều hướng: giữ `DashTable` + `className="cvd-rowlist-table"` (+ `sticky` để header dính) — vd job mẫu của Audit.
