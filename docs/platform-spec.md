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

---

## THÔNG TIN CHUNG VÀ LUẬT DỰ ÁN

### 1. Mục tiêu và phạm vi — PV

| Mã | Vấn đề cần thống nhất | Quy định & hiện trạng |
| --- | --- | --- |
| PV01 | Vấn đề ưu tiên | Giải quyết 3 vấn đề cốt lõi:<br>• Phân mảnh các giai đoạn công việc (quản lý bằng sheet, thao tác trên CVAT, trao đổi truyền miệng).<br>• Dễ sót thông tin và khó quản lý tập trung các thành phần dự án.<br>• Khó mở rộng (scale up) mô hình vận hành hiện tại. |
| PV02 | Người sử dụng | **4 vai trò phẳng:** `PM`, `QC2` (QC Level 2), `QC1` (QC Level 1), `Annotator`. |
| PV03 | Phạm vi MVP | [Danh sách tính năng MVP cần có](./mvp-checklist.md) |
| PV04 | Ranh giới với CVAT | • **Làm trên VanoHub:** Quản lý dự án/dataset/batch, giao việc & giới hạn WIP, vòng đời trạng thái job, kiểm duyệt QC1/QC2 & ghi nhận lỗi (`ReviewError`), xác nhận batch sang QC2, lấy mẫu & chốt audit QC2, theo dõi tiến độ/deadline/KPI, thông báo trong app, nhật ký thao tác và ghi nhận bàn giao.<br>• **Làm trên CVAT:** Vẽ/chỉnh sửa annotation (`shapes` / `tracks` / cuboid) trực tiếp qua deep link từ VanoHub.<br>• *Hiện trạng đồng bộ:* VanoHub đọc/đồng bộ một chiều từ CVAT (`import-cvat` / `sync-cvat`) cho các bước trước QC2; chưa đẩy ngược trạng thái từ VanoHub về CVAT (đồng bộ 2 chiều là hạng mục mở rộng). |
| PV05 | Tiêu chí thành công | • Giảm thời gian tổng hợp, hỏi tiến độ và thao tác quản lý của PM nhờ tập trung trên 1 nền tảng.<br>• Số liệu cập nhật liên tục theo từng dự án, dễ báo cáo và bám sát KPI nhân sự.<br>• Giảm thời gian job nằm chờ giữa các bước (`Anno → QC1 → QC2 → Bàn giao`).<br>• Batch bàn giao đúng hạn hơn mà không giảm chất lượng. |

### 2. Quy trình và tổ chức — TC

| Mã | Vấn đề cần thống nhất | Quy định & hiện trạng |
| --- | --- | --- |
| TC01 | Quy trình vận hành (phẳng) | Vòng đời chuẩn của công việc:<br>1. **PM** tạo dự án, cấu hình quy tắc (rework, sampling, WIP, KPI, danh mục lỗi, guideline) và tạo Dataset / Batch.<br>2. Đội tiền xử lý chuẩn bị dữ liệu trên CVAT; **PM** nhập CVAT Task thành Batch và Job trên VanoHub.<br>3. **PM** giao job (hoặc **Annotator** tự nhận từ hàng chờ theo giới hạn WIP) → Annotator thực hiện trên CVAT và nộp bài lên QC1.<br>4. **QC1** kiểm tra từng job: `Pass` → `Đạt QC1` (`qc1_passed`) hoặc `Reject` kèm danh sách lỗi → `Rework`.<br>5. Khi **100% job trong batch** đã đạt QC1, **PM** xác nhận chuyển cả batch sang `Chờ QC2` (`pending_qc2`).<br>6. **PM** tạo đợt audit QC2 (Random / Stratified) và phân cho **QC2** → QC2 chấm `Pass` / `Reject` từng job mẫu.<br>7. **PM** chốt kết quả audit (`Chấp nhận batch` / `Trả cả batch` / `Trả theo tầng`) và ghi nhận bàn giao khi 100% job của batch đạt `Đã duyệt`. |
| TC02 | Cơ cấu quản lý | • **Cấu trúc phẳng:** `PM → Annotator / QC1 / QC2` (không có tầng Director hay Team Leader).<br>• **PM** chịu trách nhiệm tổng thể dự án, trực tiếp điều phối công việc hằng ngày, chốt tiêu chuẩn chất lượng, phân xử khiếu nại lỗi và xử lý dữ liệu bị chặn.<br>• Không ai được tự ý thay đổi tiêu chuẩn gán nhãn hoặc bỏ qua lỗi khi chưa có quyết định của PM. |
| TC03 | Dự án và nhóm phân bổ | • Mọi thành viên tham gia dự án qua bản ghi phân quyền theo dự án (`RoleAssignment`) và chịu quản lý trực tiếp của **PM**.<br>• *Ghi chú kỹ thuật:* Hệ thống có thực thể `Team` / `TeamMember` (không có `leader`) dùng làm nhóm phân bổ tùy chọn cho PM quản lý sức chứa (`capacity`), lọc pool batch và gửi thông báo nhóm; không tạo tầng quản lý trung gian. |
| TC04 | Thành viên | Mỗi thành viên (`Annotator`, `QC1`, `QC2`) được PM thêm vào dự án và có thể tham gia nhiều dự án với các vai trò độc lập theo từng dự án. |
| TC05 | Kiêm nhiệm và thay thế | • **Kiêm vai trò:** Một người có thể giữ nhiều vai trò trong cùng dự án (nhiều dòng `RoleAssignment`). Đặc biệt, **`PM` mặc định kiêm `QC2`** (`IMPLIED_ROLES = {PM → QC2}`); chiều ngược lại không đúng.<br>• **Luật bốn mắt (bắt buộc):** Không được QC1 job mình đã annotate; không được audit QC2 job mình đã annotate hoặc đã QC1.<br>• **Thay thế khi vắng mặt:** Dùng tài khoản riêng của người thay thế (không dùng chung tài khoản); PM giao lại job cho QC/Annotator khác đảm bảo không vi phạm luật bốn mắt; PM khác trong dự án tiếp nhận khi PM vắng mặt. |

### 3. Dữ liệu và cấu trúc công việc — DL

| Mã | Vấn đề cần thống nhất | Quy định & hiện trạng |
| --- | --- | --- |
| DL01 | Nguồn dữ liệu | Dữ liệu ảnh/LiDAR gốc được đội tiền xử lý lọc và tạo thành Project / Task / Job trên CVAT. Trên VanoHub, PM gắn `cvat_project_id` vào Project, duyệt danh sách CVAT Task (`/api/cvat/tasks/`) và nhập vào Batch qua `import-cvat`. |
| DL02 | Quan hệ dữ liệu | Phân cấp chuẩn: `Project (1) → Dataset (N) → Batch (N) → Job (N)`.<br>• Ánh xạ CVAT: `1 Project ↔ 1 CVAT Project` (`cvat_project_id`), `1 Batch ↔ 1 CVAT Task` (`cvat_task_id`), `1 Job ↔ 1 CVAT Job` (`cvat_job_id`, duy nhất toàn hệ thống).<br>• Các thực thể gắn kèm: `Batch → Audit → AuditSample`; `Batch → Delivery`; `Job → ReviewError`, `AnnotatorRequest`, `ActivityLog`. |
| DL03 | Quyền tạo | • **Project, Dataset, Batch:** Chỉ **PM** tạo/cập nhật trên VanoHub.<br>• **Job:** Chỉ tạo qua thao tác PM nhập từ CVAT Task vào Batch (`POST .../batches/{id}/import-cvat/`); không tạo job thủ công tách rời CVAT. |
| DL04 | Quy tắc chia batch | Mặc định `1 Batch = 1 CVAT Task`, số job trong batch linh hoạt theo dữ liệu đầu vào. PM có thể gom/chuyển hàng loạt job sang batch khác cùng dự án (`bulk-move-batch`) khi job chưa khóa, chưa bàn giao và không thuộc đợt audit QC2 đang mở. |
| DL05 | Thông tin bắt buộc & cấu hình | • **Dự án:** Tên dự án, mô tả, PM phụ trách (`pm_ids`), `cvat_project_id` (tùy chọn khi khởi tạo).<br>• **Cấu hình vận hành trên Project:** `max_rework_rounds` (mặc định DB `3`, khuyến nghị `2`), `escalation_policy` (`block` / `warn_only`), `annotator_wip_limit` (mặc định `2`), chiến thuật lấy mẫu QC2 (`sampling_method`: `random` / `stratified`, `sampling_rate`: mặc định `10%`, `stratify_by`: `annotator` / `qc1_reviewer` / `dataset`), ngưỡng `quality_cl_threshold` / `defect_rate_threshold`, chỉ tiêu `kpi_annotation_target` (object/ngày), `kpi_qc1_target` (job/ngày), `kpi_qc2_target` (job/ngày).<br>• **Batch:** Tên (duy nhất trong Dataset), `deadline` (tự kế thừa xuống job khi import). |
| DL06 | Thay đổi cấu trúc | • **Không xóa cứng** Dataset, Batch, Job hay Danh mục lỗi đang dùng để bảo toàn truy vết.<br>• PM được `lock` / `unlock` Dataset, Batch, Job (khi chưa `delivered`), giao/giao lại job, đổi deadline, chuyển batch (`bulk-move-batch`). Mọi thay đổi đều ghi `ActivityLog` (trước/sau, người thao tác, lý do). |
| DL07 | Hướng dẫn gán nhãn | • Chỉ **PM** (`manage_quality_catalog`) soạn và phát hành `Guideline` dạng Markdown; mỗi lần lưu tự tăng `version` (khóa dòng Project chống trùng phiên bản), giữ nguyên toàn bộ phiên bản cũ.<br>• Mọi vai trò trong dự án đều xem được toàn bộ lịch sử phiên bản.<br>• *Chưa chốt kỹ thuật:* Job chưa lưu trường `guideline_version` áp dụng tại thời điểm giao, nên mặc định các job đang làm tham chiếu phiên bản mới nhất. |

