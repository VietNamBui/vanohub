# Đặc tả Platform — VanoHub

> **Mô hình tổ chức phẳng — 4 vai trò:** `PM` (Project Manager), `QC2` (QC Level 2 / Auditor), `QC1` (QC Level 1 / Reviewer), `Annotator`.  
> Đã loại bỏ hoàn toàn tầng `Director` và `Team Leader`; đồng bộ theo thực tế codebase hiện tại và đánh dấu rõ các hạng mục còn chờ chốt / chưa triển khai.

- **Stakeholder**
  - PM: Anh Duyệt, anh An, anh Tú
  - QC Level 2 (QC2)
  - QC Level 1 (QC1)
  - Annotator (Anno)
- **Nội dung tài liệu**
  - [Thông tin chung và luật dự án (PV – NT)](#thông-tin-chung-và-luật-dự-án)
  - [Ma trận phân quyền (RBAC)](#ma-trận-phân-quyền-rbac)
  - [Ma trận sự kiện và người nhận thông báo](#ma-trận-sự-kiện-và-người-nhận-thông-báo)
  - [Chi tiết chỉ số chất lượng chính (FPY, Defect Error Rate, Quality CL)](#chi-tiết-chỉ-số-chất-lượng-chính-fpy-defect-error-rate-quality-cl)
  - [Tổng hợp công thức tính toán trong Platform (SL – DA)](#tổng-hợp-công-thức-tính-toán-trong-platform)
  - [Bố cục trang dashboard theo 4 vai trò](#bố-cục-trang-dashboard)
  - [Đề xuất thiết kế — Dữ liệu Pre-label 3D, Chính sách Guideline, Đánh giá 2 trục & Throughput (Chờ chốt)](#đề-xuất-thiết-kế--dữ-liệu-pre-label-3d-chính-sách-guideline-đánh-giá-2-trục--throughput-chờ-chốt)
  - [Backlog — Kiến trúc Plugin Stub (trên nền cvat-base gốc)](#backlog--kiến-trúc-plugin-stub-trên-nền-cvat-base-gốc)

---

## THÔNG TIN CHUNG VÀ LUẬT DỰ ÁN

### 1. Mục tiêu và phạm vi — PV

| Mã | Vấn đề cần thống nhất | Quy định & hiện trạng |
| --- | --- | --- |
| PV01 | Vấn đề ưu tiên | Giải quyết 3 vấn đề cốt lõi:<br>• Phân mảnh các giai đoạn công việc (quản lý bằng sheet, thao tác trên CVAT, trao đổi truyền miệng).<br>• Dễ sót thông tin và khó quản lý tập trung các thành phần dự án.<br>• Khó mở rộng (scale up) mô hình vận hành hiện tại. |
| PV02 | Người sử dụng | **4 vai trò phẳng:** `PM`, `QC2` (QC Level 2), `QC1` (QC Level 1), `Annotator`. |
| PV03 | Phạm vi MVP | [Danh sách tính năng MVP cần có](./mvp-checklist.md) |
| PV04 | Ranh giới với CVAT | • **Tích hợp trực tiếp trên `cvat-base` gốc (không fork/patch CVAT).**<br>• **Làm trên VanoHub:** Quản lý Organization/Project/Task/Job, giao việc & giới hạn WIP, vòng đời trạng thái job, kiểm duyệt QC1/QC2 cấp frame & ghi nhận lỗi (`ReviewError`), xác nhận Task sang QC2 (`confirm-qc2`), theo dõi tiến độ/deadline/KPI & sổ sản lượng ngày (`DailyOutputRecord`), thông báo trong app, nhật ký thao tác và ghi nhận bàn giao (`Delivery`).<br>• **Làm trên CVAT:** Vẽ/chỉnh sửa annotation (`shapes` / `tracks` / cuboid 3D / object 2D) trực tiếp qua deep link từ VanoHub.<br>• *Hiện trạng đồng bộ:* VanoHub đồng bộ cấu trúc & tiến độ trước QC2 một chiều từ CVAT (`POST /api/cvat/sync-organizations/`, `POST /api/projects/{id}/cvat-sync/`, CLI `sync_cvat`), lọc chỉ job `type = annotation` (loại `ground_truth`/`consensus`), bung track thành số cuboid/object-frame theo từng frame hợp lệ (`outside`, `frame_step`, `deleted_frames`, `included_frames`). Ghi ra CVAT được giới hạn nghiêm ngặt ở **job `assignee`** (`PATCH /api/jobs/{id}`) và **lời mời organization** (`POST /api/invitations?org=<slug>`) sau khi người dùng tự liên kết `CvatAccount` (`/api/cvat/link/`). Telemetry/webhook ngoài để vào Backlog. |
| PV05 | Tiêu chí thành công | • Giảm thời gian tổng hợp, hỏi tiến độ và thao tác quản lý của PM nhờ tập trung trên 1 nền tảng.<br>• Số liệu cập nhật liên tục theo từng dự án, dễ báo cáo và bám sát KPI nhân sự.<br>• Giảm thời gian job nằm chờ giữa các bước (`Anno → QC1 → QC2 → Bàn giao`).<br>• Batch bàn giao đúng hạn hơn mà không giảm chất lượng. |

### 2. Quy trình và tổ chức — TC

| Mã | Vấn đề cần thống nhất | Quy định & hiện trạng |
| --- | --- | --- |
| TC01 | Quy trình vận hành (phẳng) | Vòng đời chuẩn của công việc:<br>1. Nhân sự tự liên kết tài khoản CVAT qua `/api/cvat/link/` (`CvatAccount`); **PM** đồng bộ CVAT Organization → `Organization` trên VanoHub (`POST /api/cvat/sync-organizations/`) và cấu hình quy tắc (rework, tỷ lệ frame QC2, WIP, KPI, danh mục lỗi, guideline).<br>2. Đội tiền xử lý tạo Project / Task / Job trên CVAT; **PM** đồng bộ về VanoHub (`POST /api/projects/{id}/cvat-sync/`): `CVAT Project → Dataset`, `CVAT Task → Batch`, `CVAT Job → Job`.<br>3. **PM** giao job (hoặc **Annotator** tự nhận từ hàng chờ theo WIP; hệ thống tự đẩy CVAT `assignee` hậu commit) → Annotator thực hiện trên CVAT và nộp bài lên QC1.<br>4. **QC1** kiểm tra từng job: `Đạt QC1` (`qc1_passed`) hoặc `Reject` kèm `ReviewError` → `Rework`.<br>5. **Hybrid A2 gate:** Khi **100% job trong Task (`Batch`)** đã đạt QC1 (không còn job khóa/chặn), **PM** bấm `confirm-qc2` một lần cho Task đó để chuyển các job `qc1_passed` sang `pending_qc2` và ghi nhận `Batch.qc2_confirmed_at`. Với job rework hậu QC2, khi qua `qc1_pass` sẽ đi thẳng sang `pending_qc2`.<br>6. Mỗi job vào `pending_qc2` tự động gắn vào đợt `Audit` đang mở của Task và sinh `AuditSample` cấp **frame** (`Project.sampling_rate`%, mặc định `20%`), tự phân auditor QC2 ít tải nhất (đảm bảo luật bốn mắt) → QC2 chấm `Pass` (`→ approved`) hoặc `Reject` (`→ rework`).<br>7. Khi **100% job của Task** đạt `approved`, không có job khóa và không còn `AuditSample` `pending`, **PM** ghi nhận `Delivery` (`POST .../deliveries/`) để tự động chốt `Audit` → `completed` và khóa/chuyển Task + mọi Job sang `delivered`. |
| TC02 | Cơ cấu quản lý | • **Cấu trúc phẳng:** `PM → Annotator / QC1 / QC2` (không có tầng Director hay Team Leader).<br>• **PM** chịu trách nhiệm tổng thể dự án, trực tiếp điều phối công việc hằng ngày, chốt tiêu chuẩn chất lượng, phân xử khiếu nại lỗi và xử lý dữ liệu bị chặn.<br>• Không ai được tự ý thay đổi tiêu chuẩn gán nhãn hoặc bỏ qua lỗi khi chưa có quyết định của PM. |
| TC03 | Dự án và nhóm phân bổ | • Mọi thành viên tham gia dự án qua bản ghi phân quyền theo dự án (`RoleAssignment`) và chịu quản lý trực tiếp của **PM**.<br>• *Ghi chú kỹ thuật:* Hệ thống có thực thể `Team` / `TeamMember` (không có `leader`) dùng làm nhóm phân bổ tùy chọn cho PM quản lý sức chứa (`capacity`), lọc pool batch và gửi thông báo nhóm; không tạo tầng quản lý trung gian. |
| TC04 | Thành viên | Mỗi thành viên (`Annotator`, `QC1`, `QC2`) được PM thêm vào dự án và có thể tham gia nhiều dự án với các vai trò độc lập theo từng dự án. |
| TC05 | Kiêm nhiệm và thay thế | • **Kiêm vai trò:** Một người có thể giữ nhiều vai trò trong cùng dự án (nhiều dòng `RoleAssignment`). Đặc biệt, **`PM` mặc định kiêm `QC2`** (`IMPLIED_ROLES = {PM → QC2}`); chiều ngược lại không đúng.<br>• **Luật bốn mắt (bắt buộc):** Không được QC1 job mình đã annotate; không được audit QC2 job mình đã annotate hoặc đã QC1.<br>• **Thay thế khi vắng mặt:** Dùng tài khoản riêng của người thay thế (không dùng chung tài khoản); PM giao lại job cho QC/Annotator khác đảm bảo không vi phạm luật bốn mắt; PM khác trong dự án tiếp nhận khi PM vắng mặt. |

### 3. Dữ liệu và cấu trúc công việc — DL

| Mã | Vấn đề cần thống nhất | Quy định & hiện trạng |
| --- | --- | --- |
| DL01 | Nguồn dữ liệu | Dữ liệu ảnh/LiDAR gốc được đội tiền xử lý lọc và tổ chức thành **Organization / Project / Task / Job** trên CVAT. Người dùng tự liên kết `CvatAccount` (`/api/cvat/link/`); PM kéo danh sách Organization về VanoHub (`POST /api/cvat/sync-organizations/`) và đồng bộ cây Project / Task / Job qua `POST /api/projects/{id}/cvat-sync/` (hoặc CLI `manage.py sync_cvat`). *(Hàm `import_task_jobs`/`sync_batch` trong `cvat_integration/sync.py` được giữ ở tầng service).* |
| DL02 | Quan hệ dữ liệu | Phân cấp chuẩn 4 tầng (tên model backend giữ nguyên để tương thích nội bộ, nhãn UI hiển thị theo thuật ngữ CVAT):<br>• **`Organization` (`Project` model) ↔ `CVAT Organization`** (`cvat_org_id`, `cvat_org_slug`, `cvat_synced_at`)<br>• **`Project` (`Dataset` model) ↔ `CVAT Project`** (`cvat_project_id`, `last_synced_at`)<br>• **`Task` (`Batch` model) ↔ `CVAT Task`** (`cvat_task_id`, `last_synced_at`, `qc2_confirmed_at`, `qc2_confirmed_by`)<br>• **`Job` (`Job` model) ↔ `CVAT Job`** (`cvat_job_id` duy nhất toàn hệ thống, `cvat_task_id`, `cvat_start_frame`, `cvat_assignee_id`)<br>• Các thực thể gắn kèm: `Batch → Audit → AuditSample` (cấp frame); `Batch → Delivery` (duy nhất mỗi Task); `Job → ReviewError`, `AnnotatorRequest`, `DailyOutputRecord`, `ActivityLog`; `User → CvatAccount`. |
| DL03 | Quyền tạo | • **Organization (`Project`):** Tạo bằng đồng bộ từ CVAT Organization (khi có Owner/Maintainer đã liên kết VanoHub) hoặc PM tạo mới thủ công trên VanoHub (`POST /api/projects/`).<br>• **Project (`Dataset`), Task (`Batch`), Job (`Job`):** Tạo từ đồng bộ CVAT (`POST /api/cvat/sync-organizations/`, `POST /api/projects/{id}/cvat-sync/`); không tạo Project/Task/Job gắn CVAT thủ công tách rời trên UI. |
| DL04 | Quy tắc chia task (batch) | Mặc định `1 Task (Batch) = 1 CVAT Task`, số job trong task linh hoạt theo CVAT. `POST .../jobs/bulk-move-batch/` chỉ áp dụng cho job nội bộ chưa gắn CVAT (`cvat_job_id is None`), chưa khóa/bàn giao và không thuộc đợt audit `in_progress` — **chặn cứng** mọi job đã gắn `cvat_job_id`. |
| DL05 | Thông tin bắt buộc & cấu hình | • **Organization (`Project`):** Tên, mô tả, PM phụ trách (`pm_ids`), liên kết `cvat_org_id` / `cvat_org_slug` (tùy chọn với dữ liệu demo/tạo tay).<br>• **Cấu hình vận hành trên `Project`:** `max_rework_rounds` (mặc định DB `3`, tối thiểu `1`), `escalation_policy` (`block` mặc định / `warn_only`), `annotator_wip_limit` (mặc định `2`, `1..50`), tỷ lệ lấy mẫu frame QC2 (`sampling_rate`: mặc định **`20%`**, `1..100`; hai cột `sampling_method`/`stratify_by` giữ ở DB để tương thích lịch sử, không còn dùng), ngưỡng `quality_cl_threshold` / `defect_rate_threshold`, chỉ tiêu `kpi_annotation_target` (object/ngày), `kpi_qc1_target` (job/ngày), `kpi_qc2_target` (job/ngày).<br>• **Task (`Batch`):** Tên (đồng bộ theo CVAT Task), `deadline` (tự kế thừa xuống mọi job chưa hoàn tất của Task khi cập nhật), `team` phụ trách. |
| DL06 | Thay đổi cấu trúc | • **Không xóa cứng** Dataset, Batch, Job hay Danh mục lỗi đang dùng để bảo toàn truy vết.<br>• PM được `lock` / `unlock` Dataset, Batch, Job (khi chưa `delivered`), giao/giao lại job, đổi deadline, chuyển batch cho job nội bộ (`bulk-move-batch`). Mọi thay đổi đều ghi `ActivityLog` (trước/sau, người thao tác, lý do). |
| DL07 | Hướng dẫn gán nhãn | • Chỉ **PM** (`manage_quality_catalog`) soạn và phát hành `Guideline` dạng Markdown; mỗi lần lưu tự tăng `version` (khóa dòng Project chống trùng phiên bản), giữ nguyên toàn bộ phiên bản cũ.<br>• Mọi vai trò trong dự án đều xem được toàn bộ lịch sử phiên bản.<br>• *Chưa chốt kỹ thuật:* Job chưa lưu `guideline_version` áp dụng tại thời điểm giao (mặc định tham chiếu bản mới nhất); đề xuất bổ sung `annotation_policies` (`do_not_delete`, `outside_only`, `add_only`) theo Guideline tại mục [Đề xuất thiết kế — Pre-label 3D & Guideline](#đề-xuất-thiết-kế--dữ-liệu-pre-label-3d-chính-sách-guideline-đánh-giá-2-trục--throughput-chờ-chốt). |

### 4. Giao việc và thực hiện — GV

| Mã | Vấn đề cần thống nhất | Quy định & hiện trạng |
| --- | --- | --- |
| GV01 | Cách nhận việc | Hỗ trợ song song 2 cách:<br>• **PM phân công chủ động** từng job hoặc hàng loạt (`assign` / `bulk-assign`) cho Annotator và QC1.<br>• **Annotator tự nhận việc (`claim`)** từ pool job `pending_annotation` chưa có người làm (tự động khóa dòng `skip_locked` tránh nhận trùng, ưu tiên deadline sớm nhất và tuân thủ luật bốn mắt). |
| GV02 | Điều kiện nhận việc | Giới hạn WIP theo cấu hình dự án (`Project.annotator_wip_limit`, mặc định **2 job** đang ở `pending_annotation` / `annotating` / `rework`). Annotator đạt giới hạn phải nộp bớt mới được nhận thêm (chặn ở API `claim` với khóa tuần tự theo user). |
| GV03 | Thứ tự ưu tiên | Hàng đợi công việc cá nhân và QC1 sắp theo **DB06**: `Quá hạn → Sắp đến hạn (≤ 24h) → Rework → Còn lại`, sau đó theo deadline sớm nhất và ID job. Khi tự nhận từ pool, ưu tiên batch của nhóm phân bổ (nếu có) và deadline sớm nhất. |
| GV04 | Thu hồi và giao lại | **PM** có quyền giao lại Annotator / QC1 / Auditor QC2 (`assign`, `bulk-assign`, `audit-samples/{id}/assign`) khi job chưa khóa/bàn giao, kèm ghi chú lý do, tự động gửi thông báo `assigned` cho người mới và đẩy cập nhật `assignee` sang CVAT (`schedule_assignee_push`). *(Chưa có bước xác nhận đồng ý 2 chiều từ người nhận cũ).* |
| GV05 | Công việc dở dang | Khi đổi người làm job, sổ sản lượng ngày (`DailyOutputRecord`) và các lượt nộp trong `ActivityLog` gắn cứng theo đúng `actor` thực hiện — sản lượng đã ghi nhận của người cũ không bị chuyển sang người mới; phần việc làm sau khi giao lại tính cho người mới. **Không tính cơ chế cover hộ** (ai trực tiếp làm/duyệt thì ghi đúng người đó). |
| GV06 | Nộp bài | Annotator chuyển `pending_annotation` / `rework` → `annotating` (`start`) → `pending_qc1` (`submit`, kèm ghi chú). Sản lượng làm được theo ngày được ghi nhận ngay cả **trước khi QC** (qua đồng bộ CVAT `count_objects=true`) và **sau khi nộp/QC vẫn giữ nguyên như thường** (không cộng đúp, không trừ ngược ngày cũ). Sau khi nộp, Annotator không thể tự rút job về mà phải chờ QC1 kiểm tra (`Đạt QC1` hoặc `Reject` sang `rework`).<br>• *Đề xuất chờ chốt (Pre-label):* Khóa nhập tay `object_count` cho job đã gắn `cvat_job_id` (tự động đọc CVAT khi nộp, có cờ `count_sync_pending` khi CVAT lỗi để không oan deadline) và chụp baseline `S0` lúc đồng bộ/import — xem mục [Đề xuất thiết kế](#đề-xuất-thiết-kế--dữ-liệu-pre-label-3d-chính-sách-guideline-đánh-giá-2-trục--throughput-chờ-chốt). |

### 5. Luồng duyệt, chất lượng và ngoại lệ — L

| Mã | Vấn đề cần thống nhất | Quy định & hiện trạng |
| --- | --- | --- |
| **L1** | **Vòng đời trạng thái Job** | 9 trạng thái chuẩn trên `JobStatus`:<br>`pending_annotation` (Chờ annotate) → `annotating` (Đang annotate) → `pending_qc1` (Chờ QC1) → `qc1_reviewing` (Đang QC1) → `qc1_passed` (Đạt QC1) → `pending_qc2` (Chờ QC2, sau khi PM `confirm-qc2` cho Task; hoặc đi thẳng với rework hậu QC2) → `approved` (Đã duyệt) → `delivered` (Đã bàn giao).<br>Nhánh trả sửa: `qc1_reviewing` / `pending_qc2` → `rework` → `annotating`. |
| **L2** | **Vượt giới hạn rework** | • Giới hạn vòng sửa `max_rework_rounds` do PM cài đặt theo dự án (mặc định DB `3`, tối thiểu `1`).<br>• Mỗi lần QC1/QC2/CVAT-sync trả job về `rework`, tăng cả `rework_round += 1` và `total_rework_rounds += 1`. Khi `rework_round > max_rework_rounds`, bật `is_escalated = True` và gửi thông báo `escalated` (ghim chờ xử lý) lên **PM**.<br>• Chính sách xử lý `escalation_policy` do PM chọn: `block` (mặc định — khóa job chờ PM gọi `resolve-escalation`) hoặc `warn_only` (chỉ cảnh báo, vẫn cho Annotator sửa tiếp). Khi PM gỡ escalation, có thể đổi người làm và đặt lại `rework_round = 0` cho vòng xử lý mới, trong khi **giữ bất biến `total_rework_rounds`, `first_qc1_result` và toàn bộ lịch sử lỗi** để không làm sai lệch `CL01` / `RW02`. |
| **L3** | **Chuyển QC1 → QC2 (Hybrid A2)** | • **Trước khi Task xác nhận QC2 (`batch.qc2_confirmed_at is None`):** QC1 duyệt từng job sang `qc1_passed`. Khi **100% job trong Task** đã qua QC1 (không còn job ở `BLOCKING_QC2_STATUSES`, không còn job khóa), hệ thống gửi thông báo `review_needed` cho PM. **PM** thực hiện `POST .../batches/{id}/confirm-qc2/` một lần cho Task (yêu cầu `Batch` & `Dataset` `active`, 0 job khóa, 0 job chặn, ≥ 1 job `qc1_passed`) để chuyển toàn bộ job `qc1_passed` sang `pending_qc2`, đặt `batch.qc2_confirmed_at` và tự động sinh lượt QC2 (`ensure_qc2_sample`).<br>• **Sau khi Task đã xác nhận QC2 (`batch.qc2_confirmed_at is not None`):** Mọi job rework hậu QC2 khi đạt `qc1_pass` (hoặc đồng bộ CVAT `POST_QC1_CVAT_STATES`) đi **thẳng** sang `pending_qc2` và tự động tạo lượt `AuditSample` mới (không phải chờ `confirm-qc2` lại cả Task). |
| **L4** | **Quyền quyết định chất lượng** | • `AuditViewSet` **chỉ đọc** (mỗi Task có tối đa 1 đợt `Audit` `in_progress` tự tạo khi job đầu tiên của Task vào `pending_qc2`).<br>• **QC2** (hoặc **PM** kiêm QC2, tuân thủ luật bốn mắt) chấm `Pass` (`→ approved`) hoặc `Reject` (`→ rework`, bắt buộc kèm `ReviewError` và `rework_scope`) cho từng `AuditSample` qua `AuditSampleViewSet.{pass_,reject}`.<br>• Khi **100% job** trong Task ở trạng thái `approved`, không có job khóa và không còn `AuditSample` `pending`, **PM** ghi nhận bàn giao (`DeliveryViewSet.perform_create`), hệ thống **tự động chốt mọi `Audit` `in_progress` sang `completed`** và chuyển `Batch` + toàn bộ `Job` sang `delivered` *(không còn bước `Audit.complete` accept/reject/partial_reject rời trước bàn giao)*. |
| L5 | Điều kiện đạt QC1 | QC1 kiểm tra toàn bộ job trên CVAT và đánh dấu đạt/trả sửa theo ngưỡng chất lượng dự án (`quality_cl_threshold` / `defect_rate_threshold` do PM cấu hình). |
| L6 | Danh mục lỗi | • Quản lý theo từng dự án (`ErrorCategory`): tên lỗi, mô tả, mức độ (`minor` Nhẹ / `major` Nặng / `critical` Nghiêm trọng), phạm vi áp dụng (`qc1` / `qc2` / `both`).<br>• Với cuboid: thiếu/thừa đối tượng, sai lớp, sai vị trí/kích thước/hướng, sai thuộc tính, sai ID liên kết giữa các frame.<br>• Chỉ **PM** tạo/sửa danh mục; không xóa cứng (`on_delete=RESTRICT`), chỉ ẩn bằng `is_active = False` để bảo toàn lịch sử. |
| L7 | Bằng chứng lỗi | Khi QC1 hoặc QC2 trả `Reject`, bắt buộc ghi ít nhất 1 `ReviewError` gồm loại lỗi, mức độ (`minor`/`major`/`critical`), phân loại kết luận độc lập `verdict` (`fail` \| `edge`), cờ tường minh `is_missing_object` (True khi thiếu đối tượng / False Negative — DB chặn `cvat_object_id != None` và `verdict = "edge"`), vị trí (`location` + trường có cấu trúc tùy chọn `frame_number`, `cvat_object_id`) và mô tả. |
| L8 | Phạm vi sửa và kiểm lại | Khi trả rework QC1 hoặc QC2, reviewer chọn `rework_scope`: `partial` (sửa theo danh sách lỗi đã ghi) hoặc `full` (sửa toàn job). Annotator xem chi tiết lỗi theo từng vòng sửa; QC1 kiểm lại theo phạm vi tương ứng. |
| L9 | Lấy mẫu QC2 (cấp frame) | • Triển khai lấy mẫu **cấp frame trên MỌI job vào `pending_qc2`** (`backend/quality/qc2.py`):<br>&nbsp;&nbsp;◦ Số frame cần kiểm: $k = \min(F, \max(1, \lceil F \cdot r / 100 \rceil))$ với $F = \max(\text{job.frame\_count}, 1)$ và $r = \text{Project.sampling\_rate}$% (mặc định **`20%`**).<br>&nbsp;&nbsp;◦ `pick_frames()` chọn offset ngẫu nhiên **cố định theo `(job.pk, job.rework_round)`** và cộng `job.cvat_start_frame` để mở đúng số frame trên CVAT (đồng bộ lại không làm đổi danh sách frame).<br>&nbsp;&nbsp;◦ `pick_auditor()` tự phân lượt `AuditSample` cho người có vai trò trực tiếp `QC2` đang ít lượt `pending` nhất (không tự đẩy vào PM kiêm QC2), loại trừ xung đột bốn mắt; không có ai phù hợp thì để trống cho PM phân qua `audit-samples/{id}/assign/`. *(Hai cột `sampling_method`/`stratify_by` chỉ giữ trên DB để tương thích lịch sử, không dùng).* |
| L10 | Job / lượt kiểm không đạt ở QC2 | Khi QC2 chấm `Reject` trên `AuditSample`, job chuyển về `rework`, tăng `rework_round` và `total_rework_rounds` (kiểm tra escalation), thông báo cho Annotator và QC1 phụ trách. Sau khi Annotator sửa và đạt `qc1_pass`, vì Task đã đặt `batch.qc2_confirmed_at`, job tự động quay thẳng về `pending_qc2` và sinh lượt `AuditSample` mới (`rework_round` mới). |
| L11 | Phản hồi lỗi | Annotator gửi yêu cầu `error_dispute` gắn với job và `ReviewError` cụ thể **trực tiếp tới PM** (`status = pending_pm`); PM xem xét và kết luận `resolved` hoặc `rejected` kèm `resolution_note`. Khi PM kết luận `resolved`, lỗi `ReviewError` gắn kèm tự động đánh dấu `is_voided = True` (giữ lịch sử truy vết, loại khỏi tính toán `CL02`/`CL04`/`CL06`/`CL11`/`RW04` và ghi nhận vào `CL09`). |
| L12 | Dữ liệu có vấn đề | Annotator báo `data_issue` **trực tiếp tới PM** (`status = pending_pm`). PM có thể tạm khóa job (`lock`) trong thời gian chờ xử lý dữ liệu / xác nhận khách hàng, sau đó kết luận yêu cầu và mở khóa. |
| L13 | Luật bốn mắt | Thực thi cứng ở backend trên mọi thao tác giao việc, tự nhận việc, QC1 (`_check_qc1_access`, `_exclude_four_eyes_conflicts` trong `backend/quality/views.py`) và QC2 (`four_eyes_conflicts`, `get_stage_history` trong `backend/quality/qc2.py`): kiểm tra cả người đang được giao hiện tại lẫn **lịch sử `ActivityLog` / `ReviewError` / `AuditSample`** để ngăn lách luật bốn mắt bằng cách giao lại job. |
| L14 | Can thiệp và mở lại | PM có quyền `lock` / `unlock` job, batch, dataset chưa bàn giao và gỡ escalation (`resolve-escalation`). *(Chưa có API mở lại job đã `approved` hoặc `delivered` về `rework` — cần bổ sung nếu áp dụng quy trình hậu bàn giao).* |

### 6. Deadline và thời gian — TG

| Mã | Vấn đề cần thống nhất | Quy định & hiện trạng |
| --- | --- | --- |
| TG01 | Các cấp deadline | Mục tiêu: Project, Dataset, Batch và Job do **PM** đặt.<br>• *Hiện trạng DB:* Đã có `deadline` ở cấp **Batch** và **Job** (job tự kế thừa hạn batch khi import; PM đặt/đổi hàng loạt qua `bulk-deadline`). Cấp Project và Dataset chưa có cột `deadline`. |
| TG02 | Cách tính thời gian | Deadline lưu theo mốc `DateTime` chuẩn UTC và hiển thị cố định theo múi giờ vận hành Việt Nam `Asia/Ho_Chi_Minh` (`backend/accounts/datetime_utils.py`, `frontend/src/shared/utils/format.ts`; trường `User.timezone_name` chưa kích hoạt đa múi giờ). |
| TG03 | Gia hạn | Chỉ **PM** được điều chỉnh deadline batch/job; thao tác đổi hạn job **bắt buộc ghi lý do (`note`)** và lưu giá trị trước/sau vào `ActivityLog`. |
| TG04 | Quá hạn và sắp hạn | • `due_soon`: còn `≤ 24 giờ` so với hiện tại trên job đang mở (`OPEN_STATUSES`).<br>• `overdue`: đã quá hạn trên job đang mở.<br>• Hệ thống tự tạo cảnh báo `deadline` (ghim chờ xử lý) cho người đang giữ job (Annotator / QC1 / QC2) và **PM** dự án. |
| TG05 | Rework và tạm dừng | PM có thể đặt/điều chỉnh lại deadline khi job vào rework. *(Chưa có cơ chế tự động trừ thời gian tạm dừng do `data_issue` / `error_dispute` khỏi thời gian tính SLA).* |

### 7. KPI và chỉ số — CS

| Mã | Vấn đề cần thống nhất | Quy định & hiện trạng |
| --- | --- | --- |
| CS01 | Đơn vị sản lượng | • **Annotator:** Số cuboid 3D / object 2D (object-frame) làm được mỗi ngày (`kpi_annotation_target`). Không liên quan tiền bạc/trả công.<br>• **QC1 & QC2:** Số job hoàn tất kiểm tra mỗi ngày (`kpi_qc1_target`, `kpi_qc2_target`).<br>• Toàn bộ chỉ tiêu do **PM** cấu hình theo từng dự án. |
| CS02 | Thời điểm ghi nhận | • **Annotator (tính theo ngày làm, cả trước và sau QC):** Ghi vào sổ sản lượng ngày `DailyOutputRecord(user, job, work_date, is_rework, object_count, source)` theo múi giờ nghiệp vụ:<br>&nbsp;&nbsp;◦ **Khi chưa QC (đang annotate/rework):** Khi đồng bộ CVAT (`cvat-sync` với `count_objects=true`) thấy số cuboid/object-frame tăng thêm `Δ > 0`, ghi nhận ngay `Δ` vào đúng ngày hôm đó cho `job.annotator`.<br>&nbsp;&nbsp;◦ **Khi nộp bài (`submit`) & sau QC:** Chỉ ghi phần chênh lệch chưa ghi nhận (không cộng đúp phần đã đồng bộ trong ngày). Khi QC1/QC2 duyệt `Pass` giữ nguyên sản lượng đã ghi (không dịch ngày, không cộng thêm); khi QC trả `Reject` không trừ ngược sản lượng ngày cũ.<br>• **QC1:** Ghi nhận tại thời điểm bấm `qc1.pass` hoặc `qc1.reject` cho đúng `actor`.<br>• **QC2:** Ghi nhận tại thời điểm bấm `pass` hoặc `reject` trên `AuditSample` (`reviewed_at`) cho đúng `reviewed_by` (**không tính cover hộ / không cộng đúp cho `auditor` được giao nếu người khác kiểm**). |
| CS03 | Rework và nhiều người làm | • Sản lượng rework (`SL03`) **vẫn tính vào tổng sản lượng KPI** của Annotator (`SL06 = SL01 + SL03`), hiển thị tách biệt hai phần.<br>• Khi `rework_scope = partial`, **không** cộng lại toàn bộ `job.object_count` — chỉ ghi phần thực sửa (số cuboid lỗi duy nhất của vòng hiện tại cộng phần object tăng thêm chưa ghi nhận). Khi `rework_scope = full`, tính theo khối lượng làm lại của vòng đó (trừ phần đã ghi trước lúc nộp trong cùng vòng).<br>• Khi nhiều người tham gia cùng 1 job, mỗi bản ghi `DailyOutputRecord` và lượt duyệt gắn theo đúng `actor` trực tiếp thực hiện (**không có ngoại lệ cover hộ**). |
| CS04 | Chỉ tiêu KPI | Gộp `KPI07` vào **`KPI02`** (chỉ tính theo khối lượng cuboid 3D / object 2D / job trên `Project.kpi_*_target`, không tách khoán/tiền bạc).<br>• *Hạng mục mở rộng sau MVP:* Thêm bảng lịch sử `KpiTargetHistory(effective_from)` khi cần đổi chỉ tiêu giữa kỳ mà không ảnh hưởng lịch sử cũ. |
| CS05 | Chất lượng | Xem chi tiết tại mục [Chi tiết chỉ số chất lượng chính (FPY, Defect Error Rate, Quality CL)](#chi-tiết-chỉ-số-chất-lượng-chính-fpy-defect-error-rate-quality-cl). |
| CS06 | Tốc độ làm việc | • **Annotator:** `AnnotatorAnalyticsView` tính giờ phiên đo thực (`NS01`) bằng hợp nhất (union) các khoảng `ANNOTATING → PENDING_QC1` (giới hạn `0.25h – 10h`/phiên, không cộng đúp giờ song song khi WIP ≥ 2, không gán cứng giờ ảo `7.5h` cho ngày chưa có phiên nộp). Chưa tự trừ giờ nghỉ/chờ.<br>• **QC1 / QC2:** Chưa lưu thời điểm bắt đầu kiểm từng lượt audit nên `audit_speed` đang trả trạng thái `pending_definition`. |
| CS07 | Đánh giá QC | • Đánh giá QC1 theo sản lượng kiểm, tỷ lệ Pass/Reject, phân bố lỗi ghi nhận và **số lỗi QC1 bỏ sót (`qc2_escape_errors`)** — tức lỗi QC2 phát hiện trên job mà QC1 đó đã duyệt đạt.<br>• Đánh giá QC2 theo số mẫu audit, tỷ lệ Pass/Reject, tiến độ theo batch và so sánh 2 kỳ.<br>• Tranh chấp kết luận chất lượng do **PM** phân xử. |
| CS08 | Kỳ báo cáo và múi giờ | Báo cáo theo `day` / `week` / `month` (và `7d` / `30d` / `week` cho phân tích cá nhân), quy ngày cố định theo múi giờ vận hành `Asia/Ho_Chi_Minh` (`APP_TIME_ZONE`) và hiển thị mốc đồng bộ CVAT gần nhất (`last_cvat_sync_at`). |

### 8. Phân quyền và bảo mật — PQ

| Mã | Vấn đề cần thống nhất | Quy định & hiện trạng |
| --- | --- | --- |
| PQ01 | Phạm vi nhìn thấy | • **PM:** Xem toàn bộ dữ liệu trong các dự án được phân công.<br>• **QC2:** Chỉ xem các đợt audit và mẫu `AuditSample` được giao cho mình.<br>• **QC1:** Chỉ xem job được giao kiểm và pool job `pending_qc1` hợp lệ (loại trừ job tự annotate).<br>• **Annotator:** Chỉ xem job được giao cho mình, lỗi/yêu cầu của mình và thứ hạng cá nhân (không thấy điểm/dữ liệu của đồng nghiệp).<br>• Người không thuộc dự án nhận `404 Not Found` (không tiết lộ dự án có tồn tại).<br>• Chi tiết xem tại [Ma trận phân quyền (RBAC)](#ma-trận-phân-quyền-rbac). |
| PQ02 | Quản lý quyền | • **PM** tạo/sửa dự án, gán danh sách PM phụ trách (`pm_ids`) và gán thêm các vai trò `QC2`, `QC1`, `Annotator` cho thành viên trong dự án (`POST .../members/{user_id}/roles/`).<br>• Quản trị tài khoản hệ thống (`User`, cấp quyền superuser/PM đầu tiên) do quản trị viên Django Admin đảm nhiệm. |
| PQ03 | Tài khoản và nghỉ việc | Mỗi nhân sự có tài khoản riêng trên VanoHub liên kết 1-1 với tài khoản CVAT qua `CvatAccount` (`/api/cvat/link/`). Khi nghỉ việc, vô hiệu hóa tài khoản (`is_active = False` — giữ toàn bộ lịch sử), PM giao lại các job đang mở cho người khác; nếu PM nghỉ, bàn giao dự án qua danh sách `pm_ids` hoặc cập nhật vai trò Owner/Maintainer trên CVAT organization. |
| PQ04 | Xuất và tải dữ liệu | VanoHub không mở tính năng tải/xuất dữ liệu gốc đại trà; dữ liệu annotation và xuất tập tin nằm trên CVAT dưới quyền kiểm soát của PM. Mọi thao tác quản trị trên VanoHub đều ghi nhật ký. |
| PQ05 | Nhật ký và lưu trữ | • **Ghi `ActivityLog`:** Tạo/sửa dự án & cài đặt, thêm vai trò, tạo/khóa dataset & batch, nhập/đồng bộ CVAT, giao/đổi hạn/khóa/chuyển batch job, start/submit, QC1 pass/reject, xác nhận chuyển QC2, tạo/chốt audit & QC2 pass/reject, khiếu nại lỗi & báo dữ liệu lỗi, bàn giao, phát hành guideline, gửi thông báo, quản lý nhóm phân bổ.<br>• **Dữ liệu lưu:** `actor`, `created_at`, `action`, `target_type/id/label`, `job`, `before`, `after`, `note`. Không lưu mật khẩu/token.<br>• **Bất biến:** `ActivityLogViewSet` chỉ đọc (`ReadOnlyModelViewSet`), không sửa/xóa qua API. PM xem toàn bộ nhật ký dự án (`view_activity`); Annotator/QC1/QC2 xem dòng thời gian (`events`) trên job họ có quyền truy cập.<br>• **Chính sách lưu trữ:** Đề xuất giữ nhật ký tối thiểu **12 tháng** cho MVP; chưa tự động xóa dữ liệu dự án khi chưa chốt chính sách lưu trữ với khách hàng. |

### 9. Thông báo và phối hợp — TB

| Mã | Vấn đề cần thống nhất | Quy định & hiện trạng |
| --- | --- | --- |
| TB01 | Sự kiện và người nhận | Xem đầy đủ tại mục [Ma trận sự kiện và người nhận thông báo](#ma-trận-sự-kiện-và-người-nhận-thông-báo). |
| TB02 | Kênh thông báo | Thông báo trong app (`GET /api/projects/{id}/notifications/` hợp nhất `UserNotification`, cảnh báo hạn `deadline` động và `Announcement`). |
| TB03 | Treo thông báo chưa xử lý | Các thông báo cần hành động (`rework`, `review_needed`, `escalated`, `deadline`, `dispute`) được gắn cờ `is_pinned_pending = True` và ghim lên đầu danh sách cho tới khi hành động tương ứng hoàn tất (ví dụ: Annotator nộp lại bài, QC1 duyệt xong, PM kết luận yêu cầu). |
| TB04 | Phân loại và tùy chỉnh | • 8 nhãn phân loại (`category`): `assigned`, `rework`, `review_needed`, `escalated`, `deadline`, `dispute`, `qc_pass`, `announcement`.<br>• Người dùng tùy chỉnh bật/tắt 4 nhóm trên trang Tài khoản (`notify_rework`, `notify_deadline`, `notify_request_updates`, `notify_qc_pass`).<br>• Trao đổi nghiệp vụ hiện thực hiện qua ghi chú nộp/duyệt và luồng `AnnotatorRequest` *(chưa có luồng bình luận tự do trên job)*. |

### 10. Bàn giao — BG

| Mã | Vấn đề cần thống nhất | Quy định & hiện trạng |
| --- | --- | --- |
| BG01 | Điều kiện bàn giao | • **Cấp Task (`Batch` — đã triển khai):** Task đủ điều kiện bàn giao khi `Batch` & `Dataset` đều `active`, có ít nhất 1 job, **100% job** ở trạng thái `approved`, **0 job bị khóa** (`is_locked=False`) và **không còn lượt `AuditSample` nào** đang `pending` (`/api/projects/{id}/deliveries/candidates/`).<br>• **Cấp Project (`Dataset` — tổng hợp):** Project sẵn sàng bàn giao hoàn tất khi toàn bộ Task bên trong đã được duyệt/bàn giao. |
| BG02 | Người và đầu ra bàn giao | **PM** (`manage_delivery`) tạo bản ghi `Delivery` cho từng batch, lưu thời điểm (`delivered_at`), người thực hiện (`delivered_by`), người nhận (`recipient`), đường dẫn đầu ra (`output_path`), ghi chú (`note`) và phản hồi khách hàng (`client_feedback`). |
| BG03 | Khóa sau bàn giao | Ngay khi tạo `Delivery`, hệ thống tự chốt mọi `Audit` `in_progress` của Task sang `completed`, chuyển `Batch.status = delivered` và toàn bộ job trong Task sang `JobStatus.DELIVERED`, khóa cứng mọi chỉnh sửa/chuyển trạng thái (`ensure_editable` & `_set_status` chặn thay đổi). |
| BG04 | Lỗi sau bàn giao | PM có thể cập nhật `client_feedback` trên bản ghi `Delivery`. *(Hạng mục cần bổ sung: API mở lại `reopen` batch/job đã `delivered` khi khách hàng reject để chạy lại vòng sửa và theo dõi trên timeline).* |

### 11. Đồng bộ CVAT và vận hành — VH

| Mã | Vấn đề cần thống nhất | Quy định & hiện trạng |
| --- | --- | --- |
| VH01 | Nguồn dữ liệu chuẩn | • **CVAT làm chuẩn:** Cấu trúc `Organization → Project → Task → Job`, dữ liệu annotation (`shapes`/`tracks`/cuboid), số frame (`frame_count`, `cvat_start_frame`), trạng thái gốc CVAT (`cvat_stage`/`cvat_state`).<br>• **VanoHub làm chuẩn:** Workflow trạng thái (nhất là `qc1_passed`, `pending_qc2`, `approved`, `delivered`), phân quyền vai trò chi tiết (`QC2`, `QC1`, `Annotator`) & WIP, deadline, số vòng rework & escalation, `ReviewError`, QC2 `AuditSample`, `Delivery`, KPI và `ActivityLog`. |
| VH02 | Chiều và tốc độ đồng bộ | • **Đọc/đồng bộ từ CVAT → VanoHub:** PM gọi `POST /api/cvat/sync-organizations/` (Organization + vai trò thành viên từ CVAT org), `POST /api/projects/{id}/cvat-sync/` (tùy chọn `count_objects=true`) hoặc cron chạy `python manage.py sync_cvat [--count-objects]`. Lọc chỉ job `type = annotation` (bỏ `ground_truth`/`consensus`), kiểm tra khớp `cvat_org_id` / `cvat_project_id` / `cvat_task_id`, thực hiện toàn bộ HTTP I/O bên ngoài `transaction.atomic()`, đánh dấu `source_missing=True` cục bộ nếu task/job 404 trên CVAT, và cấm HTTP redirect (`allow_redirects=False`). Chỉ đồng bộ trạng thái trong `SYNCABLE_STATUSES` (`annotation` + `qc1` đang mở), tôn trọng `is_locked`, `Batch`/`Dataset` không `active`, `DELIVERED` và `escalation_policy = block`.<br>• **Ghi ra CVAT (giới hạn nghiêm ngặt — `backend/cvat_integration/assignee.py`):** Sau khi liên kết `CvatAccount` (`/api/cvat/link/`), VanoHub chỉ đẩy hai loại thao tác ra CVAT: *(1)* cập nhật **job `assignee`** (`PATCH /api/jobs/{id}` hậu commit qua `schedule_assignee_push` / `push_assignees` theo `current_holder(job)`) và *(2)* gửi **lời mời vào CVAT organization** vai trò `worker` (`POST /api/invitations?org=<slug>` qua `_OrgMembers.ensure`) khi người nhận job chưa thuộc org. Không bao giờ sửa annotation hay đẩy workflow status lên CVAT.<br>• *Mở rộng sau MVP (Backlog):* Webhook / đồng bộ nền và các plugin stub. |
| VH03 | Xung đột | • **Trước QC2:** Khi đồng bộ CVAT, trạng thái ánh xạ từ CVAT (`CVAT_STATUS_MAP`) cập nhật một chiều trong `SYNCABLE_STATUSES` và ghi `ActivityLog` (`"Đồng bộ từ CVAT"` — không bao giờ gán `actor = PM` bấm sync, chỉ dùng `job.annotator` hoặc `None` và lưu `synced_by` vào `after` để bảo vệ luật bốn mắt): `annotation/rejected` & `validation/rejected` đưa về `rework` (tăng `rework_round` + `total_rework_rounds` và kiểm tra escalation); **Hybrid A2:** `POST_QC1_CVAT_STATES` (`validation/completed`, `acceptance/*`) bị chặn ở `qc1_passed` nếu `batch.qc2_confirmed_at is None`, và chỉ vào `pending_qc2` + `ensure_qc2_sample` sau khi PM đã `confirm-qc2`.<br>• Khi bật `count_objects=true`, hệ thống bung toàn bộ track keyframe (xét `outside`, `frame_step`, `deleted_frames`, `included_frames`) và ghi ngay phần chênh lệch dương vào sổ `DailyOutputRecord` (`source="cvat_sync"`) cho `job.annotator`.<br>• **Từ QC2 trở đi (`pending_qc2`, `approved`, `delivered`) & `qc1_passed`:** VanoHub luôn giữ quyền — đồng bộ CVAT không ghi đè hoặc kéo lùi trạng thái.<br>• Ánh xạ tài khoản: qua `CvatAccount` (`GET/POST/DELETE /api/cvat/link/`, xác minh PAT 1 lần qua `/users/self` rồi bỏ token, `cvat_user_id` unique 1-1). Endpoint `/api/cvat/sync-organizations/` giới hạn chỉ PM. |
| VH04 | Mất kết nối | • Endpoint kiểm tra kết nối `GET /api/cvat/status/` (timeout 5s; tải danh sách task 10s; mặc định client 15s).<br>• Khi CVAT không kết nối được hoặc trả lỗi 401/404/5xx, backend trả HTTP `502 Bad Gateway` kèm thông báo dễ hiểu, đồng thời lưu `last_sync_status = "error"`, `last_sync_error` và `last_synced_at` lên Batch.<br>• Người dùng vẫn thao tác bình thường các luồng nội bộ VanoHub và thử đồng bộ lại khi CVAT khôi phục. |
| VH05 | Quy mô và hiệu năng | • API danh sách phân trang chuẩn `page_size = 50` (tối đa `500`), đánh chỉ mục DB trên các truy vấn trọng yếu (`project+status`, `project+created_at`, `recipient+project+is_read`, `project+created_by+status`).<br>• Sử dụng khóa hàng nguyên tử (`select_for_update(of=("self",))` / `skip_locked`) cho `claim`, `start`, `submit`, `qc1`, `confirm-qc2`, `ensure_qc2_sample`, `qc2.pass/reject`, `delivery.create`, `guideline.publish`.<br>• *Cần chốt SLA:* Số người dùng đồng thời tối đa và ngưỡng phản hồi mục tiêu (P95) khi đưa vào sản xuất. |
| VH06 | Triển khai và khôi phục | • **Kiến trúc triển khai:** Backend Django 6 / DRF + SimpleJWT (access token 30 phút, refresh token 1 ngày), Frontend React 19 / TypeScript / Vite 8, CSDL PostgreSQL 17 (`docker-compose.yml`, volume `pgdata`).<br>• Cấu hình bí mật qua `backend/.env` (`DJANGO_SECRET_KEY`, `POSTGRES_*`, `CVAT_URL`, `CVAT_PUBLIC_URL`, `CVAT_ACCESS_TOKEN` hoặc `CVAT_USERNAME/PASSWORD`, `CORS_ALLOWED_ORIGINS`).<br>• *Cần chốt vận hành production:* Lịch sao lưu định kỳ PostgreSQL (`pg_dump` / WAL archiving), mục tiêu RPO/RTO và đơn vị vận hành hạ tầng. |

### 12. Duyệt yêu cầu và nghiệm thu — NT

| Mã | Vấn đề cần thống nhất | Quy định & hiện trạng |
| --- | --- | --- |
| NT01 | Người chốt | **PM** có quyền duyệt và chốt cuối cùng về quy trình, chất lượng, KPI và phân quyền trong phạm vi dự án phụ trách. |
| NT02 | Người kiểm thử | Cử người đại diện đủ 4 vai trò (**PM, QC2, QC1, Annotator**) kiểm thử đầu-cuối trên dữ liệu mẫu và kết nối CVAT thật. |

---

## MA TRẬN PHÂN QUYỀN (RBAC)

> Nguồn thực thi: `backend/accounts/permissions.py` (`CAPABILITY_ROLES`) và `backend/accounts/models.py` (`IMPLIED_ROLES`).  
> **Quy tắc kế thừa:** `PM` tự động có toàn bộ quyền của `QC2` (`PM → QC2`). Chiều ngược lại **không** đúng.  
> **Phạm vi dữ liệu:** Mọi API dự án đều khóa chặt theo `project_id` (`ProjectScopedViewMixin`); người không thuộc dự án nhận `404`.

| Capability / Nhóm thao tác | Mô tả & phạm vi | PM | QC2 | QC1 | Annotator |
| --- | --- | :---: | :---: | :---: | :---: |
| `project.create` / `update` / `pm_ids` | Tạo dự án mới (bất kỳ PM hiện hữu / superuser); sửa thông tin & danh sách PM (PM của dự án) | ✓ | — | — | — |
| `view_project` | Truy cập dự án, xem danh sách thành viên, thông báo cá nhân, danh mục lỗi, cài đặt (chỉ đọc) | ✓ | ✓ | ✓ | ✓ |
| `view_guidelines` | Đọc hướng dẫn gán nhãn và lịch sử phiên bản | ✓ | ✓ | ✓ | ✓ |
| `view_dashboard` | Xem tổng quan dự án, xếp hạng nhóm, hiệu suất thành viên, báo cáo QC1/QC2 toàn dự án | ✓ | — | — | — |
| `view_jobs` | Xem toàn bộ Dataset, Batch, Job và Data Queue cấp dự án | ✓ | — | — | — |
| `manage_data` | Tạo/sửa/khóa Dataset & Batch; đồng bộ CVAT (`cvat-sync`); xác nhận Task chuyển QC2 (`confirm-qc2`) | ✓ | — | — | — |
| `manage_jobs` | Giao/giao lại job, đổi deadline, khóa/mở khóa job, chuyển batch cho job nội bộ (`bulk-move-batch`), gỡ escalation, xử lý `AnnotatorRequest` | ✓ | — | — | — |
| `manage_team` | Tạo thành viên mới (`POST .../members/`), gán/gỡ vai trò (`QC2`, `QC1`, `Annotator`), quản lý team, sức chứa (`capacity`), điều chuyển & xem tải | ✓ | — | — | — |
| `manage_settings` | Chỉnh cấu hình rework, `escalation_policy`, WIP limit, tỷ lệ frame QC2 (`sampling_rate`), ngưỡng chất lượng & chỉ tiêu KPI | ✓ | — | — | — |
| `manage_audits` | Xem đợt `Audit` (chỉ đọc), xem quy tắc & thống kê QC2 (`audit-strategy`), phân lại auditor (`audit-samples/{id}/assign`) | ✓ | — | — | — |
| `perform_audit` | Xem & thực hiện chấm `Pass` / `Reject` kèm lỗi trên các mẫu `AuditSample` được giao *(luật bốn mắt)* | ✓ *(kế thừa QC2)* | ✓ | — | — |
| `manage_quality_catalog` | Tạo/cập nhật/vô hiệu hóa danh mục lỗi (`ErrorCategory`); phát hành phiên bản `Guideline` mới | ✓ | — | — | — |
| `manage_delivery` | Xem danh sách batch sẵn sàng, tạo bản ghi bàn giao (`Delivery`), cập nhật phản hồi khách hàng | ✓ | — | — | — |
| `send_announcement` | Gửi thông báo dự án theo vai trò / nhóm phân bổ | ✓ | — | — | — |
| `view_activity` | Xem nhật ký toàn bộ thao tác dự án (`ActivityLog`, chỉ đọc) | ✓ | — | — | — |
| `perform_qc1` | Xem hàng chờ QC1 (job được giao + pool hợp lệ, trừ job tự annotate), `start`, `pass`, `reject` QC1 | — | — | ✓ | — |
| `annotate_jobs` | Xem job được giao, tự nhận job (`claim` theo WIP), `start`, `submit`, gửi yêu cầu `error_dispute`/`data_issue`, xem dashboard & phân tích cá nhân | — | — | — | ✓ |

---

## MA TRẬN SỰ KIỆN VÀ NGƯỜI NHẬN THÔNG BÁO

> Nguồn thực thi: `backend/projects/notifications.py`, `backend/projects/views.py` (`ProjectNotificationsView`), `backend/jobs/views.py`, `backend/quality/views.py`.

| Nhãn (`category`) | Sự kiện kích hoạt | Người nhận | Ghim chờ xử lý (`TB03`) | Tùy chọn tắt/bật | Điểm đến (`action_url`) |
| --- | --- | --- | :---: | --- | --- |
| `assigned` | PM giao/giao lại Annotator, QC1 hoặc phân auditor QC2 | Người được giao *(trừ chính người thao tác)* | Không | Luôn bật | Job Annotator / Hàng chờ QC1 / Hàng chờ QC2 |
| `review_needed` | • Annotator nộp bài (`submit`)<br>• 100% job trong Task đạt QC1<br>• PM xác nhận chuyển Task sang QC2 (`confirm-qc2`) | • QC1 được giao *(hoặc QC1 cùng team / toàn org nếu ở pool)*<br>• **PM** dự án<br>• **PM & QC2** dự án | **Có** *(QC1 gỡ ghim khi QC1 xử lý; PM `100% QC1` gỡ ghim khi `confirm-qc2`; thông báo `confirm-qc2` cấp Task `job=None` hiện chưa tự gỡ ghim khi hoàn tất `AuditSample`)* | Luôn bật | `/qc1/work` · `/batches` · `/qc2/work` |
| `rework` | • QC1 trả sửa (`qc1.reject`)<br>• QC2 trả sửa (`qc2.reject`) | • **Annotator** của job<br>• **QC1** phụ trách *(khi bị QC2 trả sửa)* | **Có** *(trên Annotator; gỡ ghim khi nộp lại)* | `notify_rework` *(Annotator)* | `/annotator/jobs/{job_id}` · `/qc1/work` |
| `escalated` | Job vượt `max_rework_rounds` (từ QC1 reject, QC2 reject hoặc đồng bộ CVAT) | Toàn bộ **PM** của dự án | **Có** | Luôn bật | `/jobs?escalated=1` |
| `deadline` | Job đang mở sắp đến hạn (`≤ 24h`) hoặc đã quá hạn *(tính động khi tải thông báo)* | Annotator / QC1 / QC2 đang giữ job và **PM** dự án | **Có** | `notify_deadline` | Trang công việc tương ứng theo vai trò |
| `dispute` | • Annotator gửi `error_dispute` hoặc `data_issue`<br>• PM kết luận `resolved` / `rejected` | • **PM** phụ trách + Annotator tạo yêu cầu<br>• Annotator tạo yêu cầu *(khi có kết luận; gỡ ghim yêu cầu cũ)* | **Có** *(khi đang chờ PM)* | `notify_request_updates` *(Annotator)* | `/annotator/requests` |
| `qc_pass` | QC1 duyệt đạt job (`qc1.pass`) | **Annotator** của job | Không | `notify_qc_pass` | `/annotator/jobs/{job_id}` |
| `announcement` | PM gửi thông báo dự án (`Announcement`) | Thành viên thuộc `target_roles` / `target_team` đích *(rỗng = toàn dự án)* | Không | Luôn bật | `/announcements` |

---

## CHI TIẾT CHỈ SỐ CHẤT LƯỢNG CHÍNH (FPY, DEFECT ERROR RATE, QUALITY CL)

### 1. First Pass Yield — FPY tại QC1 (`CL01`)
- **Công thức chuẩn:**
  $$\text{FPY}_{\text{QC1}} = \frac{\text{Số job đạt QC1 ngay lần kiểm đầu}}{\text{Tổng số job đã có kết quả kiểm QC1 lần đầu}} \times 100\%$$
- **Triển khai (`Đã có`):** `Job.first_qc1_result` (`pass` \| `reject`, ghi 1 lần bất biến tại quyết định QC1 đầu tiên — không bị ảnh hưởng khi QC2 trả lại về sau hay khi PM gọi `resolve-escalation`). Mẫu số bao gồm cả job trượt lần đầu vẫn đang ở `REWORK` / `ANNOTATING`. Hiển thị trên `ProjectOverviewView`, `AnnotatorDashboardView` và `Qc1SummaryView`.

### 2. Defect Error Rate — Tỷ lệ đối tượng lỗi (`CL02`)
- **Công thức chuẩn:**
  $$\text{Defect Error Rate} = \frac{\text{Số cuboid (object-frame) duy nhất có verdict = Fail}}{\text{Tổng} = N_{\text{checked}} + N_{\text{missing}}} \times 100\%$$
- **Hiện trạng (`Đang chờ chốt` — `pending_definition`):**
  1. **Hạ tầng đã có:** `CvatClient.count_job_objects()` gọi `/api/jobs/{id}/annotations` kết hợp `/api/jobs/{id}/data/meta` để đếm cuboid/object-frame hợp lệ (bung khoảng frame hoạt động của từng CVAT track theo `frame_step`, trừ `deleted_frames`, giao với `included_frames` nếu có và bỏ `outside=True`); `ReviewError` lưu `frame_number`, `cvat_object_id`, `verdict` (`fail` \| `edge`), `is_missing_object`, `is_voided` (khử trùng theo `(job_id, frame_number, cvat_object_id)`, riêng lỗi thiếu đối tượng khử trùng theo `(frame_number, category_id)`).
  2. **Điểm còn chờ chốt theo QC2 cấp frame:** Khi chuyển QC2 sang **kiểm theo `sampling_rate`% số frame (`AuditSample.frames`)**, cần chốt quy tắc tính $N_{\text{checked}}$ chỉ trên tập frame được QC2 kiểm (thay vì toàn bộ `job.object_count`). Do đó hiện tại `AuditSampleViewSet._finish()` giữ `AuditSample.checked_object_count = None` và `backend/analytics/views.py` (`ProjectOverviewView`, `Qc2SummaryView`) trả về `value = null`, `status = "pending_definition"` cho `defect_error_rate` (`CL02`), `error_percent_in_job`, `defect_rate_by_severity` (`CL05`) và `quality_cl` (`CL11`).

### 3. Quality CL (`CL11`) và phân biệt `Edge` với `AQL`
- **Công thức chuẩn (đã gộp `CL03` vào `CL11`):**
  $$\text{Quality CL} = \frac{\text{Cuboid}_{\text{Pass}} + \text{Cuboid}_{\text{Edge}}}{N_{\text{checked}} + N_{\text{missing}}} \times 100\% = 100\% - \text{Defect Error Rate}$$
- **Hiện trạng (`Đang chờ chốt` — `pending_definition`):** Chờ chốt `AuditSample.checked_object_count` theo danh sách frame QC2 kiểm giống `CL02` (`analytics/views.py` đang trả `status = "pending_definition"`, `value = null`; UI `MetricCard` hiển thị `"—"` kèm nhãn `"Chưa chốt công thức"`).
- **Quy ước đã chốt cho mô hình dữ liệu (`ReviewError` & `Project`):**
  - **`AQL` (Acceptable Quality Limit)** là **ngưỡng chấp nhận ở cấp Project/Task** (`Project.quality_cl_threshold`, `Project.defect_rate_threshold`).
  - **`Edge`** là **phân loại kết luận độc lập** trên `ReviewError.verdict = "edge"` (tách biệt với `severity = minor | major | critical`):
    - Trọng số `Edge` trong tử số `Quality CL` bằng `1.0` (cộng chung với `Pass` để không phạt tỷ lệ chất lượng cho ca cận biên / rìa FOV).
    - `Edge` **không** tính vào tử số `Fail` của `Defect Error Rate (CL02)` nhưng vẫn được lưu để theo dõi riêng qua cột phụ `Edge %` và bổ sung guideline.
    - `CL03` gộp vào `CL11` (Pass thuần không gồm Edge: $(N_{\text{checked}} - \text{Fail} - \text{Edge}) \div (N_{\text{checked}} + N_{\text{missing}})$).

---

## TỔNG HỢP CÔNG THỨC TÍNH TOÁN TRONG PLATFORM

> **Ký hiệu trạng thái triển khai:** `Đã có` (đang chạy đúng nghiệp vụ) · `Tạm tính` (đang chạy công thức provisional) · `Chờ chốt` (`pending_definition`) · `Chưa làm` (chưa triển khai trong codebase).

| Mã | Chỉ số | Công thức / quy tắc tính | PM | QC2 | QC1 | Anno | Cách trình bày | Mức | Hiện trạng |
| --- | --- | --- | :---: | :---: | :---: | :---: | --- | :---: | --- |
| **SL01** | Sản lượng Anno lần đầu | Tổng cuboid 3D / object 2D làm được theo ngày ở vòng đầu (`is_rework=False`) trên `DailyOutputRecord` (`source="submit"\|"cvat_sync"`) — tính cả khi chưa QC và giữ nguyên sau QC | ✓ | — | — | ✓ | Thẻ số; biểu đồ cột theo ngày | P1 | Đã có |
| **SL02** | Sản lượng QC | Số lượt hoàn tất kiểm job hợp lệ (`qc1.pass/reject` theo `actor`, `qc2 pass/reject` theo `reviewed_by` — không tính cover hộ); tách QC1/QC2 | ✓ | ✓ | ✓ | — | Thẻ thực tế/chỉ tiêu; cột phân nhóm | P1 | Đã có *(chưa tách kiểm đầu/lại)* |
| **SL03** | Sản lượng rework Anno | Tổng cuboid 3D / object 2D thực làm theo ngày ở vòng sửa (`is_rework=True`) trên `DailyOutputRecord` (`partial` tính lỗi duy nhất vòng hiện tại + delta tăng thêm; `full` tính theo vòng làm lại) | ✓ | — | — | ✓ | Phần rework trong cột sản lượng | P1 | Đã có |
| **SL04** | Sản lượng theo người thực hiện | Tổng sản lượng ghi nhận theo đúng `actor` (`DailyOutputRecord.user` / `reviewed_by`); giao lại không chuyển sản lượng cũ, không tính cover hộ | ✓ | ✓ | ✓ | ✓ | Bảng chi tiết người–job–vòng xử lý | P1 | Đã có |
| **SL05** | Sản lượng dự án / nhóm | Tổng sản lượng thành viên trong phạm vi từ `DailyOutputRecord`, tách từng vai trò và đơn vị | ✓ | — | — | — | Cột theo ngày / nhóm phân bổ; bộ lọc vai trò | P1 | Đã có *(Anno & Team)* |
| **SL06** | Tổng sản lượng tính KPI Anno | `SL01 + SL03` trên `DailyOutputRecord` trong ngày/kỳ theo múi giờ nghiệp vụ (`Asia/Ho_Chi_Minh`) | ✓ | — | — | ✓ | Thẻ KPI chính; bấm xem phần đóng góp | P1 | Đã có |
| **KPI01** | Chỉ tiêu trong kỳ | Chỉ tiêu cấu hình trên `Project` (`kpi_*_target`: cuboid/object cho Anno; job cho QC1/QC2) | ✓ | ✓ | ✓ | ✓ | Đường mục tiêu trên biểu đồ; thông tin kỳ | P1 | Đã có *(chưa có lịch sử đổi giữa kỳ)* |
| **KPI02** | Tỷ lệ đạt KPI *(đã gộp KPI07)* | Sản lượng đủ điều kiện ÷ chỉ tiêu cùng kỳ × 100% (chỉ tính khối lượng cuboid 3D / object 2D / job, không liên quan tiền bạc) | ✓ | ✓ | ✓ | ✓ | Thẻ % + thực tế/chỉ tiêu; thanh tiến độ | P1 | Đã có |
| **KPI03** | Sản lượng còn thiếu | `max(0, chỉ tiêu − sản lượng thực tế)` | ✓ | ✓ | ✓ | ✓ | Số phụ trong thẻ KPI | P1 | Đã có |
| **KPI04** | Sản lượng vượt chỉ tiêu | `max(0, sản lượng thực tế − chỉ tiêu)` | ✓ | ✓ | ✓ | ✓ | Số phụ khi đã đạt KPI | P1 | Đã có |
| **KPI05** | Tỷ lệ thành viên đạt KPI | Thành viên đạt chỉ tiêu ÷ thành viên đủ điều kiện đánh giá × 100% | ✓ | — | — | — | Thẻ % + số người đạt/tổng | P1 | Chưa làm |
| **KPI06** | Thành viên dưới ngưỡng KPI | Thành viên dưới ngưỡng X ÷ thành viên được đánh giá × 100%; đề xuất X = 50% | ✓ | — | — | — | Danh sách cần hỗ trợ + số đếm | P1 | Chưa làm |
| **KPI07** | *(Gộp vào KPI02)* | Đã gộp vào `KPI02` (khối lượng cuboid 3D / object 2D / job theo `Project.kpi_*_target`; không có nghiệp vụ tiền bạc/khoán riêng trong MVP) | — | — | — | — | Gộp chung trong `KPI02` | — | Gộp vào KPI02 |
| **KPI08** | Chênh lệch hai kỳ | Giá trị kỳ này − giá trị kỳ trước (`kpi.comparison.*.delta`) | ✓ | ✓ | ✓ | ✓ | Số tăng/giảm cạnh chỉ số chính | P1 | Đã có *(QC1/QC2)* |
| **KPI09** | Tỷ lệ tăng/giảm hai kỳ | `(Kỳ này − kỳ trước) ÷ kỳ trước × 100%` (`kpi.comparison.*.pct_change`); kỳ trước = 0 thì trả `null` | ✓ | ✓ | ✓ | ✓ | Nhãn tăng/giảm, ghi rõ kỳ so sánh | P1 | Đã có *(QC1/QC2)* |
| **KPI10** | Xếp hạng sản lượng | Sắp giảm dần theo sản lượng `DailyOutputRecord` cùng kỳ trong cùng vai trò & dự án; cá nhân chỉ thấy hạng mình | ✓ | ✓ | ✓ | ✓ | PM xem bảng; cá nhân chỉ thấy hạng mình | P2 | Đã có *(Anno & Team)* |
| **KPI11** | Chỉ tiêu dự án / nhóm | Tổng chỉ tiêu thành viên trong phạm vi, cùng đơn vị và kỳ | ✓ | — | — | — | Đường chỉ tiêu cạnh SL05 | P1 | Chưa làm |
| **NS01** | Thời gian làm thực tế | Tổng thời lượng phiên làm hợp lệ (`ANNOTATING → PENDING_QC1` lọc theo đúng `actor`) | ✓ | ✓ | ✓ | ✓ | Thẻ giờ trong tab năng suất | P2 | Tạm tính *(Anno)* |
| **NS02** | Thời gian chờ/tạm dừng | Tổng thời lượng chờ/tạm dừng đã ghi nhận, phân theo nguyên nhân | ✓ | ✓ | ✓ | ✓ | Thanh ngang theo nguyên nhân; timeline job | P2 | Chưa làm |
| **NS03** | Năng suất Anno | Sản lượng Anno hợp lệ ÷ giờ làm thực tế; tách riêng giờ làm đầu (`first_pass_per_hour`) và giờ rework (`rework_per_hour`) | ✓ | — | — | ✓ | Đường xu hướng object-frame/giờ | P2 | Tạm tính |
| **NS04** | Năng suất QC | Lượt kiểm job hoàn tất ÷ giờ kiểm thực tế; tách kiểm đầu/kiểm lại | ✓ | ✓ | ✓ | — | Đường xu hướng job/giờ | P2 | Chờ chốt |
| **NS05** | Thời gian trung bình/đơn vị | Giờ làm thực tế ÷ số đơn vị hoàn thành tương ứng | ✓ | ✓ | ✓ | ✓ | Thẻ phụ; bảng theo loại công việc | P2 | Chưa làm |
| **NS06** | Sản lượng trung bình/ngày công | Tổng sản lượng ÷ số ngày công có hoạt động | ✓ | ✓ | ✓ | ✓ | Thẻ trung bình trong tab năng suất | P1 | Đã có *(Anno)* |
| **NS07** | Thời gian chờ giữa hai bước | Thời điểm bắt đầu bước sau − thời điểm sẵn sàng chuyển bước | ✓ | ✓ | ✓ | ✓ | Thanh ngang trung vị theo bước; danh sách chờ lâu | P1 | Chưa làm |
| **NS08** | Thời gian hoàn tất toàn luồng | Thời điểm PM chấp nhận − thời điểm lần đầu giao Anno | ✓ | — | — | — | Xu hướng trung vị theo kỳ; chi tiết từng job | P1 | Chưa làm |
| **NS09** | Tỷ lệ công QA / Annotation *(đề xuất)* | Tổng giờ (hoặc ngày công) QC1 + QC2 ÷ tổng giờ (hoặc ngày công) Annotation trong kỳ (`qa_to_annotation_ratio`); `≥ 1.0` cảnh báo nghẽn QA (`QA days > Annotation days`) | ✓ | ✓ | — | — | Thẻ tỷ lệ + xu hướng theo batch/kỳ | P2 | Chờ chốt |
| **NS10** | End-to-End Throughput *(đề xuất Phase 2)* | `approved_cuboids / (annotation_days + qa_days)` ở cấp Task/Project để đo thông lượng toàn quy trình và phát hiện nghẽn `qa_days > annotation_days` (không phạt cá nhân) | ✓ | — | — | — | Thẻ thông lượng + xu hướng cấp Task/Project | P2 | Chờ chốt *(Đề xuất Phase 2)* |
| **CL01** | FPY tại QC1 | Job Pass ở lần QC1 đầu ÷ job có kết quả QC1 đầu × 100% (`Job.first_qc1_result`) | ✓ | — | ✓ | ✓ | Thẻ % + đạt/tổng; đường xu hướng tuần | P1 | Đã có |
| **CL02** | Tỷ lệ đối tượng lỗi (Defect Error Rate) | Cuboid duy nhất có `verdict=fail` (không void) ÷ `(N_checked + N_missing)` × 100% | ✓ | ✓ | ✓ | — | Thẻ % có cỡ mẫu (`MetricCard` hiện `"Chưa chốt công thức"`) | P1 | Chờ chốt *(`pending_definition` chờ `checked_object_count` theo frame QC2)* |
| **CL03** | *(Gộp vào CL11)* | Đã gộp vào `CL11` (Pass thuần = `(N_checked - Fail - Edge) ÷ (N_checked + N_missing)` nếu cần tách riêng) | — | — | — | — | Gộp chung trong `CL11` | — | Gộp vào CL11 |
| **CL04** | Số lỗi theo loại/mức độ | Đếm `ReviewError` (`is_voided=False`) theo loại lỗi (`errors_by_category`) và mức độ (`errors_by_severity`) | ✓ | ✓ | ✓ | ✓ | Thanh ngang top lỗi; Anno xem lỗi trên job mình | P1 | Đã có |
| **CL05** | Tỷ lệ đối tượng lỗi theo mức độ | Cuboid `verdict=fail` theo mức nặng nhất `minor`/`major`/`critical` ÷ `(N_checked + N_missing)` × 100% | ✓ | ✓ | ✓ | — | Phân bố theo mức độ | P1 | Chờ chốt *(`pending_definition` chờ `checked_object_count` theo frame QC2)* |
| **CL06** | Số lỗi QC1 bỏ sót | Đếm lỗi QC2 (`is_voided=False`, `verdict=fail`) xác nhận trên job đã qua QC1 (`qc1_missed_errors` / `qc2_escape_errors`) | ✓ | ✓ | ✓ | — | Thẻ số + bảng bằng chứng | P1 | Đã có |
| **CL07** | Tỷ lệ job có lỗi QC1 bỏ sót | Job audit có lỗi QC1 bỏ sót ÷ job đã audit thuộc trách nhiệm QC1 đó × 100% (`qc1_escape_job_rate`) | ✓ | ✓ | ✓ | — | Thẻ % + số job lỗi/số job audit | P1 | Đã có |
| **CL08** | Tỷ lệ lỗi QC2 bỏ sót | Object-frame có lỗi QC2 bỏ sót xác nhận ÷ object-frame tái kiểm × 100% | ✓ | ✓ | — | — | Thẻ % + bảng kết luận tái kiểm độc lập | P2 | Chưa làm |
| **CL09** | Tỷ lệ kết luận lỗi bị hủy | `error_dispute` có `status=resolved` ÷ (`resolved` + `rejected`) × 100% (`dispute_overturn_rate`) | ✓ | ✓ | ✓ | — | Bảng phân xử; chỉ số phụ | P2 | Đã có |
| **CL10** | Batch được chấp nhận lần đầu | Batch được PM `accept` ở đợt audit đầu ÷ batch có đợt audit đầu đã chốt × 100% | ✓ | ✓ | — | — | Thẻ % + đường xu hướng | P1 | Chưa làm *(hoặc N/A theo mô hình frame QC2)* |
| **CL11** | Quality CL *(đã gộp CL03)* | `(Cuboid Pass + Cuboid Edge) ÷ (N_checked + N_missing) × 100% = 100% − CL02` (`verdict=edge` độc lập + cột phụ `Edge %`); *giả định phân mức 3 cấp chờ chốt:* Xanh `≥ 95%`, Vàng `90%–<95%`, Đỏ `< 90%` | ✓ | ✓ | ✓ | ✓ | Thẻ % kèm cỡ mẫu, cột `Edge %` & nhãn màu 3 mức | P1 | Chờ chốt *(`pending_definition` chờ `checked_object_count` theo frame QC2)* |
| **CL12** | Điều kiện đạt/chặn chất lượng | Áp ngưỡng dự án; lỗi nghiêm trọng chưa xử lý thì chặn chấp nhận/bàn giao | ✓ | ✓ | ✓ | ✓ | Nhãn Đạt/Chưa đạt + lý do chặn | P1 | Chưa làm |
| **CL13** | FPY toàn luồng | Job được PM chấp nhận không qua rework ÷ job đã được PM chấp nhận × 100% | ✓ | — | — | — | Thẻ phụ có số job còn mở; không thay CL01 | P2 | Chưa làm |
| **RW01** | Số vòng rework | Đếm quyết định trả về `rework` (`Job.rework_round` hiện tại & `Job.total_rework_rounds` bất biến) | ✓ | ✓ | ✓ | ✓ | Nhãn số vòng trên job + timeline | P1 | Đã có |
| **RW02** | Tỷ lệ job bị rework | Job duy nhất có `total_rework_rounds > 0` ÷ tổng job trong nhóm đánh giá × 100% | ✓ | ✓ | ✓ | ✓ | Thẻ % + xu hướng; lọc ra danh sách job | P1 | Đã có |
| **RW03** | Lượt trả trung bình/job | Tổng lượt trả sửa ÷ số job trong nhóm đánh giá | ✓ | ✓ | ✓ | ✓ | Chỉ số phụ, đơn vị lượt/job | P1 | Chưa làm |
| **RW04** | Khối lượng đang chờ sửa | Tổng `ReviewError` chưa void thuộc vòng rework hiện tại trên job đang ở `rework` | ✓ | ✓ | ✓ | ✓ | Thẻ khối lượng + danh sách sửa | P1 | Đã có |
| **RW05** | Thời gian một vòng sửa | Thời điểm nộp lại − thời điểm trả sửa | ✓ | ✓ | ✓ | ✓ | Timeline từng vòng | P1 | Chưa làm |
| **RW06** | Thời gian sửa trung bình | Tổng thời gian vòng sửa hoàn tất ÷ số vòng sửa hoàn tất | ✓ | ✓ | ✓ | ✓ | Thẻ phụ + xu hướng | P1 | Chưa làm |
| **RW07** | Vượt giới hạn rework | `rework_round > max_rework_rounds` → `is_escalated = True`, báo PM (`block` hoặc `warn_only`) | ✓ | ✓ | ✓ | ✓ | Thẻ số job vượt vòng + danh sách ưu tiên | P1 | Đã có |
| **AU01** | Cỡ mẫu QC2 *(cấp frame)* | Mỗi job vào `pending_qc2` lấy ngẫu nhiên cố định theo `(job.pk, rework_round)`: $k = \min(F, \max(1, \lceil F \cdot r / 100 \rceil))$ frame ($F = \max(\text{frame\_count}, 1)$, $r = \text{sampling\_rate}$%, mặc định `20%`) | ✓ | ✓ | — | — | Số frame kiểm / tổng frame trong `AuditSample` và `AuditStrategyPage` | P1 | Đã có *(cấp frame)* |
| **AU02** | Tỷ lệ lấy mẫu thực tế *(cấp frame)* | `len(sample.frames) ÷ job.frame_count × 100%` trên từng lượt `AuditSample` | ✓ | ✓ | — | — | Nhãn `frames.length / frame_count` trên QC2 Work & Audits | P1 | Đã có *(cấp frame)* |
| **AU03** | Tiến độ audit | Mẫu đã có kết quả ÷ tổng mẫu của đợt audit × 100% | ✓ | ✓ | — | — | Thanh phân đoạn đạt/không đạt/chưa kiểm | P1 | Đã có |
| **AU04** | Mẫu còn chờ | Tổng mẫu phải kiểm − mẫu đã có kết quả (`pending`) | ✓ | ✓ | — | — | Thẻ số + danh sách mẫu chưa kiểm | P1 | Đã có |
| **AU05** | Tỷ lệ mẫu đạt | Mẫu `Pass` ÷ mẫu đã có kết quả × 100% (`qc2_pass_rate`) | ✓ | ✓ | — | — | Chỉ số phụ, luôn hiển thị cùng AU03 | P1 | Đã có |
| **AU06** | Tỷ lệ audit đạt | Audit chốt đạt lần đầu ÷ tổng audit đã chốt × 100% *(không còn dùng cơ chế `Audit.complete` accept/reject rời)* | ✓ | ✓ | — | — | Thẻ % theo kỳ + xu hướng | P1 | Chưa làm *(N/A theo mô hình mới)* |
| **AU07** | Chốt đợt audit / bàn giao | `Audit` tự tạo khi có job vào `pending_qc2`, QC2 chấm `Pass`/`Reject` từng job, và tự chuyển `completed` khi PM ghi nhận `Delivery` (`100% approved`, 0 mẫu `pending`) | ✓ | ✓ | — | — | Trạng thái đợt `Audit` trên `AuditsPage` & `DeliveryPage` | P1 | Đã có |
| **TD01** | Khối lượng được giao | Đếm job; cộng `frame_count` / `object_count` / `target_object_count` (tính trên toàn bộ job đang giữ, không cắt top 10) | ✓ | ✓ | ✓ | ✓ | Thẻ số + bảng công việc | P1 | Đã có |
| **TD02** | Số job theo trạng thái | Đếm job hiện tại ở từng `JobStatus` và theo stage (`JobQueueView`) | ✓ | ✓ | ✓ | ✓ | Thẻ số / thanh phân bố; bấm mở hàng đợi | P1 | Đã có |
| **TD03** | Tiến độ Anno trong job | `object_count ÷ target_object_count × 100%` (hoặc `100%` khi đã nộp) | ✓ | — | ✓ | ✓ | Thanh tiến độ trên dòng job | P1 | Đã có |
| **TD04** | Tiến độ QC trong job | Đơn vị đã kiểm ÷ đơn vị phải kiểm × 100% | ✓ | ✓ | ✓ | — | Thanh tiến độ; QC2 dùng phạm vi mẫu | P1 | Chưa làm *(cấp đơn vị trong job)* |
| **TD05** | Tiến độ qua từng bước | Tỷ lệ tích lũy job đã qua từng mốc (`stage_progress`: Anno nộp, đạt QC1, đạt QC2) ÷ tổng job × 100% | ✓ | ✓ | ✓ | ✓ | Các thanh tiến độ Anno/QC1/QC2/PM | P1 | Đã có |
| **TD06** | Tiến độ toàn luồng | Job `approved` + `delivered` ÷ tổng job × 100% | ✓ | — | — | — | Thẻ % + hoàn tất/tổng; bảng batch/dự án | P1 | Đã có |
| **TD07** | Khối lượng còn lại | `total_jobs − done_jobs` (`remaining_jobs`) | ✓ | ✓ | ✓ | ✓ | Số phụ cạnh tiến độ; danh sách việc còn lại | P1 | Đã có |
| **TD08** | Tỷ lệ sẵn sàng bàn giao | Batch đủ điều kiện giao (`candidates.ready`, dùng `Count(..., distinct=True)`) + đã giao ÷ tổng batch × 100% | ✓ | ✓ | — | — | Thanh tiến độ + danh sách batch sẵn sàng giao | P1 | Đã có *(cấp batch)* |
| **TD09** | Tỷ lệ đã bàn giao | Batch đã `delivered` ÷ tổng batch × 100% (`delivered_rate`) | ✓ | — | — | — | Thẻ % + lịch sử bàn giao | P1 | Đã có *(cấp batch)* |
| **TD10** | Tải công việc hiện tại | Số job đang giữ đúng vai trò (`holding` = active Anno, `qc1_holding` = `pending_qc1`/`qc1_reviewing`), `due_soon`, `overdue`, `escalated` | ✓ | ✓ | ✓ | ✓ | Bảng tải thành viên: đang làm, sắp hạn, bị chặn | P1 | Đã có |
| **TD11** | Số người đang có việc | Hợp nhất số người duy nhất đang giữ việc mở trên cả 3 vai trò (`Anno` + `QC1` + `QC2`) (`active_members`) | ✓ | — | — | — | Thẻ số; không gắn nhãn “đang online” | P1 | Đã có |
| **TD12** | Tiền xử lý/lên CVAT | Frame đã tiền xử lý hoặc đã lên CVAT ÷ tổng frame tương ứng × 100% | ✓ | — | — | — | Hai thanh riêng trên dataset | P1 | Chưa làm |
| **TD13** | Việc cần quyết định/xử lý | Đếm yêu cầu mở (`pending_decisions`): batch chờ `confirm-qc2`, audit chờ chốt, `AnnotatorRequest`, job escalated | ✓ | ✓ | ✓ | ✓ | Hộp việc cần xử lý; cá nhân thấy yêu cầu mình gửi | P1 | Đã có |
| **DH01** | Deadline hiệu lực | Mốc giờ `deadline` trên Batch / Job kèm lịch sử điều chỉnh trong `ActivityLog` | ✓ | ✓ | ✓ | ✓ | Cột deadline + lịch sử điều chỉnh | P1 | Đã có |
| **DH02** | Thời gian còn lại | `deadline − hiện tại` trên job đang mở (`hours_remaining`; trả `null` khi job đã đóng) | ✓ | ✓ | ✓ | ✓ | Nhãn “Còn … giờ/ngày” trên công việc | P1 | Đã có |
| **DH03** | Thời gian quá hạn | Chưa xong: `max(0, hiện tại − hạn)`; đã xong: `max(0, hoàn tất − hạn)` (`overdue_hours`) | ✓ | ✓ | ✓ | ✓ | Nhãn đỏ + danh sách quá hạn (`overdue=1`) | P1 | Đã có |
| **DH04** | Sắp đến hạn | `0 ≤ thời gian còn lại ≤ 24 giờ` trên job đang mở (`due_soon=1`, không tính nhầm job đã quá hạn) | ✓ | ✓ | ✓ | ✓ | Nhãn cảnh báo + bộ lọc sắp hạn | P1 | Đã có |
| **DH05** | Kết quả đúng hạn | Thời điểm nộp/hoàn tất `≤ deadline` (`is_on_time`) | ✓ | ✓ | ✓ | ✓ | Nhãn Đúng hạn/Trễ | P1 | Đã có |
| **DH06** | Tỷ lệ hoàn tất bước đúng hạn | Lượt nộp đúng hạn ÷ tổng lượt nộp có deadline × 100% (`on_time_pct`, tính trên lịch sử nộp) | ✓ | ✓ | ✓ | ✓ | Thẻ % + đúng hạn/tổng; xu hướng | P1 | Đã có *(Anno)* |
| **DH07** | Tỷ lệ bàn giao đúng hạn | Batch/Dataset giao đúng hạn ÷ đơn vị đến hạn trong kỳ × 100% | ✓ | — | — | — | Thẻ %; danh sách đến hạn chưa giao | P1 | Chưa làm |
| **DB01** | Tốc độ hoàn tất gần đây | Job hoàn tất hợp lệ trong 14 ngày ÷ số ngày làm việc | ✓ | — | — | — | Chỉ số cơ sở trong chi tiết dự báo | P2 | Chưa làm |
| **DB02** | Thời gian dự kiến còn lại | Khối lượng còn lại ÷ tốc độ nhóm việc tương đồng | ✓ | ✓ | ✓ | ✓ | Số ngày/giờ dự kiến, ghi rõ ước tính | P2 | Chờ chốt |
| **DB03** | Thời điểm dự kiến hoàn tất — ETA | Hiện tại + thời gian dự kiến còn lại theo lịch làm việc | ✓ | ✓ | ✓ | ✓ | Cột ETA cạnh deadline | P2 | Chờ chốt |
| **DB04** | Độ trễ dự kiến | `max(0, ETA − deadline)` | ✓ | ✓ | ✓ | ✓ | Cột “Trễ dự kiến” | P2 | Chờ chốt |
| **DB05** | Sản lượng dự báo | Sản lượng trung bình/ngày công × ngày công còn lại trong tuần | ✓ | ✓ | ✓ | ✓ | Đường dự báo nét đứt, tách số liệu thật | P2 | Đã có *(Anno)* |
| **DB06** | Thứ tự công việc tiếp theo | Quá hạn → sắp hạn (`≤ 24h`) → rework → còn lại; deadline sớm trước | ✓ | ✓ | ✓ | ✓ | Hàng đợi ưu tiên + nút “Tiếp tục làm” | P1 | Đã có |
| **DA01** | Dự án đang chạy | Đếm dự án PM phụ trách đang hoạt động | ✓ | — | — | — | Thẻ số + danh sách dự án (`/projects`) | P1 | Đã có |
| **DA02** | Dự án có nguy cơ trễ | Đếm dự án chưa hoàn tất có ETA vượt deadline dự án | ✓ | — | — | — | Thẻ cảnh báo + bảng ETA/hạn | P2 | Chưa làm |
| **DA03** | Dự án quá hạn | Đếm dự án chưa hoàn tất và vượt deadline dự án | ✓ | — | — | — | Thẻ số đỏ + danh sách dự án phụ trách | P1 | Chưa làm *(chưa có `Project.deadline`)* |

---

## Bố cục trang dashboard

| Vai trò | Khu vực dashboard | Thông tin cần hiển thị | Mã chỉ số | Cách trình bày | Mức |
| --- | --- | --- | --- | --- | :---: |
| **PM** | Chỉ số đầu trang | Tiến độ dự án; việc/batch chờ duyệt; công việc quá hạn; tỷ lệ sẵn sàng bàn giao | TD06, TD13, DH03, TD08 | **4 thẻ**; bấm để mở danh sách tương ứng | P1 |
| PM | Hàng chờ quyết định & xử lý | Task chờ xác nhận chuyển QC2 (`confirm-qc2`), lượt `AuditSample` chờ chấm, phản hồi lỗi & dữ liệu bị chặn (`AnnotatorRequest`), job vượt vòng rework (`escalated`) | TD13, TD05, AU07, CL12, RW07 | **Bảng thao tác ưu tiên**, có tiến độ QC1/QC2, thời gian chờ và nút xử lý | P1 |
| PM | Điều phối & phân công nhân sự | Job theo bước (`JobQueue`), người đang giữ job, tải/sức chứa, deadline, KPI và sản lượng thành viên | TD02, TD10, TD01, DH01, SL05, KPI02, KPI03, KPI11 | **Bảng tải thành viên + thanh phân bố trạng thái**; thao tác giao/giao lại & đổi hạn | P1 |
| PM | Chất lượng dự án | FPY QC1, tỷ lệ đối tượng lỗi (Defect Error Rate), Quality CL, cột phụ `Edge %`, tỷ lệ job rework, top lỗi phổ biến, job vượt vòng sửa | CL01, CL02, CL11, CL04, RW02, RW07 | **Thẻ % + thanh ngang top lỗi + danh sách rework** | P1 |
| PM | Bàn giao | Batch sẵn sàng giao (`candidates`), lịch sử đã giao (`Delivery`), người nhận, đường dẫn đầu ra, phản hồi khách hàng | TD08, TD09, DH07 | **Bảng bàn giao** có trạng thái sẵn sàng, deadline và nút ghi nhận bàn giao | P1 |
| PM | Dự báo & phân tích năng suất | ETA, thời gian còn lại, độ trễ dự kiến, thời gian chờ giữa các bước, tốc độ Anno/QC, **End-to-End Throughput (`NS10`)**, tổng quan các dự án phụ trách | DB02, DB03, DB04, NS07, NS03, NS04, NS10, RW06, DA01, DA02, DA03 | **Các cột dự báo trong bảng tiến độ** (ghi rõ “Ước tính”) + **tab phân tích năng suất** | P2 |
| **QC2** | Chỉ số đầu trang | Audit đang làm; mẫu còn chờ; lỗi nghiêm trọng còn mở; sản lượng/chỉ tiêu | TD13, AU04, CL12, SL02, KPI02 | **4 thẻ**, lỗi nghiêm trọng có màu cảnh báo | P1 |
| QC2 | Audit đang thực hiện | Danh sách job mẫu được giao, tỷ lệ frame kiểm (`frames.length / frame_count`), số đạt/không đạt/chưa kiểm, deadline, nút mở CVAT đúng frame | AU01, AU02, AU03, AU05, DH01 | **Bảng audit + thanh tiến độ phân đoạn**, chấm Pass/Reject kèm `ReviewError` | P1 |
| QC2 | Chất lượng mẫu kiểm | Tỷ lệ đối tượng lỗi, phân bố loại/mức độ lỗi, lỗi QC1 bỏ sót | CL02, CL04, CL05, CL06 | **Thẻ % kèm cỡ mẫu + thanh ngang loại lỗi** | P1 |
| QC2 | Bàn giao kết quả cho PM | Đợt audit theo Task: tiến độ các lượt mẫu đã chấm và trạng thái tự chốt khi Task `delivered` | AU07, TD13 | **Danh sách đợt audit**, hiển thị tiến độ và thời điểm chốt | P1 |
| QC2 | Phân tích cá nhân | Năng suất, so sánh 2 kỳ, xu hướng theo ngày, lỗi bỏ sót qua tái kiểm độc lập | NS04, KPI08, KPI09, DH06, CL08 | **Tab phân tích:** thẻ kỳ này/kỳ trước, biểu đồ xu hướng | P2 |
| **QC1** | Chỉ số đầu trang | Job chờ kiểm; job đang kiểm; sản lượng/chỉ tiêu; tỷ lệ đạt QC1 | TD02, SL02, KPI02, DH06 | **4 thẻ**, tách hàng chờ của tôi và pool chung | P1 |
| QC1 | Hàng đợi chính | Job cần kiểm tiếp (sắp theo DB06), khối lượng, vòng sửa, deadline, mức ưu tiên | TD01, RW01, DH02, DH04, DB06 | **Bảng hàng đợi ưu tiên**, nút mở đúng job trên CVAT và panel chấm QC1 | P1 |
| QC1 | Phản hồi chất lượng kiểm | Lỗi QC1 bỏ sót do QC2 phát hiện (`qc2_escape_errors`) và tỷ lệ job audit có lỗi bỏ sót | CL06, CL07 | **Thẻ số/% + bảng bằng chứng**, liên kết job đã duyệt | P1 |
| QC1 | Phân tích cá nhân | So sánh 2 kỳ, xu hướng kiểm theo ngày, top loại lỗi ghi nhận, FPY nhóm job đã kiểm | NS04, KPI08, KPI09, CL04, CL01 | **Biểu đồ xu hướng**; ghi rõ FPY phản ánh đầu ra Anno | P2 |
| **Anno** | Chỉ số đầu trang | Sản lượng hôm nay/chỉ tiêu (còn thiếu/vượt); job cần sửa; sắp/quá hạn; FPY cá nhân | SL06, KPI02, KPI03, KPI04, TD02, CL01 | **4 thẻ**; phần thiếu/vượt gộp trong thẻ KPI | P1 |
| Anno | Công việc chính | Job cần làm tiếp (DB06), tiến độ, WIP hiện tại, deadline, nút nhận thêm job (`claim`) & mở CVAT | TD03, TD10, DH02, DH04, DB06 | **Danh sách job + nút “Tiếp tục làm”**, cảnh báo hạn trên từng dòng | P1 |
| Anno | Việc cần sửa | Loại lỗi, vị trí frame/object cần sửa, phạm vi sửa (`partial`/`full`), vòng rework, khối lượng còn lại | CL04, RW01, RW04 | **Danh sách lỗi có vị trí cụ thể**, nút gửi `error_dispute` và mở job trên CVAT | P1 |
| Anno | Kết quả theo ngày | Sản lượng lần đầu/rework 7 ngày gần nhất so với đường chỉ tiêu; tỷ lệ nộp đúng hạn | SL01, SL03, KPI01, DH06 | **Cột chồng lần đầu/rework + đường chỉ tiêu**; thẻ đúng hạn nhỏ | P1 |
| Anno | Yêu cầu đang chờ | Phản hồi lỗi (`error_dispute`), dữ liệu bị chặn (`data_issue`), PM xử lý và kết luận | TD13 | **Danh sách trạng thái yêu cầu** (`/annotator/requests`) | P1 |
| Anno | Phân tích cá nhân | Năng suất (`object/giờ`), dự báo sản lượng tuần, thứ hạng cá nhân (ẩn điểm người khác) | NS01, NS03, DB05, KPI10 | **Trang riêng** (`/annotator/analytics`), đường dự báo nét đứt và hạng cá nhân | P2 |

---

## ĐỀ XUẤT THIẾT KẾ — DỮ LIỆU PRE-LABEL 3D, CHÍNH SÁCH GUIDELINE, ĐÁNH GIÁ 2 TRỤC & THROUGHPUT (CHỜ CHỐT)

> **Trạng thái:** **Đề xuất / Giả định tham khảo từ mentor và các hạng mục analytics đã duyệt định hướng (chưa triển khai code).**
>
> Mục tiêu của mục này là làm tài liệu tham khảo để PM/Mentor chốt chi tiết trước khi viết migration và backend; toàn bộ ngưỡng & chính sách được thiết kế **cấu hình được** theo `Project` / `Guideline`, không hardcode cứng.

### 1. Bối cảnh thực tế & vấn đề cần giải quyết
- **Dữ liệu pre-label sẵn trên `cvat-base`:** Job 3D LiDAR nhập từ CVAT thường đã có sẵn cuboid/track do AI pre-label tạo ra. Công việc thực tế của Annotator gồm 4 phần: *(a)* kiểm tra & giữ nguyên box đúng sẵn, *(b)* chỉnh sửa box lệch, *(c)* bật `outside=True` cho box AI sai (không xóa track để tránh hỏng nội suy 3D), và *(d)* vẽ thêm box AI bỏ sót.
- **Lỗ hổng của cơ chế đếm hiện tại:**
  1. `cvat-sync` chưa lưu mốc pre-label ban đầu (`S0`) → lần chạy `cvat-sync` (`count_objects=true`) đầu tiên sẽ tính toàn bộ cuboid pre-label có sẵn thành sản lượng của Annotator dù chưa thao tác.
  2. `POST /submit/` hiện vẫn cho phép Annotator gửi `object_count` nhập tay kể cả trên job gắn `cvat_job_id` → rủi ro sai lệch sản lượng `SL01`/`SL06` và làm phồng mẫu số khiến Accuracy (`CL02`/`CL05`/`CL11`) đẹp giả tạo.
- **Tỷ lệ thời gian QA vs Annotation:** Thực tế vận hành thường có xu hướng **`QA days > Annotation days`** khi trình độ Annotator chưa đồng đều (làm ẩu gây nhiều vòng rework và bóp nghẽn QC1).
- **Lý do KHÔNG dùng "đếm thao tác từng cuboid / dwell" làm công thức KPI:**
  - Trên dữ liệu pre-label, box AI đúng sẵn có 0 thao tác sửa → tính KPI theo thao tác sẽ kích hoạt nạn nhích chuột `micro-jitter` làm hỏng dữ liệu chuẩn.
  - Trên 3D Track, đếm theo keyframe sẽ khiến Annotator bấm `K` phá nội suy; đếm theo frame đổi tọa độ nội suy thì 1 kéo ở frame `0` ăn cả 100 frame.
  - Dwell (thời gian đứng trên frame) là tín hiệu thụ động dễ lướt qua/làm giả, không tương đương "đã làm xong".
  - Trên `cvat-base` gốc (v2.84.0), chế độ `Standard 3D` tắt UI Tag, bảng `LabeledTrack`/`TrackedShape` không có `updated_date`/`updated_by`, và `source` chỉ nằm ở cấp track (sửa 1 keyframe lật cả track).

### 2. Cơ chế chốt sản lượng Pre-label & `outside` (không tính điểm, chỉ đếm cuboid thật)
- **Chụp mốc Baseline `S0` lúc đồng bộ/tạo job từ CVAT (`cvat-sync`):** Đọc `/api/jobs/{id}/annotations` + `/data/meta` 1 lần khi tạo job mới, lưu gọn trên `Job`:
  - `baseline_frame_counts`: `{frame_number: visible_count_S0}` (số cuboid `outside=False` ban đầu theo từng frame).
  - `baseline_track_ids`: tập `track_id` pre-label ban đầu.
  - **Không** ghi `DailyOutputRecord` tại thời điểm import/sync ban đầu.
- **Khóa nhập tay `object_count` cho job gắn `cvat_job_id`:**
  - `POST /submit/` bỏ qua/chặn `object_count` nhập tay từ Annotator và tự động gọi CVAT đếm cuboid (timeout ngắn ~10–15s).
  - Nếu CVAT trả lỗi mạng/timeout: **vẫn cho hoàn tất `Submit`** để giữ đúng `submitted_at` (không oan trễ deadline `DH05`/`DH06`), đồng thời bật cờ `count_sync_pending = True` để đồng bộ bù tự động (và cảnh báo trước khi chốt mẫu `AuditSample.checked_object_count`).
  - Ngoại lệ duy nhất: **PM** được phép chỉnh `object_count` khi `source_missing = True` hoặc job không gắn `cvat_job_id` (bắt buộc ghi lý do vào `ActivityLog`).
- **2 phương án ghi nhận theo ngày (chọn 1 khi chốt):**
  - **Mô hình 1 (Đơn giản nhất — khi cắt job ≤ 1 ngày):** Chỉ ghi `DailyOutputRecord` từ CVAT tại thời điểm Annotator bấm `Submit`. Không phát sinh bước nhập tiến độ nào.
  - **Mô hình 2 (Khuyến nghị nếu có job dài nhiều ngày / OT chưa kịp Submit — bao trùm Mô hình 1):**
    - Job xong trong ngày: Annotator chỉ bấm **`Submit`** → hệ thống tự chốt toàn bộ các frame chưa tính.
    - Job dài nhiều ngày / OT: cuối ca Annotator cập nhật mốc frame đã xong (vd khoảng `0 → 45`) → backend VanoHub đọc CVAT, chỉ tính các frame mới chưa có trong `counted_frames` theo khóa `(job_id, rework_round)` (chống cộng đúp).
    - Vì tổng job khóa cứng theo CVAT, khai sớm mốc frame giữa chừng chỉ là ứng trước sản lượng ngày hôm sau của chính mình, không tạo cuboid ảo; khi đổi người làm giữa chừng (`reassignment`), PM gỡ các frame chưa làm để điều chỉnh phần `DailyOutputRecord` sang đúng người làm tiếp.
    - Bổ sung tùy chọn `Project.workday_cutoff_hour` (vd `04:00`) để ca OT sau `00:00` vẫn quy về đúng ngày làm việc.
- **Tách rạch ròi 2 công thức (không trộn lẫn):**
  1. **Sản lượng KPI (`SL01` / `SL06`) tại mỗi frame `f` được chốt:**
     $$\text{output}(f) = \max\big(\text{visible}_{S_1}(f),\; \text{visible}_{S_0}(f)\big)$$
     - Pre-label giữ/sửa: tính đủ.
     - Pre-label rác thuộc track span qua frame bị bật `outside=True`: `visible_{S_0}(f)` giữ mức nền nên **vẫn tính sản lượng**.
     - Cuboid vẽ mới (`outside=False`): `visible_{S_1}(f) > visible_{S_0}(f)` nên được cộng thêm.
     - Cuboid tự vẽ rồi tắt `outside` trước khi chốt: không có trong `S0`, không hiện trong `S1` → tính `0`.
     - Miễn nhiễm Split/Merge đổi `track_id` (không đếm trùng x2).
  2. **Mẫu số chất lượng (`CL02`, `CL05`, `CL11`) & `job.object_count` bàn giao:**
     - **Chỉ dùng `visible_{S_1}` (`outside=False`)**, tuyệt đối không cộng `outside=True` để tránh làm loãng tỷ lệ lỗi.
- **Hiển thị song song khi `SL06 = SL01 + SL03`:** Mọi bảng/thẻ KPI cá nhân và nhóm luôn tách rõ `SL01` (làm mới), `SL03` (rework), tỷ trọng rework (`SL03 / SL06`) và nhãn phân mức chất lượng đi kèm để không che giấu tình trạng làm ẩu gây nhiều vòng rework.

### 3. Chính sách Annotation theo `Guideline` (`annotation_policies`)
Cấu hình tổ hợp cờ ngay trên `Guideline` (snapshot vào `Batch`/`Job` khi áp dụng để phiên bản Guideline mới không làm thay đổi quy tắc của batch cũ). Hệ thống kiểm tra tự động **1 lần lúc `Submit`** bằng cách so `S0` với `S1` và **chỉ gắn cờ cảnh báo cho QC1** (không chặn cứng Submit để tránh oan deadline hoặc chặn nhầm ca Split/Merge hợp lệ):

| Cờ policy | Ý nghĩa | Kiểm tra tự động `S0 → S1` | Cảnh báo hiển thị cho QC1 |
| --- | --- | --- | --- |
| `do_not_delete` | Cấm xóa track/shape pre-label (tránh hỏng interpolation & mất track ID) | Mọi `track_id`/`shape_id` ở `S0` phải còn tồn tại ở `S1` | `forbidden_track_deleted` (kèm danh sách `track_id`) |
| `outside_only` | Ẩn box pre-label sai chỉ bằng `outside=True`, cấm xóa track | Gồm `do_not_delete` + kiểm tra `outside=True` có lan tràn sang vùng frame chưa hoàn thành | `forbidden_track_deleted`, `outside_spillover` |
| `add_only` | Chỉ vẽ thêm box mới, không xóa và không tắt `outside` pre-label | Không xóa `S0` + không chuyển `visible(S0) → outside(S1)` *(cần chốt có cấm sửa tọa độ pre-label hay không)* | `forbidden_track_deleted`, `forbidden_outside` *(+ `forbidden_prelabel_edit` nếu áp bản chặt)* |

- **Cảnh báo bổ trợ cho QC1 (chỉ thông tin, không cộng/trừ KPI):** `suspect_untouched` khi ≥ N frame liên tiếp có 0% thay đổi so với `S0`, giúp QC1 ưu tiên soi nhanh các đoạn có nguy cơ bỏ qua chưa kiểm.

### 4. Đánh giá 2 trục ĐỘC LẬP (`AND`), Cột phụ `Edge %` & Chỉ số `NS09` / `NS10` *(Đề xuất đã duyệt định hướng — chờ triển khai)*

- **Nguyên tắc đánh giá 2 trục ĐỘC LẬP (`AND`):**
  - **Loại bỏ mọi công thức cộng/trừ sản lượng bằng hệ số phạt `k` tùy ý** (ví dụ không trừ thẳng `k` cuboid khỏi sản lượng ngày). Sản lượng và chất lượng là **2 trục độc lập (`AND`)** phải đạt đồng thời.
  - **Trục Sản lượng (`SL`):** Đối chiếu `SL06 = SL01 + SL03` với chỉ tiêu (`KPI01` / `KPI02`), luôn tách rõ sản lượng làm mới (`SL01`) và sản lượng rework (`SL03`).
  - **Trục Chất lượng (`CL` — ngưỡng giả định tham khảo từ mentor, cấu hình được theo `Project`):** Đề xuất 2 mốc cấu hình `quality_cl_target` (giả định `95%`) và `quality_cl_warning_threshold` (giả định `90%`):

| Mức trạng thái | Giả định ngưỡng `Quality CL` (`CL11`) | Tương đương `Defect Error Rate` (`CL02`) | Ý nghĩa vận hành |
| --- | --- | --- | --- |
| **Đạt (`good` — Xanh)** | `≥ 95%` | `≤ 5%` | Chất lượng tốt, QA đi nhanh |
| **Đáng báo động (`warning` — Vàng)** | `90% ≤ CL11 < 95%` | `5% < CL02 ≤ 10%` | Đáng báo động — cần rà lỗi, nhắc guideline / coaching |
| **Cảnh báo (`critical` — Đỏ)** | `< 90%` | `> 10%` | Cảnh báo nặng — nguyên nhân trực tiếp gây `QA days > Annotation days`, cần PM can thiệp |

- **Ma trận hành động 4 góc phần tư (`SL` × `CL`):**

| Trục Sản lượng (`SL`) \ Trục Chất lượng (`CL`) | Chất lượng tốt (`CL` đạt ngưỡng) | Chất lượng thấp (`CL` Vàng / Đỏ) |
| --- | --- | --- |
| **Sản lượng cao (đạt / vượt `KPI01`)** | **Khen thưởng / Tăng tải:** Duy trì, cân nhắc tăng tải hoặc giao ca khó | **Dừng tăng tốc, rà lỗi lặp & coaching:** Chặn xu hướng "làm nhanh gây nghẽn QA", rà nhóm lỗi hay lặp |
| **Sản lượng thấp (dưới `KPI01`)** | **Đào tạo tốc độ / workflow:** Giữ chuẩn chất lượng, hướng dẫn tối ưu thao tác & phím tắt CVAT | **Re-training / Kèm cặp:** Đào tạo lại guideline và kèm cặp sát đầu ra trước khi tăng tải |

- **Cột phụ `Edge %` (`edge / tổng cuboid`):**
  - Hiển thị song song **cạnh tỷ lệ `Pass` / `Quality CL`** để tách nhóm ca khó / cận biên (`ReviewError.verdict = "edge"`) ra quan sát riêng (nhận diện vùng mờ của guideline hoặc đối tượng rìa FOV).
  - **Không tự ý đổi định nghĩa Pass chuẩn** khi chưa có dữ liệu chứng minh từ vận hành thực tế.

- **Chỉ số nghẽn QA (`NS09`) & End-to-End Throughput (`NS10` — Phase 2 / Đề xuất):**
  - **`NS09` (`qa_to_annotation_ratio`):** Tổng giờ / ngày công giai đoạn `QC1 + QC2` chia cho tổng giờ / ngày công giai đoạn `Annotation`. `ratio ≥ 1.0` (`qa_days > annotation_days`) báo động nghẽn QA cấp Task/Project.
  - **`NS10` — End-to-End Throughput (Phase 2 / Đề xuất):**
    $$\text{NS10} = \frac{\text{approved\_cuboids}}{\text{annotation\_days} + \text{qa\_days}}$$
    Theo dõi **thông lượng toàn quy trình ở cấp Task / Project** (từ Annotate đến khi `approved`), giúp PM nhận diện trực tiếp nút thắt `qa_days > annotation_days` và tác động của rework lặp lên tốc độ bàn giao mà **không phạt sai lệch lên từng cá nhân**.

### 5. Danh sách điểm mở cần PM / Mentor xác nhận trước khi triển khai
1. **Ngưỡng chất lượng giả định (`95%` / `90%`):** Giữ làm giá trị mặc định khởi tạo dự án hay đổi mốc? Áp chung cho cá nhân (`Annotator`), `Task (Batch)`, hay tách ngưỡng riêng?
2. **Định nghĩa $N_{\text{checked}}$ theo frame cho `CL02`/`CL05`/`CL11`:** Chốt cách đọc/lưu `AuditSample.checked_object_count` chỉ trên tập `AuditSample.frames` khi chấm QC2 để mở khóa `pending_definition`.
3. **Mô hình ghi nhận ngày:** Chọn **Mô hình 1** (cắt job ≤ 1 ngày, chỉ chốt lúc `Submit`) hay **Mô hình 2** (chốt lúc `Submit` + mốc frame cuối ca cho job nhiều ngày/OT)?
4. **Định nghĩa chặt cho `add_only`:** Cấm sửa cả tọa độ/nhãn pre-label (chỉ vẽ mới) hay vẫn cho tinh chỉnh tọa độ, chỉ cấm xóa & cấm `outside`?
5. **Cắt ngày cho ca OT xuyên `00:00`:** Có áp dụng `Project.workday_cutoff_hour` (vd `04:00`) không?
6. **Trường hợp track keyframe thưa khi bật `outside=True`:** Chấp nhận tính `per_frame` theo `max(visible_S1(f), visible_S0(f))` hay cần tùy chọn `keyframe_only`?

---

## BACKLOG — KIẾN TRÚC PLUGIN STUB (TRÊN NỀN CVAT-BASE GỐC)

> **Trạng thái:** Backlog sau MVP (chưa triển khai mã nguồn stub ở giai đoạn hiện tại).  
> **Nguyên tắc:** Không fork hoặc patch `cvat-base`; VanoHub giữ vai trò nền tảng lõi (tiến độ, chất lượng, giao việc) và mở rộng theo mô hình **cắm-rút (plug-in)** khi cần nối thêm công cụ ngoài (`cvat-auto-qc`, hệ thống telemetry phiên làm việc, CVAT webhook, hoặc overlay UI).

| Hạng mục Backlog | Giao diện / Thực thể dự kiến | Mục đích & dữ liệu trao đổi |
| --- | --- | --- |
| **B1. Plugin Hooks (Python `Protocol`)** | `TelemetryCollector`, `ExternalQcFindingProvider`, `WorkSessionProvider` | Cho phép đăng ký nguồn dữ liệu ngoài qua cấu hình mà không sửa logic lõi của `jobs`/`quality`/`analytics`. |
| **B2. Bảng `JobTelemetryEvent`** | `(project, job, user, source, event_type, occurred_at, delta_objects, duration_seconds, payload, idempotency_key)` | Nhận sự kiện làm việc / phiên hoạt động từ plugin ngoài để bổ sung `NS01`–`NS04` chính xác theo phiên thực (có chống ghi trùng theo `idempotency_key`). |
| **B3. API nhận cảnh báo Auto-QC** | `POST /api/projects/{id}/jobs/{job_id}/plugin-findings/` | Cho phép pipeline kiểm định tự động (như `cvat-auto-qc`) đẩy kết quả gợi ý lỗi (`frame_number`, `cvat_object_id`, `severity`, `confidence`, `source_plugin`, `status=suggested`) vào `ReviewError` mà không tự ý đổi trạng thái `Job`; QC1/QC2 xác nhận hoặc bỏ qua. |
| **B4. API nhận Telemetry** | `POST /api/projects/{id}/telemetry/` | Nạp batch sự kiện làm việc / thời gian thao tác từ plugin ngoài (xác thực theo API key/service token riêng). |
| **B5. CVAT Webhook Ingest** | `POST /api/integrations/cvat/webhook/` | Nhận webhook gốc từ `cvat-base` (`update:job`, `update:task`, xác thực chữ ký HMAC `X-Signature-256`) để kích hoạt đồng bộ tự động thay vì chỉ bấm thủ công. |
| **B6. Mở rộng KPI & Quy trình hậu MVP** | `KpiTargetHistory(effective_from)`, `Project/Dataset.deadline`, `Delivery.reopen`, `CL08`/`CL10`/`CL12`/`CL13`, `NS02`/`NS04`/`NS05`/`NS07`/`NS08`, `RW03`/`RW05`/`RW06`, `AU06`, `DB01`–`DB04`, `DA02`–`DA03` | Các chỉ số P2 và quy trình hậu bàn giao triển khai tăng dần sau khi lõi MVP vận hành ổn định. |
