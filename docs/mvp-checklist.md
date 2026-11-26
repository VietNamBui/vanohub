# Danh sách tính năng MVP — VanoHub

> **Mô hình tổ chức phẳng — 4 vai trò:** `PM` (kiêm `QC2`), `QC2` (QC Level 2), `QC1` (QC Level 1), `Annotator` — loại bỏ hoàn toàn `Director` và `Team Leader`.  
> Đồng bộ chi tiết với [platform-spec.md](./platform-spec.md).

| Nhóm | Phạm vi MVP đề xuất | Giá trị mang lại |
| --- | --- | --- |
| **1. Tài khoản và phân quyền** | Đăng nhập JWT; phân 4 vai trò phẳng **PM (kiêm QC2), QC2, QC1, Annotator**; giới hạn dữ liệu theo dự án và vai trò (`404` ngoài dự án); thực thi luật bốn mắt | Mỗi người thấy và thao tác đúng phạm vi |
| **2. Kết nối CVAT** | Kiểm tra kết nối, lấy danh sách task/job và thông tin cần thiết; ánh xạ `1 Batch ↔ 1 CVAT Task`, `1 Job ↔ 1 CVAT Job`; mở đúng job trên CVAT; hiển thị trạng thái đồng bộ và lỗi | Dùng được với công việc thật |
| **3. Quản lý dự án, nhân sự và batch** | Thông tin dự án, PM phụ trách, thành viên & nhóm phân bổ sức chứa (không có Team Leader); Data Query (`bulk-move-batch`), dataset, nhóm job vào batch; guidelines có phiên bản | Có cấu trúc để giao và theo dõi công việc |
| **4. Giao việc và hàng đợi cá nhân** | PM giao/giao lại job hoặc Annotator tự nhận (`claim`) theo giới hạn WIP; mỗi vai trò xem hàng đợi ưu tiên (DB06), trạng thái và deadline; mở job trên CVAT để làm | Thay thế phần giao việc và tra cứu thủ công |
| **5. QC1 và rework** | Giao người kiểm hoặc nhận từ pool; đánh dấu đạt (`qc1_passed`)/trả sửa (`rework`); ghi loại lỗi, mức độ, vị trí và mô tả + phạm vi sửa (`partial`/`full`); theo dõi vòng sửa; **báo PM khi vượt giới hạn** (`block` hoặc `warn_only`); luồng khiếu nại lỗi / báo dữ liệu bị chặn gửi thẳng **PM** | Quản lý được vòng kiểm và sửa lỗi |
| **6. Xác nhận chuyển QC2** | Một cách duyệt thống nhất: **PM xác nhận theo batch (`confirm-qc2`)** sau khi 100% job trong batch đã đạt QC1 | Luồng bàn giao rõ ràng, dễ vận hành |
| **7. QC2 và quyết định batch** | Chọn các job cần audit theo quy tắc đã chốt (`Random` / `Stratified`, có xem trước + `seed`); QC2 chấm `Pass`/`Reject` từng mẫu; **PM** chốt `accept` / `reject` / `partial_reject` theo tầng và ghi lý do | Có bước kiểm soát chất lượng trước bàn giao |
| **8. Deadline và tổng quan tiến độ** | Đặt hạn batch/job (đổi hạn bắt buộc ghi lý do); hiển thị sắp đến hạn (`≤ 24h`), quá hạn; thống kê số job theo trạng thái/stage; bấm vào để xem danh sách | **PM** biết chỗ nào đang tắc để xử lý |
| **9. Thông báo và lịch sử** | Thông báo hợp nhất trong app khi được giao việc, bị trả sửa, cần duyệt, escalated, sắp/quá hạn, cập nhật yêu cầu (`is_pinned_pending` treo tới khi xử lý); lưu `ActivityLog` bất biến ai thay đổi gì, lúc nào | Giảm bỏ sót và truy được nguyên nhân |
| **10. Theo dõi bàn giao** | Danh sách batch đủ điều kiện (`100% approved`, không còn audit mở); **PM** ghi nhận bàn giao (`Delivery`), thời gian, người nhận, đường dẫn đầu ra, phản hồi khách hàng và tự khóa batch/job | Theo dõi được đến điểm kết thúc công việc |

---

## Ghi chú chỉ số chất lượng chính (chi tiết tại [platform-spec.md](./platform-spec.md#chi-tiết-chỉ-số-chất-lượng-chính-fpy-defect-error-rate-quality-cl))

- **First Pass Yield (`CL01`):** $\text{Job đạt QC1 ngay lần kiểm đầu} \div \text{Tổng job đã có kết quả kiểm QC1 lần đầu} \times 100\%$ *(tạm tính — cần sửa mẫu số bao gồm job trượt lần đầu còn ở `REWORK`)*.
- **Defect Error Rate (`CL02`):** $\text{Số cuboid (object-frame) duy nhất có lỗi xác nhận} \div \text{Tổng số cuboid đã kiểm} \times 100\%$ *(chờ chốt — cần bung track thành object-frame từ CVAT và tách `frame_number` + `cvat_object_id` trên `ReviewError`)*.
- **Quality CL (`CL11`):** $(\text{Cuboid Pass} + \text{Cuboid Edge}) \div \text{Tổng số cuboid đã kiểm} \times 100\%$ *(chờ chốt — `Edge` là mức chấm cấp cuboid trong thang `Pass`/`Edge`/`Fail`, khác với `AQL` là ngưỡng chất lượng cấp batch)*.