### 4. Giao việc và thực hiện — GV

| Mã | Vấn đề cần thống nhất | Quy định & hiện trạng |
| --- | --- | --- |
| GV01 | Cách nhận việc | Hỗ trợ song song 2 cách:<br>• **PM phân công chủ động** từng job hoặc hàng loạt (`assign` / `bulk-assign`) cho Annotator và QC1.<br>• **Annotator tự nhận việc (`claim`)** từ pool job `pending_annotation` chưa có người làm (tự động khóa dòng `skip_locked` tránh nhận trùng, ưu tiên deadline sớm nhất và tuân thủ luật bốn mắt). |
| GV02 | Điều kiện nhận việc | Giới hạn WIP theo cấu hình dự án (`Project.annotator_wip_limit`, mặc định **2 job** đang ở `pending_annotation` / `annotating` / `rework`). Annotator đạt giới hạn phải nộp bớt mới được nhận thêm (chặn ở API `claim` với khóa tuần tự theo user). |
| GV03 | Thứ tự ưu tiên | Hàng đợi công việc cá nhân và QC1 sắp theo **DB06**: `Quá hạn → Sắp đến hạn (≤ 24h) → Rework → Còn lại`, sau đó theo deadline sớm nhất và ID job. Khi tự nhận từ pool, ưu tiên batch của nhóm phân bổ (nếu có) và deadline sớm nhất. |
| GV04 | Thu hồi và giao lại | **PM** có quyền giao lại Annotator / QC1 / Auditor QC2 (`assign`, `bulk-assign`, `audit-samples/{id}/assign`) khi job chưa khóa/bàn giao, kèm ghi chú lý do và tự động gửi thông báo `assigned` cho người mới. *(Chưa có bước xác nhận đồng ý 2 chiều từ người nhận cũ).* |
| GV05 | Công việc dở dang | Khi đổi người làm job, các lượt nộp bài trước đó vẫn gắn với `actor` cũ trong `ActivityLog` nên sản lượng đã nộp không bị chuyển sang người mới; phần việc nộp sau khi giao lại tính cho người mới. |
| GV06 | Nộp bài | Annotator chuyển `pending_annotation` / `rework` → `annotating` (`start`) → `pending_qc1` (`submit`, kèm `object_count` và ghi chú). Sau khi nộp, Annotator không thể tự rút job về mà phải chờ QC1 kiểm tra (`Pass` hoặc `Reject` sang `rework`). |

### 5. Luồng duyệt, chất lượng và ngoại lệ — L

