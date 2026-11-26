"""Client gọi CVAT REST API (tích hợp trên nền cvat-base gốc, chỉ đọc ở giai đoạn MVP).

Cấu hình qua biến môi trường (backend/.env):
- CVAT_URL: địa chỉ backend gọi tới, vd. http://localhost:8080
- CVAT_ACCESS_TOKEN (Personal Access Token) hoặc CVAT_USERNAME + CVAT_PASSWORD
- CVAT_ORGANIZATION (tùy chọn): slug organization trên CVAT, gửi qua header X-Organization
"""

import requests
from django.conf import settings
from pydantic import ValidationError as PydanticValidationError

from .schemas import CvatAboutPayload, CvatAnnotationsPayload, CvatJobMetaPayload, CvatJobPayload, CvatTaskPayload

MAX_PAGES = 1000


class CvatError(Exception):
    """Lỗi khi gọi CVAT — view sẽ chuyển thành thông báo dễ hiểu cho người dùng."""


class CvatNotFoundError(CvatError):
    """Tài nguyên không còn tồn tại trên CVAT (HTTP 404)."""


def _validate_model(model_cls, payload, label: str):
    try:
        return model_cls.model_validate(payload)
    except PydanticValidationError as exc:
        raise CvatError(f"Dữ liệu CVAT không hợp lệ ({label}): {exc}") from exc


class CvatClient:
    def __init__(self, base_url=None, token=None, username=None, password=None, organization=None, timeout=15):
        self.base_url = (base_url or settings.CVAT_URL or "").rstrip("/")
        if not self.base_url:
            raise CvatError("Chưa cấu hình CVAT_URL trong backend/.env.")
        self.timeout = timeout
        self.session = requests.Session()
        token = token or settings.CVAT_ACCESS_TOKEN
        username = username or settings.CVAT_USERNAME
        password = password or settings.CVAT_PASSWORD
        org = organization if organization is not None else getattr(settings, "CVAT_ORGANIZATION", "")
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        elif username and password:
            self.session.auth = (username, password)
        else:
            raise CvatError("Chưa cấu hình tài khoản CVAT (CVAT_ACCESS_TOKEN hoặc CVAT_USERNAME/CVAT_PASSWORD).")
        if org:
            self.session.headers["X-Organization"] = org

    def _get(self, path, params=None):
        url = f"{self.base_url}/api/{path.lstrip('/')}"
        try:
            response = self.session.get(url, params=params, timeout=self.timeout, allow_redirects=False)
        except requests.RequestException as exc:
            raise CvatError(f"Không kết nối được CVAT tại {self.base_url}: {exc}") from exc
        if 300 <= response.status_code < 400:
            raise CvatError(
                f"CVAT trả chuyển hướng HTTP {response.status_code} cho {path} — kiểm tra lại CVAT_URL."
            )
        if response.status_code == 401:
            raise CvatError("CVAT từ chối xác thực. Kiểm tra tài khoản/token CVAT.")
        if response.status_code == 404:
            raise CvatNotFoundError(f"Không tìm thấy trên CVAT: {path}")
        if not response.ok:
            raise CvatError(f"CVAT trả lỗi {response.status_code} cho {path}")
        try:
            return response.json()
        except ValueError as exc:
            raise CvatError(f"CVAT trả JSON không hợp lệ cho {path}") from exc

    def _get_all(self, path, params=None):
        """CVAT phân trang (results + next). Gom hết các trang an toàn, giới hạn MAX_PAGES."""
        params = {**(params or {}), "page_size": 100, "page": 1}
        items = []
        for _ in range(MAX_PAGES):
            data = self._get(path, params)
            if not isinstance(data, dict) or not isinstance(data.get("results", []), list):
                raise CvatError(f"CVAT trả cấu trúc phân trang không hợp lệ cho {path}")
            items.extend(data.get("results", []))
            if not data.get("next"):
                return items
            params["page"] += 1
        raise CvatError(f"CVAT vượt quá giới hạn phân trang ({MAX_PAGES} trang) cho {path}")

    def about(self):
        return _validate_model(CvatAboutPayload, self._get("server/about"), "server/about").model_dump()

    def list_tasks(self, project_id=None, search=None):
        params = {}
        if project_id:
            params["project_id"] = project_id
        if search:
            params["search"] = search
        raw_items = self._get_all("tasks", params)
        return [_validate_model(CvatTaskPayload, item, "task").model_dump() for item in raw_items]

    def get_task(self, task_id):
        return _validate_model(CvatTaskPayload, self._get(f"tasks/{task_id}"), f"tasks/{task_id}").model_dump()

    def list_task_jobs(self, task_id):
        """Chỉ lấy annotation jobs (loại ground_truth và consensus replica của cvat-base)."""
        raw_items = self._get_all("jobs", {"task_id": task_id, "type": "annotation"})
        return [_validate_model(CvatJobPayload, item, f"jobs(task={task_id})").model_dump() for item in raw_items]

    def get_job_meta(self, job_id) -> CvatJobMetaPayload:
        return _validate_model(
            CvatJobMetaPayload,
            self._get(f"jobs/{job_id}/data/meta"),
            f"jobs/{job_id}/data/meta",
        )

    def count_job_objects(self, job_id, *, start_frame=None, stop_frame=None):
        """Tổng số cuboid/object-frame sau khi bung track keyframes, trừ deleted_frames và outside."""
        payload = _validate_model(
            CvatAnnotationsPayload,
            self._get(f"jobs/{job_id}/annotations"),
            f"jobs/{job_id}/annotations",
        )
        meta: CvatJobMetaPayload | None = None
        try:
            meta = self.get_job_meta(job_id)
        except CvatNotFoundError:
            meta = None
        if meta is None:
            return payload.count_object_frames(start_frame=start_frame, stop_frame=stop_frame)
        return payload.count_object_frames(
            start_frame=meta.start_frame if meta.start_frame is not None else start_frame,
            stop_frame=meta.resolved_stop_frame if meta.resolved_stop_frame is not None else stop_frame,
            frame_step=meta.frame_step,
            deleted_frames=meta.deleted_frames,
            included_frames=meta.included_frames,
        )