| Mã | Vấn đề cần thống nhất | Quy định & hiện trạng |
| --- | --- | --- |
| **L1** | **Vòng đời trạng thái Job** | 9 trạng thái chuẩn trên `JobStatus`:<br>`pending_annotation` (Chờ annotate) → `annotating` (Đang annotate) → `pending_qc1` (Chờ QC1) → `qc1_reviewing` (Đang QC1) → `qc1_passed` (Đạt QC1) → `pending_qc2` (Chờ QC2, sau khi PM xác nhận batch) → `approved` (Đã duyệt) → `delivered` (Đã bàn giao).<br>Nhánh trả sửa: `qc1_reviewing` / `pending_qc2` / `audit.complete` → `rework` → `annotating`. |
| **L2** | **Vượt giới hạn rework** | • Giới hạn vòng sửa `max_rework_rounds` do PM cài đặt theo dự án (mặc định DB `3`, khuyến nghị nghiệp vụ `2`).<br>• Mỗi lần QC1/QC2/PM trả job về `rework`, tăng `rework_round += 1`. Khi `rework_round > max_rework_rounds`, bật `is_escalated = True` và gửi thông báo `escalated` (ghim chờ xử lý) lên **PM**.<br>• Chính sách xử lý `escalation_policy` do PM chọn: `block` (khóa job chờ PM gọi `resolve-escalation`) hoặc `warn_only` (chỉ cảnh báo, vẫn cho Annotator sửa tiếp). Khi PM gỡ escalation, có thể đổi người làm và đặt lại `rework_round = 0` trong khi giữ nguyên lịch sử lỗi. |
| **L3** | **Chuyển QC1 → QC2** | • QC1 duyệt từng job sang `qc1_passed`.<br>• Khi **100% job trong batch** đã qua QC1 (không còn job ở `pending_annotation`, `annotating`, `rework`, `pending_qc1`, `qc1_reviewing`), hệ thống gửi thông báo `review_needed` cho PM.<br>• **PM** thực hiện `confirm-qc2` theo batch để chuyển toàn bộ job `qc1_passed` của batch sang `pending_qc2` (chặn cứng nếu còn bất kỳ job nào chưa đạt QC1). |
| **L4** | **Quyền quyết định chất lượng** | • **QC2** chấm `Pass` (`→ approved`) hoặc `Reject` (`→ rework`, bắt buộc kèm `ReviewError`) cho từng job mẫu (`AuditSample`).<br>• Khi 100% mẫu đã có kết quả, **PM** chốt đợt audit (`audit.complete`) với 3 quyết định:<br>&nbsp;&nbsp;◦ `accept`: Chấp nhận batch (các job chưa lấy mẫu trong đợt được chuyển sang `approved`).<br>&nbsp;&nbsp;◦ `reject`: Trả cả batch về `rework` (bắt buộc ghi `reason`).<br>&nbsp;&nbsp;◦ `partial_reject` *(chỉ cho Stratified)*: Chấp nhận hoặc trả `rework` theo từng tầng (`stratum_decisions`, bắt buộc ghi `reason`).<br>• *Ghi chú cần bổ sung:* Backend hiện chưa tự chặn PM chọn `accept` cho phần chưa lấy mẫu nếu đợt audit có mẫu bị QC2 `reject`, và chưa có kiểm tra tự động "chưa đánh obstacles". |
| L5 | Điều kiện đạt QC1 | QC1 kiểm tra toàn bộ job trên CVAT và đánh dấu đạt/trả sửa theo ngưỡng chất lượng dự án (`quality_cl_threshold` / `defect_rate_threshold` do PM cấu hình). |
| L6 | Danh mục lỗi | • Quản lý theo từng dự án (`ErrorCategory`): tên lỗi, mô tả, mức độ (`minor` Nhẹ / `major` Nặng / `critical` Nghiêm trọng), phạm vi áp dụng (`qc1` / `qc2` / `both`).<br>• Với cuboid: thiếu/thừa đối tượng, sai lớp, sai vị trí/kích thước/hướng, sai thuộc tính, sai ID liên kết giữa các frame.<br>• Chỉ **PM** tạo/sửa danh mục; không xóa cứng (`on_delete=RESTRICT`), chỉ ẩn bằng `is_active = False` để bảo toàn lịch sử. |
| L7 | Bằng chứng lỗi | Khi QC1 hoặc QC2 trả `Reject`, bắt buộc ghi ít nhất 1 `ReviewError` gồm loại lỗi, mức độ, vị trí (`location`: frame/object ID) và mô tả. *(Hạng mục nâng cấp: tách `frame_number` + `cvat_object_id` có cấu trúc để tính chính xác `CL02` và `CL11`).* |
| L8 | Phạm vi sửa và kiểm lại | Khi trả rework QC1, QC1 chọn `rework_scope`: `partial` (sửa theo danh sách lỗi đã ghi) hoặc `full` (sửa toàn job). Annotator xem chi tiết lỗi theo từng vòng sửa; QC1 kiểm lại theo phạm vi tương ứng. |
| L9 | Lấy mẫu QC2 | • Hỗ trợ 2 phương pháp do PM cấu hình: **Random** (`sampling_rate`% số job `pending_qc2` của batch) và **Stratified** (phân tầng theo `annotator` / `qc1_reviewer` / `dataset`).<br>• Hỗ trợ xem trước mẫu (`preview`) kèm `seed` ngẫu nhiên lưu trên `Audit` để tái lập/giải trình vì sao job được chọn; tự động phân auditor tránh vi phạm luật bốn mắt.<br>• *Ghi chú:* Hiện lấy mẫu ở **cấp job trong batch**; chưa có lấy mẫu tự động ở **cấp frame trong job** (`AU01`–`AU02`). |
| L10 | Batch không đạt | Khi PM chọn `reject` hoặc `partial_reject`, toàn bộ job bị trả (ngoại trừ job đã `reject` ở bước chấm mẫu) chuyển về `rework`, tăng `rework_round`, thông báo cho Annotator và QC1 phụ trách. Sau khi sửa và đạt QC1, PM xác nhận chuyển QC2 và tạo đợt audit mới. |
| L11 | Phản hồi lỗi | Annotator gửi yêu cầu `error_dispute` gắn với job và `ReviewError` cụ thể **trực tiếp tới PM** (`status = pending_pm`); PM xem xét và kết luận `resolved` hoặc `rejected` kèm `resolution_note`. |
| L12 | Dữ liệu có vấn đề | Annotator báo `data_issue` **trực tiếp tới PM** (`status = pending_pm`). PM có thể tạm khóa job (`lock`) trong thời gian chờ xử lý dữ liệu / xác nhận khách hàng, sau đó kết luận yêu cầu và mở khóa. |
| L13 | Luật bốn mắt | Thực thi cứng ở backend trên mọi thao tác giao việc, tự nhận việc, QC1 và QC2: `annotator != qc1_reviewer`; QC2 `auditor` không được trùng `annotator` hoặc `qc1_reviewer`. *(Hạng mục nâng cấp: đối chiếu thêm lịch sử `ActivityLog` nếu job từng đổi người làm giữa chừng).* |
| L14 | Can thiệp và mở lại | PM có quyền `lock` / `unlock` job, batch, dataset chưa bàn giao và gỡ escalation (`resolve-escalation`). *(Chưa có API mở lại job đã `approved` hoặc `delivered` về `rework` — cần bổ sung nếu áp dụng quy trình hậu bàn giao).* |

### 6. Deadline và thời gian — TG

| Mã | Vấn đề cần thống nhất | Quy định & hiện trạng |
| --- | --- | --- |
| TG01 | Các cấp deadline | Mục tiêu: Project, Dataset, Batch và Job do **PM** đặt.<br>• *Hiện trạng DB:* Đã có `deadline` ở cấp **Batch** và **Job** (job tự kế thừa hạn batch khi import; PM đặt/đổi hàng loạt qua `bulk-deadline`). Cấp Project và Dataset chưa có cột `deadline`. |
| TG02 | Cách tính thời gian | Deadline lưu theo mốc `DateTime` chuẩn UTC và hiển thị theo múi giờ người dùng (`User.timezone_name`, mặc định `Asia/Ho_Chi_Minh`). |
| TG03 | Gia hạn | Chỉ **PM** được điều chỉnh deadline batch/job; thao tác đổi hạn job **bắt buộc ghi lý do (`note`)** và lưu giá trị trước/sau vào `ActivityLog`. |
| TG04 | Quá hạn và sắp hạn | • `due_soon`: còn `≤ 24 giờ` so với hiện tại trên job đang mở (`OPEN_STATUSES`).<br>• `overdue`: đã quá hạn trên job đang mở.<br>• Hệ thống tự tạo cảnh báo `deadline` (ghim chờ xử lý) cho người đang giữ job (Annotator / QC1 / QC2) và **PM** dự án. |
| TG05 | Rework và tạm dừng | PM có thể đặt/điều chỉnh lại deadline khi job vào rework. *(Chưa có cơ chế tự động trừ thời gian tạm dừng do `data_issue` / `error_dispute` khỏi thời gian tính SLA).* |

### 7. KPI và chỉ số — CS

| Mã | Vấn đề cần thống nhất | Quy định & hiện trạng |
| --- | --- | --- |
| CS01 | Đơn vị sản lượng | • **Annotator:** Số object/cuboid xử lý mỗi ngày (`kpi_annotation_target`).<br>• **QC1 & QC2:** Số job hoàn tất kiểm tra mỗi ngày (`kpi_qc1_target`, `kpi_qc2_target`).<br>• Toàn bộ chỉ tiêu do **PM** cấu hình theo từng dự án. |
| CS02 | Thời điểm ghi nhận | • **Annotator:** Ghi nhận theo sự kiện nộp bài (`submit` → `ActivityLog` `job.status=pending_qc1` kèm `object_count`) hoặc đồng bộ `object_count` từ CVAT *(chưa có webhook realtime cho từng cú bấm xác nhận 1 object trong CVAT)*.<br>• **QC1:** Ghi nhận tại thời điểm bấm `qc1.pass` hoặc `qc1.reject`.<br>• **QC2:** Ghi nhận tại thời điểm bấm `pass` hoặc `reject` trên `AuditSample` (`reviewed_at`). |
| CS03 | Rework và nhiều người làm | • Sản lượng rework **vẫn tính vào tổng sản lượng KPI** của Annotator (`first_pass_objects + rework_objects`), hiển thị tách biệt hai phần.<br>• Khi nhiều người tham gia cùng 1 job, mỗi lượt nộp ghi theo `actor` thực hiện nên sản lượng thuộc về đúng người nộp. |
| CS04 | KPI khoán | PM đặt chỉ tiêu trên `Project`.<br>• *Hạng mục cần chốt khi đổi chỉ tiêu giữa kỳ:* Hiện chỉ lưu 1 giá trị hiện hành trên `Project` (chưa có bảng lịch sử chỉ tiêu theo ngày hiệu lực); đề xuất thêm `KpiTargetHistory(effective_from)` để ngày cũ giữ nguyên chỉ tiêu cũ, ngày mới áp chỉ tiêu mới. |
| CS05 | Chất lượng | Xem chi tiết tại mục [Chi tiết chỉ số chất lượng chính (FPY, Defect Error Rate, Quality CL)](#chi-tiết-chỉ-số-chất-lượng-chính-fpy-defect-error-rate-quality-cl). |
| CS06 | Tốc độ làm việc | • **Annotator:** `AnnotatorAnalyticsView` ước tính giờ làm phiên (`NS01`) bằng hiệu thời gian từ lần chuyển sang `ANNOTATING` gần nhất đến lúc `submit` (giới hạn `0.25h – 10h`/phiên; mặc định `7.5h` nếu thiếu mốc bắt đầu). Chưa tự trừ giờ nghỉ/chờ.<br>• **QC1 / QC2:** Chưa lưu thời điểm bắt đầu kiểm từng lượt audit nên `audit_speed` đang trả trạng thái `pending_definition`. |
| CS07 | Đánh giá QC | • Đánh giá QC1 theo sản lượng kiểm, tỷ lệ Pass/Reject, phân bố lỗi ghi nhận và **số lỗi QC1 bỏ sót (`qc2_escape_errors`)** — tức lỗi QC2 phát hiện trên job mà QC1 đó đã duyệt đạt.<br>• Đánh giá QC2 theo số mẫu audit, tỷ lệ Pass/Reject, tiến độ theo batch và so sánh 2 kỳ.<br>• Tranh chấp kết luận chất lượng do **PM** phân xử. |
| CS08 | Kỳ báo cáo và múi giờ | Báo cáo theo `day` / `week` / `month` (và `7d` / `30d` / `week` cho phân tích cá nhân), tính theo múi giờ người dùng (`User.timezone_name`, mặc định `Asia/Ho_Chi_Minh`) và hiển thị mốc đồng bộ CVAT gần nhất (`last_cvat_sync_at`). |

### 8. Phân quyền và bảo mật — PQ

| Mã | Vấn đề cần thống nhất | Quy định & hiện trạng |
| --- | --- | --- |
| PQ01 | Phạm vi nhìn thấy | • **PM:** Xem toàn bộ dữ liệu trong các dự án được phân công.<br>• **QC2:** Chỉ xem các đợt audit và mẫu `AuditSample` được giao cho mình.<br>• **QC1:** Chỉ xem job được giao kiểm và pool job `pending_qc1` hợp lệ (loại trừ job tự annotate).<br>• **Annotator:** Chỉ xem job được giao cho mình, lỗi/yêu cầu của mình và thứ hạng cá nhân (không thấy điểm/dữ liệu của đồng nghiệp).<br>• Người không thuộc dự án nhận `404 Not Found` (không tiết lộ dự án có tồn tại).<br>• Chi tiết xem tại [Ma trận phân quyền (RBAC)](#ma-trận-phân-quyền-rbac). |
| PQ02 | Quản lý quyền | • **PM** tạo/sửa dự án, gán danh sách PM phụ trách (`pm_ids`) và gán thêm các vai trò `QC2`, `QC1`, `Annotator` cho thành viên trong dự án (`POST .../members/{user_id}/roles/`).<br>• Quản trị tài khoản hệ thống (`User`, cấp quyền superuser/PM đầu tiên) do quản trị viên Django Admin đảm nhiệm. |
| PQ03 | Tài khoản và nghỉ việc | Mỗi nhân sự có tài khoản riêng trên VanoHub liên kết với `cvat_username` (hoặc trùng `username`). Khi nghỉ việc, vô hiệu hóa tài khoản (`is_active = False` — giữ toàn bộ lịch sử), PM giao lại các job đang mở cho người khác; nếu PM nghỉ, bàn giao dự án qua danh sách `pm_ids`. |
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
| BG01 | Điều kiện bàn giao | • **Cấp Batch (đã triển khai):** Batch đủ điều kiện bàn giao khi có ít nhất 1 job, **100% job** ở trạng thái `approved` và **không còn đợt audit QC2** nào đang `in_progress` (`/api/projects/{id}/deliveries/candidates/`).<br>• **Cấp Dataset (tổng hợp):** Dataset sẵn sàng bàn giao hoàn tất khi toàn bộ batch trong dataset đã được duyệt/bàn giao. |
| BG02 | Người và đầu ra bàn giao | **PM** (`manage_delivery`) tạo bản ghi `Delivery` cho từng batch, lưu thời điểm (`delivered_at`), người thực hiện (`delivered_by`), người nhận (`recipient`), đường dẫn đầu ra (`output_path`), ghi chú (`note`) và phản hồi khách hàng (`client_feedback`). |
| BG03 | Khóa sau bàn giao | Ngay khi tạo `Delivery`, hệ thống tự chuyển `Batch.status = delivered` và toàn bộ job trong batch sang `JobStatus.DELIVERED`, khóa cứng mọi chỉnh sửa/chuyển trạng thái (`ensure_editable` & `_set_status` chặn thay đổi). |
| BG04 | Lỗi sau bàn giao | PM có thể cập nhật `client_feedback` trên bản ghi `Delivery`. *(Hạng mục cần bổ sung: API mở lại `reopen` batch/job đã `delivered` khi khách hàng reject để chạy lại vòng sửa và theo dõi trên timeline).* |

### 11. Đồng bộ CVAT và vận hành — VH

| Mã | Vấn đề cần thống nhất | Quy định & hiện trạng |
| --- | --- | --- |
| VH01 | Nguồn dữ liệu chuẩn | • **CVAT làm chuẩn:** Dữ liệu annotation (`shapes`/`tracks`/cuboid), số frame (`frame_count`), trạng thái gốc CVAT (`cvat_stage`/`cvat_state`).<br>• **VanoHub làm chuẩn:** Cấu trúc Project/Dataset/Batch, workflow trạng thái (nhất là từ QC2 trở đi), phân công & WIP, deadline, số vòng rework & escalation, `ReviewError`, QC2 `Audit`, `Delivery`, KPI và `ActivityLog`. |
| VH02 | Chiều và tốc độ đồng bộ | • Hiện triển khai **đồng bộ một chiều thủ công (CVAT → VanoHub)** khi PM bấm `import-cvat` hoặc `sync-cvat` (tùy chọn `count_objects=true`).<br>• Chỉ đồng bộ trạng thái cho job ở các bước trước QC2 (`SYNCABLE_STATUSES`: `annotation` + `qc1`).<br>• *Mở rộng sau MVP:* Đồng bộ nền định kỳ / webhook và đẩy trạng thái 2 chiều ngược về CVAT. |
| VH03 | Xung đột | • **Trước QC2:** Khi PM bấm `sync-cvat`, trạng thái ánh xạ từ CVAT (`CVAT_STATUS_MAP`) cập nhật trạng thái VanoHub và ghi `ActivityLog` (`"Đồng bộ từ CVAT"`); nếu CVAT là `validation/rejected` sẽ tự tăng `rework_round` và kiểm tra escalation.<br>• **Từ QC2 trở đi (`pending_qc2`, `approved`, `delivered`):** VanoHub luôn ưu tiên — đồng bộ CVAT không ghi đè trạng thái.<br>• Ánh xạ tài khoản khi nhập job: ưu tiên `User.cvat_username`, sau đó `User.username`. |
| VH04 | Mất kết nối | • Endpoint kiểm tra kết nối `GET /api/cvat/status/` (timeout 5s; tải danh sách task 10s; mặc định client 15s).<br>• Khi CVAT không kết nối được hoặc trả lỗi 401/404/5xx, backend trả HTTP `502 Bad Gateway` kèm thông báo dễ hiểu, đồng thời lưu `last_sync_status = "error"`, `last_sync_error` và `last_synced_at` lên Batch.<br>• Người dùng vẫn thao tác bình thường các luồng nội bộ VanoHub và thử đồng bộ lại khi CVAT khôi phục. |
| VH05 | Quy mô và hiệu năng | • API danh sách phân trang chuẩn `page_size = 50` (tối đa `500`), đánh chỉ mục DB trên các truy vấn trọng yếu (`project+status`, `project+created_at`, `recipient+project+is_read`, `project+created_by+status`).<br>• Sử dụng khóa hàng nguyên tử (`select_for_update` / `skip_locked`) cho `claim`, `start`, `submit`, `qc1`, `confirm-qc2`, `audit.complete`, `guideline.publish`.<br>• *Cần chốt SLA:* Số người dùng đồng thời tối đa và ngưỡng phản hồi mục tiêu (P95) khi đưa vào sản xuất. |
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
| `manage_data` | Tạo/sửa/khóa Dataset & Batch; nhập/đồng bộ CVAT (`import-cvat`, `sync-cvat`); xác nhận batch chuyển QC2 (`confirm-qc2`) | ✓ | — | — | — |
| `manage_jobs` | Giao/giao lại job, đổi deadline, khóa/mở khóa job, chuyển batch (`bulk-move-batch`), gỡ escalation, xử lý `AnnotatorRequest` | ✓ | — | — | — |
| `manage_team` | Gán thêm vai trò (`QC2`, `QC1`, `Annotator`) trong dự án; quản lý nhóm phân bổ, sức chứa (`capacity`), điều chuyển & xem tải | ✓ | — | — | — |
| `manage_settings` | Chỉnh cấu hình rework, `escalation_policy`, WIP limit, chiến thuật sampling QC2, ngưỡng chất lượng & chỉ tiêu KPI | ✓ | — | — | — |
| `manage_audits` | Xem trước mẫu QC2 (`preview`), tạo đợt audit, phân lại auditor, chốt quyết định batch (`accept` / `reject` / `partial_reject`) | ✓ | — | — | — |
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
| `review_needed` | • Annotator nộp bài (`submit`)<br>• 100% job trong batch đạt QC1<br>• PM xác nhận chuyển batch sang QC2 | • QC1 được giao *(hoặc tất cả QC1 dự án nếu ở pool)*<br>• **PM** dự án<br>• **PM & QC2** dự án | **Có** *(gỡ ghim khi QC1 xử lý xong)* | Luôn bật | `/qc1/work` · `/batches` · `/audits` |
| `rework` | • QC1 trả sửa (`qc1.reject`)<br>• QC2 trả sửa (`qc2.reject`)<br>• PM trả batch/tầng khi chốt audit | • **Annotator** của job<br>• **QC1** phụ trách *(khi bị QC2/PM trả sửa)* | **Có** *(trên Annotator; gỡ ghim khi nộp lại)* | `notify_rework` *(Annotator)* | `/annotator/jobs/{job_id}` · `/qc1/work` |
| `escalated` | Job vượt `max_rework_rounds` (từ QC1 reject, QC2 reject, PM audit reject hoặc đồng bộ CVAT) | Toàn bộ **PM** của dự án | **Có** | Luôn bật | `/jobs?escalated=1` |
| `deadline` | Job đang mở sắp đến hạn (`≤ 24h`) hoặc đã quá hạn *(tính động khi tải thông báo)* | Annotator / QC1 / QC2 đang giữ job và **PM** dự án | **Có** | `notify_deadline` | Trang công việc tương ứng theo vai trò |
| `dispute` | • Annotator gửi `error_dispute` hoặc `data_issue`<br>• PM kết luận `resolved` / `rejected` | • **PM** phụ trách + Annotator tạo yêu cầu<br>• Annotator tạo yêu cầu *(khi có kết luận; gỡ ghim yêu cầu cũ)* | **Có** *(khi đang chờ PM)* | `notify_request_updates` *(Annotator)* | `/annotator/requests` |
| `qc_pass` | QC1 duyệt đạt job (`qc1.pass`) | **Annotator** của job | Không | `notify_qc_pass` | `/annotator/jobs/{job_id}` |
| `announcement` | PM gửi thông báo dự án (`Announcement`) | Thành viên thuộc `target_roles` / `target_team` đích *(rỗng = toàn dự án)* | Không | Luôn bật | `/announcements` |

---

## CHI TIẾT CHỈ SỐ CHẤT LƯỢNG CHÍNH (FPY, DEFECT ERROR RATE, QUALITY CL)

### 1. First Pass Yield — FPY tại QC1 (`CL01`)
- **Công thức chuẩn:**
  $$\text{FPY}_{\text{QC1}} = \frac{\text{Số job đạt QC1 ngay lần kiểm đầu}}{\text{Tổng số job đã có kết quả kiểm QC1 lần đầu}} \times 100\%$$
- **Hiện trạng (`provisional`):** `backend/analytics/views.py` hiện tính `rework_round == 0` trên tập job đã đạt `QC1_PASSED` trở lên (`REACHED_QC2`). Các job **trượt QC1 ngay lần đầu và vẫn đang ở `REWORK` / `ANNOTATING`** hiện bị lọt khỏi mẫu số, làm FPY bị cao giả tạo.
- **Khắc phục cần làm:** Lưu thêm trường bất biến `first_qc1_result` (`pass` \| `reject`) trên `Job` ngay tại quyết định QC1 đầu tiên (hoặc truy vấn sự kiện `qc1.pass` / `qc1.reject` đầu tiên theo từng job từ `ActivityLog`).

### 2. Defect Error Rate — Tỷ lệ đối tượng lỗi (`CL02`)
- **Công thức chuẩn:**
  $$\text{Defect Error Rate} = \frac{\text{Số cuboid (object-frame) duy nhất có lỗi xác nhận}}{\text{Tổng số cuboid (object-frame) đã kiểm}} \times 100\%$$
- **Hiện trạng (`pending_definition`):** Chưa trả số thực trên API tổng quan (`value = None`).
- **2 thiếu hụt dữ liệu cần xử lý:**
  1. **Đếm đúng số cuboid theo frame từ CVAT:** `CvatClient.count_job_objects()` hiện trả `len(shapes) + len(tracks)` (đếm số *track* vật thể thay vì tổng số *cuboid/object-frame*). Cần bung khoảng frame hoạt động của từng CVAT track (từ keyframe cho tới `outside=True`) cộng với các shape đơn lẻ.
  2. **Khử trùng mục tiêu lỗi:** `ReviewError.location` hiện là chuỗi tự do nên 2 lỗi trên cùng 1 cuboid dễ bị đếm trùng. Cần thêm trường có cấu trúc `frame_number` + `cvat_object_id` (và quy ước xử lý lỗi thiếu đối tượng — False Negative — vào mẫu số `checked_cuboids + missing_cuboids` để tỷ lệ luôn nằm trong `[0%, 100%]`).

### 3. Quality CL (`CL11`) và phân biệt `Edge` với `AQL`
- **Công thức chuẩn:**
  $$\text{Quality CL} = \frac{\text{Cuboid}_{\text{Pass}} + \text{Cuboid}_{\text{Edge}}}{\text{Tổng số cuboid đã kiểm}} \times 100\%$$
- **Phân biệt `Edge` và `AQL`:**
  - **`AQL` (Acceptable Quality Limit)** là **ngưỡng chấp nhận ở cấp batch** (ví dụ: chấp nhận batch khi Defect Error Rate $\le 2\%$ hoặc Quality CL $\ge 98\%$), tương ứng với `quality_cl_threshold` và `defect_rate_threshold` trên `Project`.
  - **`Edge`** **không phải** độ lệch AQL, mà là **mức chấm ở cấp từng cuboid** trong thang 3 bậc **`Pass` / `Edge` / `Fail`**:
    - *Nghĩa phổ biến nhất (Borderline / Edge-case):* Cuboid có sai lệch rất nhẹ nằm sát biên dung sai hoặc rơi vào trường hợp hướng dẫn chưa rõ/che khuất mạnh/điểm LiDAR thưa — QC đánh dấu `Edge` để theo dõi và bổ sung guideline mà không tính trượt (`Fail`) vào tỷ lệ chất lượng.
    - *Nghĩa đặc thù dự án (Spatial FOV edge):* Đối tượng nằm sát mép tầm nhìn camera hoặc rìa tầm quét LiDAR được nới lỏng dung sai và cộng chung với `Pass`.
- **Hiện trạng (`pending_definition`):** CVAT không có trạng thái gốc `Pass / Edge / Fail` trên từng cuboid.
- **3 điểm PM cần chốt trước khi lập trình `CL11`:**
  1. Quy ước ghi nhận `Edge`: thêm trường `verdict` (`edge` \| `fail`) trên `ReviewError` (cuboid không gắn lỗi mặc định là `Pass`), ánh xạ từ mức độ lỗi (`minor = Edge`, `major/critical = Fail`), hay đồng bộ từ tag/attribute của CVAT.
  2. Trọng số của `Edge` trong tử số `Quality CL` (`1.0` như công thức `(Pass + Edge) / Tổng`, hay hệ số từng phần như `0.5`).
  3. `Edge` có được tính vào tử số của `Defect Error Rate (CL02)` hay chỉ tính `Fail`.

---

## TỔNG HỢP CÔNG THỨC TÍNH TOÁN TRONG PLATFORM

> **Ký hiệu trạng thái triển khai:** `Đã có` (đang chạy đúng nghiệp vụ) · `Tạm tính` (đang chạy công thức provisional) · `Chờ chốt` (`pending_definition`) · `Chưa làm` (chưa triển khai trong codebase).

| Mã | Chỉ số | Công thức / quy tắc tính | PM | QC2 | QC1 | Anno | Cách trình bày | Mức | Hiện trạng |
| --- | --- | --- | :---: | :---: | :---: | :---: | --- | :---: | --- |
| **SL01** | Sản lượng Anno lần đầu | Tổng object-frame nộp hợp lệ ở vòng làm đầu (`rework_round = 0`) trong kỳ | ✓ | — | — | ✓ | Thẻ số; biểu đồ cột theo ngày | P1 | Đã có |
| **SL02** | Sản lượng QC | Số lượt hoàn tất kiểm job hợp lệ (`qc1.pass/reject`, `qc2 pass/reject`); tách QC1/QC2 | ✓ | ✓ | ✓ | — | Thẻ thực tế/chỉ tiêu; cột phân nhóm | P1 | Đã có *(chưa tách kiểm đầu/lại)* |
| **SL03** | Sản lượng rework Anno | Tổng object-frame nộp lại trong vòng sửa (`rework_round > 0`) | ✓ | — | — | ✓ | Phần rework trong cột sản lượng | P1 | Đã có |
| **SL04** | Sản lượng theo người thực hiện | Tổng phần việc ghi nhận theo từng `actor`; giao lại không chuyển sản lượng cũ | ✓ | ✓ | ✓ | ✓ | Bảng chi tiết người–job–vòng xử lý | P1 | Đã có |
| **SL05** | Sản lượng dự án / nhóm | Tổng sản lượng thành viên trong phạm vi, tách từng vai trò và đơn vị | ✓ | — | — | — | Cột theo ngày / nhóm phân bổ; bộ lọc vai trò | P1 | Tạm tính |
| **SL06** | Tổng sản lượng tính KPI Anno | `SL01 + SL03` trong ngày/kỳ theo múi giờ người dùng | ✓ | — | — | ✓ | Thẻ KPI chính; bấm xem phần đóng góp | P1 | Đã có |
| **KPI01** | Chỉ tiêu trong kỳ | Chỉ tiêu cấu hình trên `Project` (`kpi_*_target`) theo ngày công | ✓ | ✓ | ✓ | ✓ | Đường mục tiêu trên biểu đồ; thông tin kỳ | P1 | Đã có *(chưa có lịch sử đổi giữa kỳ)* |
| **KPI02** | Tỷ lệ đạt KPI | Sản lượng đủ điều kiện ÷ chỉ tiêu cùng kỳ × 100% | ✓ | ✓ | ✓ | ✓ | Thẻ % + thực tế/chỉ tiêu; thanh tiến độ | P1 | Đã có |
| **KPI03** | Sản lượng còn thiếu | `max(0, chỉ tiêu − sản lượng thực tế)` | ✓ | ✓ | ✓ | ✓ | Số phụ trong thẻ KPI | P1 | Đã có |
| **KPI04** | Sản lượng vượt chỉ tiêu | `max(0, sản lượng thực tế − chỉ tiêu)` | ✓ | ✓ | ✓ | ✓ | Số phụ khi đã đạt KPI | P1 | Đã có |
| **KPI05** | Tỷ lệ thành viên đạt KPI | Thành viên đạt chỉ tiêu ÷ thành viên đủ điều kiện đánh giá × 100% | ✓ | — | — | — | Thẻ % + số người đạt/tổng | P1 | Chưa làm |
| **KPI06** | Thành viên dưới ngưỡng KPI | Thành viên dưới ngưỡng X ÷ thành viên được đánh giá × 100%; đề xuất X = 50% | ✓ | — | — | — | Danh sách cần hỗ trợ + số đếm | P1 | Chưa làm |
| **KPI07** | Tỷ lệ đạt khoán | Sản lượng đủ điều kiện khoán ÷ chỉ tiêu khoán × 100% | ✓ | ✓ | ✓ | ✓ | Thẻ trong tab KPI kỳ; chưa tính tiền công | P1 | Chưa làm |
| **KPI08** | Chênh lệch hai kỳ | Giá trị kỳ này − giá trị kỳ trước | ✓ | ✓ | ✓ | ✓ | Số tăng/giảm cạnh chỉ số chính | P1 | Đã có *(QC1/QC2)* |
| **KPI09** | Tỷ lệ tăng/giảm hai kỳ | `(Kỳ này − kỳ trước) ÷ kỳ trước × 100%`; kỳ trước = 0 thì không tính % | ✓ | ✓ | ✓ | ✓ | Nhãn tăng/giảm, ghi rõ kỳ so sánh | P1 | Đã có *(QC1/QC2)* |
| **KPI10** | Xếp hạng sản lượng | Sắp giảm dần trong cùng vai trò, dự án và kỳ; cá nhân chỉ thấy hạng của mình | ✓ | ✓ | ✓ | ✓ | PM xem bảng; cá nhân chỉ thấy hạng mình | P2 | Đã có *(Anno & Team)* |
| **KPI11** | Chỉ tiêu dự án / nhóm | Tổng chỉ tiêu thành viên trong phạm vi, cùng đơn vị và kỳ | ✓ | — | — | — | Đường chỉ tiêu cạnh SL05 | P1 | Chưa làm |
| **NS01** | Thời gian làm thực tế | Tổng thời lượng phiên làm hợp lệ (`ANNOTATING → PENDING_QC1`) | ✓ | ✓ | ✓ | ✓ | Thẻ giờ trong tab năng suất | P2 | Tạm tính *(Anno)* |
| **NS02** | Thời gian chờ/tạm dừng | Tổng thời lượng chờ/tạm dừng đã ghi nhận, phân theo nguyên nhân | ✓ | ✓ | ✓ | ✓ | Thanh ngang theo nguyên nhân; timeline job | P2 | Chưa làm |
| **NS03** | Năng suất Anno | Sản lượng Anno hợp lệ ÷ giờ làm thực tế; tách lần đầu/rework | ✓ | — | — | ✓ | Đường xu hướng object-frame/giờ | P2 | Tạm tính |
| **NS04** | Năng suất QC | Lượt kiểm job hoàn tất ÷ giờ kiểm thực tế; tách kiểm đầu/kiểm lại | ✓ | ✓ | ✓ | — | Đường xu hướng job/giờ | P2 | Chờ chốt |
| **NS05** | Thời gian trung bình/đơn vị | Giờ làm thực tế ÷ số đơn vị hoàn thành tương ứng | ✓ | ✓ | ✓ | ✓ | Thẻ phụ; bảng theo loại công việc | P2 | Chưa làm |
| **NS06** | Sản lượng trung bình/ngày công | Tổng sản lượng ÷ số ngày công có hoạt động | ✓ | ✓ | ✓ | ✓ | Thẻ trung bình trong tab năng suất | P1 | Đã có *(Anno)* |
| **NS07** | Thời gian chờ giữa hai bước | Thời điểm bắt đầu bước sau − thời điểm sẵn sàng chuyển bước | ✓ | ✓ | ✓ | ✓ | Thanh ngang trung vị theo bước; danh sách chờ lâu | P1 | Chưa làm |
| **NS08** | Thời gian hoàn tất toàn luồng | Thời điểm PM chấp nhận − thời điểm lần đầu giao Anno | ✓ | — | — | — | Xu hướng trung vị theo kỳ; chi tiết từng job | P1 | Chưa làm |
| **CL01** | FPY tại QC1 | Job Pass ở lần QC1 đầu ÷ job có kết quả QC1 đầu × 100% | ✓ | — | ✓ | ✓ | Thẻ % + đạt/tổng; đường xu hướng tuần | P1 | Tạm tính *(cần sửa mẫu số)* |
| **CL02** | Tỷ lệ đối tượng lỗi (Defect Error Rate) | Object-frame duy nhất có lỗi xác nhận ÷ tổng object-frame đã kiểm × 100% | ✓ | ✓ | ✓ | — | Thẻ % có cỡ mẫu; bấm xem lỗi | P1 | Chờ chốt |
| **CL03** | Tỷ lệ đối tượng đạt trong mẫu | Object-frame không lỗi ÷ tổng object-frame đã kiểm × 100% | ✓ | ✓ | ✓ | — | Thông tin phụ trong chi tiết audit | P1 | Chờ chốt |
| **CL04** | Số lỗi theo loại/mức độ | Đếm `ReviewError` đã ghi theo loại lỗi và mức độ | ✓ | ✓ | ✓ | ✓ | Thanh ngang top lỗi; Anno xem lỗi trên job mình | P1 | Đã có |
| **CL05** | Tỷ lệ đối tượng lỗi theo mức độ | Object-frame có lỗi mức X ÷ tổng object-frame đã kiểm × 100% | ✓ | ✓ | ✓ | — | Thanh phân bố; dùng mức nặng nhất nếu tránh chồng lặp | P1 | Chờ chốt |
| **CL06** | Số lỗi QC1 bỏ sót | Đếm lỗi QC2 xác nhận trên job đã qua QC1 (`qc1_missed_errors` / `qc2_escape_errors`) | ✓ | ✓ | ✓ | — | Thẻ số + bảng bằng chứng | P1 | Đã có |
| **CL07** | Tỷ lệ job có lỗi QC1 bỏ sót | Job audit có lỗi QC1 bỏ sót ÷ job đã audit thuộc trách nhiệm QC1 đó × 100% | ✓ | ✓ | ✓ | — | Thẻ % + số job lỗi/số job audit | P1 | Chưa làm |
| **CL08** | Tỷ lệ lỗi QC2 bỏ sót | Object-frame có lỗi QC2 bỏ sót xác nhận ÷ object-frame tái kiểm × 100% | ✓ | ✓ | — | — | Thẻ % + bảng kết luận tái kiểm độc lập | P2 | Chưa làm |
| **CL09** | Tỷ lệ kết luận lỗi bị hủy | Kết luận lỗi bị hủy (`error_dispute` resolved) ÷ kết luận lỗi đã phân xử × 100% | ✓ | ✓ | ✓ | — | Bảng phân xử; chỉ số phụ | P2 | Chưa làm |
| **CL10** | Batch được chấp nhận lần đầu | Batch được PM `accept` ở đợt audit đầu ÷ batch có đợt audit đầu đã chốt × 100% | ✓ | ✓ | — | — | Thẻ % + đường xu hướng | P1 | Chưa làm |
| **CL11** | Quality CL | `(Cuboid Pass + Cuboid Edge) ÷ Tổng số cuboid đã kiểm × 100%` | ✓ | ✓ | ✓ | ✓ | Thẻ % kèm tổng cuboid đã kiểm | P1 | Chờ chốt *(quy ước Edge)* |
| **CL12** | Điều kiện đạt/chặn chất lượng | Áp ngưỡng dự án; lỗi nghiêm trọng chưa xử lý thì chặn chấp nhận/bàn giao | ✓ | ✓ | ✓ | ✓ | Nhãn Đạt/Chưa đạt + lý do chặn | P1 | Chưa làm |
| **CL13** | FPY toàn luồng | Job được PM chấp nhận không qua rework ÷ job đã được PM chấp nhận × 100% | ✓ | — | — | — | Thẻ phụ có số job còn mở; không thay CL01 | P2 | Chưa làm |
| **RW01** | Số vòng rework | Đếm quyết định trả về `rework` (`Job.rework_round`) | ✓ | ✓ | ✓ | ✓ | Nhãn số vòng trên job + timeline | P1 | Đã có |
| **RW02** | Tỷ lệ job bị rework | Job duy nhất có `rework_round > 0` ÷ tổng job trong nhóm đánh giá × 100% | ✓ | ✓ | ✓ | ✓ | Thẻ % + xu hướng; lọc ra danh sách job | P1 | Tạm tính |
| **RW03** | Lượt trả trung bình/job | Tổng lượt trả sửa ÷ số job trong nhóm đánh giá | ✓ | ✓ | ✓ | ✓ | Chỉ số phụ, đơn vị lượt/job | P1 | Chưa làm |
| **RW04** | Khối lượng đang chờ sửa | Tổng lỗi / object-frame đang chờ sửa trên job ở trạng thái `rework` | ✓ | ✓ | ✓ | ✓ | Thẻ khối lượng + danh sách sửa | P1 | Tạm tính *(theo số ReviewError)* |
| **RW05** | Thời gian một vòng sửa | Thời điểm nộp lại − thời điểm trả sửa | ✓ | ✓ | ✓ | ✓ | Timeline từng vòng | P1 | Chưa làm |
| **RW06** | Thời gian sửa trung bình | Tổng thời gian vòng sửa hoàn tất ÷ số vòng sửa hoàn tất | ✓ | ✓ | ✓ | ✓ | Thẻ phụ + xu hướng | P1 | Chưa làm |
| **RW07** | Vượt giới hạn rework | `rework_round > max_rework_rounds` → `is_escalated = True`, báo PM (`block` hoặc `warn_only`) | ✓ | ✓ | ✓ | ✓ | Thẻ số job vượt vòng + danh sách ưu tiên | P1 | Đã có |
| **AU01** | Cỡ mẫu QC2 | Hiện tại: `ceil(job pending_qc2 × sampling_rate ÷ 100)` *(Random/Stratified cấp job; cấp frame chưa làm)* | ✓ | ✓ | — | — | Số mẫu/tổng đơn vị trong cấu hình và audit | P1 | Đã có *(cấp job)* |
| **AU02** | Tỷ lệ lấy mẫu thực tế | Đơn vị được chọn ÷ đơn vị đủ điều kiện × 100% | ✓ | ✓ | — | — | Nhãn % kèm số lượng, phân biệt với % cài đặt | P1 | Đã có *(cấp job)* |
| **AU03** | Tiến độ audit | Mẫu đã có kết quả ÷ tổng mẫu của đợt audit × 100% | ✓ | ✓ | — | — | Thanh phân đoạn đạt/không đạt/chưa kiểm | P1 | Đã có |
| **AU04** | Mẫu còn chờ | Tổng mẫu phải kiểm − mẫu đã có kết quả (`pending`) | ✓ | ✓ | — | — | Thẻ số + danh sách mẫu chưa kiểm | P1 | Đã có |
| **AU05** | Tỷ lệ mẫu đạt | Mẫu `Pass` ÷ mẫu đã có kết quả × 100% (`qc2_pass_rate`) | ✓ | ✓ | — | — | Chỉ số phụ, luôn hiển thị cùng AU03 | P1 | Đã có |
| **AU06** | Tỷ lệ audit đạt | Audit chốt `accept` ÷ tổng audit đã chốt × 100% | ✓ | ✓ | — | — | Thẻ % theo kỳ + xu hướng | P1 | Chưa làm |
| **AU07** | Kết luận audit/batch | Chấm đủ 100% mẫu rồi PM chọn `accept` / `reject` / `partial_reject` + lý do | ✓ | ✓ | — | — | Nhãn kết luận + quyết định theo tầng | P1 | Đã có |
| **TD01** | Khối lượng được giao | Đếm job; cộng `frame_count` / `object_count` / `target_object_count` | ✓ | ✓ | ✓ | ✓ | Thẻ số + bảng công việc | P1 | Đã có |
| **TD02** | Số job theo trạng thái | Đếm job hiện tại ở từng `JobStatus` và theo stage (`JobQueueView`) | ✓ | ✓ | ✓ | ✓ | Thẻ số / thanh phân bố; bấm mở hàng đợi | P1 | Đã có |
| **TD03** | Tiến độ Anno trong job | `object_count ÷ target_object_count × 100%` (hoặc `100%` khi đã nộp) | ✓ | — | ✓ | ✓ | Thanh tiến độ trên dòng job | P1 | Đã có |
| **TD04** | Tiến độ QC trong job | Đơn vị đã kiểm ÷ đơn vị phải kiểm × 100% | ✓ | ✓ | ✓ | — | Thanh tiến độ; QC2 dùng phạm vi mẫu | P1 | Chưa làm *(cấp đơn vị trong job)* |
| **TD05** | Tiến độ qua từng bước | Job đã Pass bước và chưa mở lại ÷ tổng job phải qua bước đó × 100% | ✓ | ✓ | ✓ | ✓ | Các thanh tiến độ Anno/QC1/QC2/PM | P1 | Tạm tính *(theo stage)* |
| **TD06** | Tiến độ toàn luồng | Job `approved` + `delivered` ÷ tổng job × 100% | ✓ | — | — | — | Thẻ % + hoàn tất/tổng; bảng batch/dự án | P1 | Tạm tính |
| **TD07** | Khối lượng còn lại | Khối lượng phải làm − khối lượng hoàn tất hợp lệ | ✓ | ✓ | ✓ | ✓ | Số phụ cạnh tiến độ; danh sách việc còn lại | P1 | Đã có |
| **TD08** | Tỷ lệ sẵn sàng bàn giao | Batch đủ điều kiện giao (`candidates.ready`) hoặc job `approved+delivered` ÷ tổng × 100% | ✓ | ✓ | — | — | Thanh tiến độ + danh sách batch sẵn sàng giao | P1 | Đã có *(cấp batch)* |
| **TD09** | Tỷ lệ đã bàn giao | Batch/Dataset đã `delivered` ÷ tổng cần giao × 100% | ✓ | — | — | — | Thẻ % + lịch sử bàn giao | P1 | Đã có *(cấp batch)* |
| **TD10** | Tải công việc hiện tại | Số job đang giữ / sức chứa (`capacity` / `wip_limit`), job sắp hạn, escalated | ✓ | ✓ | ✓ | ✓ | Bảng tải thành viên: đang làm, sắp hạn, bị chặn | P1 | Đã có |
| **TD11** | Số người đang có việc | Số người duy nhất đang giữ ≥ 1 job ở `OPEN_STATUSES` (`active_members`) | ✓ | — | — | — | Thẻ số; không gắn nhãn “đang online” | P1 | Đã có |
| **TD12** | Tiền xử lý/lên CVAT | Frame đã tiền xử lý hoặc đã lên CVAT ÷ tổng frame tương ứng × 100% | ✓ | — | — | — | Hai thanh riêng trên dataset | P1 | Chưa làm |
| **TD13** | Việc cần quyết định/xử lý | Đếm yêu cầu mở: batch chờ `confirm-qc2`, audit chờ chốt, `AnnotatorRequest`, job escalated | ✓ | ✓ | ✓ | ✓ | Hộp việc cần xử lý; cá nhân thấy yêu cầu mình gửi | P1 | Đã có |
| **DH01** | Deadline hiệu lực | Mốc giờ `deadline` trên Batch / Job kèm lịch sử điều chỉnh trong `ActivityLog` | ✓ | ✓ | ✓ | ✓ | Cột deadline + lịch sử điều chỉnh | P1 | Đã có |
| **DH02** | Thời gian còn lại | `deadline − hiện tại` (`hours_remaining`) | ✓ | ✓ | ✓ | ✓ | Nhãn “Còn … giờ/ngày” trên công việc | P1 | Đã có |
| **DH03** | Thời gian quá hạn | Chưa xong: `max(0, hiện tại − hạn)`; đã xong: `max(0, hoàn tất − hạn)` | ✓ | ✓ | ✓ | ✓ | Nhãn đỏ + danh sách quá hạn (`overdue=1`) | P1 | Đã có |
| **DH04** | Sắp đến hạn | `0 < thời gian còn lại ≤ 24 giờ` (`due_soon=1`) | ✓ | ✓ | ✓ | ✓ | Nhãn cảnh báo + bộ lọc sắp hạn | P1 | Đã có |
| **DH05** | Kết quả đúng hạn | Thời điểm hoàn tất `≤ deadline` | ✓ | ✓ | ✓ | ✓ | Nhãn Đúng hạn/Trễ | P1 | Đã có *(Anno)* |
| **DH06** | Tỷ lệ hoàn tất bước đúng hạn | Lượt nộp đúng hạn ÷ lượt nộp có deadline × 100% (`on_time_pct`) | ✓ | ✓ | ✓ | ✓ | Thẻ % + đúng hạn/tổng; xu hướng | P1 | Đã có *(Anno)* |
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
| PM | Hàng chờ quyết định & xử lý | Batch chờ xác nhận chuyển QC2 (`confirm-qc2`), batch chờ chốt sau audit (`accept`/`reject`/`partial_reject`), phản hồi lỗi & dữ liệu bị chặn (`AnnotatorRequest`), job vượt vòng rework (`escalated`) | TD13, TD05, AU07, CL12, RW07 | **Bảng thao tác ưu tiên**, có kết quả audit, thời gian chờ và nút xử lý | P1 |
| PM | Điều phối & phân công nhân sự | Job theo bước (`JobQueue`), người đang giữ job, tải/sức chứa, deadline, KPI và sản lượng thành viên | TD02, TD10, TD01, DH01, SL05, KPI02, KPI03, KPI11 | **Bảng tải thành viên + thanh phân bố trạng thái**; thao tác giao/giao lại & đổi hạn | P1 |
| PM | Chất lượng dự án | FPY QC1, tỷ lệ đối tượng lỗi (Defect Error Rate), Quality CL, tỷ lệ job rework, top lỗi phổ biến, job vượt vòng sửa | CL01, CL02, CL11, CL04, RW02, RW07 | **Thẻ % + thanh ngang top lỗi + danh sách rework** | P1 |
| PM | Bàn giao | Batch sẵn sàng giao (`candidates`), lịch sử đã giao (`Delivery`), người nhận, đường dẫn đầu ra, phản hồi khách hàng | TD08, TD09, DH07 | **Bảng bàn giao** có trạng thái sẵn sàng, deadline và nút ghi nhận bàn giao | P1 |
| PM | Dự báo & phân tích năng suất | ETA, thời gian còn lại, độ trễ dự kiến, thời gian chờ giữa các bước, tốc độ Anno/QC, tổng quan các dự án phụ trách | DB02, DB03, DB04, NS07, NS03, NS04, RW06, DA01, DA02, DA03 | **Các cột dự báo trong bảng tiến độ** (ghi rõ “Ước tính”) + **tab phân tích năng suất** | P2 |
| **QC2** | Chỉ số đầu trang | Audit đang làm; mẫu còn chờ; lỗi nghiêm trọng còn mở; sản lượng/chỉ tiêu | TD13, AU04, CL12, SL02, KPI02 | **4 thẻ**, lỗi nghiêm trọng có màu cảnh báo | P1 |
| QC2 | Audit đang thực hiện | Danh sách job mẫu được giao, tỷ lệ lấy mẫu, số đạt/không đạt/chưa kiểm, deadline, nút mở CVAT | AU01, AU02, AU03, AU05, DH01 | **Bảng audit + thanh tiến độ phân đoạn**, chấm Pass/Reject kèm `ReviewError` | P1 |
| QC2 | Chất lượng mẫu kiểm | Tỷ lệ đối tượng lỗi, phân bố loại/mức độ lỗi, lỗi QC1 bỏ sót | CL02, CL04, CL05, CL06 | **Thẻ % kèm cỡ mẫu + thanh ngang loại lỗi** | P1 |
| QC2 | Bàn giao kết quả cho PM | Đợt audit đã chấm đủ mẫu, trạng thái chờ PM chốt hoặc kết luận `accept`/`reject`/`partial_reject` | AU07, TD13 | **Danh sách đợt audit**, hiển thị quyết định và thời điểm chốt | P1 |
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
