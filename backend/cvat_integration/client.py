"""Client gọi CVAT REST API. Ghi duy nhất: assignee của CVAT job và lời mời organization (xem assignee.py).

Tách riêng file này vì đây là code kỹ thuật (HTTP, xác thực, phân trang), không phải
nghiệp vụ VanoHub. Nhờ vậy test có thể thay client giả mà không cần CVAT thật.

Cấu hình qua biến môi trường (backend/.env):
- CVAT_URL: địa chỉ backend gọi tới, vd. http://localhost:8080
- CVAT_ACCESS_TOKEN (Personal Access Token) hoặc CVAT_USERNAME + CVAT_PASSWORD
- CVAT_HOST_HEADER (tùy chọn): header Host khi CVAT đứng sau reverse proxy nội bộ
Organization trên CVAT được truyền trực tiếp qua tham số `organization` (từ `Project.cvat_org_slug`).
"""

from typing import Any
from urllib.parse import urlparse

import requests
from django.conf import settings
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from .schemas import CvatAboutPayload, CvatAnnotationsPayload, CvatJobMetaPayload, CvatJobPayload, CvatTaskPayload

MAX_PAGES = 1000


class CvatError(Exception):
    """Lỗi khi gọi CVAT — view sẽ chuyển thành thông báo dễ hiểu cho người dùng."""


class CvatNotFoundError(CvatError):
    """Tài nguyên không còn tồn tại trên CVAT (HTTP 404)."""


def _validate_model[ModelT: BaseModel](model_cls: type[ModelT], payload: Any, label: str) -> ModelT:
    try:
        return model_cls.model_validate(payload)
    except PydanticValidationError as exc:
        raise CvatError(f"Dữ liệu CVAT không hợp lệ ({label}): {exc}") from exc


def _validate_base_url(base_url: str) -> None:
    """Validate CVAT base URL scheme, host, and absence of credentials, query, or fragment."""
    try:
        parsed = urlparse(base_url)
    except ValueError as exc:
        raise CvatError("CVAT_URL không hợp lệ: cần dạng http(s)://<host>.") from exc
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise CvatError("CVAT_URL không hợp lệ: cần dạng http(s)://<host>.")
    if parsed.username is not None or parsed.password is not None:
        raise CvatError("CVAT_URL không được chứa thông tin đăng nhập trong URL.")
    if parsed.query or parsed.fragment or "?" in base_url or "#" in base_url:
        raise CvatError("CVAT_URL không được chứa query string hoặc fragment.")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise CvatError("CVAT_URL không hợp lệ: cần dạng http(s)://<host>.") from exc
    if getattr(settings, "CVAT_REQUIRE_HTTPS", False) and parsed.scheme != "https":
        raise CvatError("CVAT_URL phải dùng https:// khi CVAT_REQUIRE_HTTPS=True.")


class CvatClient:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        organization: str | None = None,
        timeout: int = 15,
    ) -> None:
        self.base_url = (base_url or settings.CVAT_URL or "").rstrip("/")
        if not self.base_url:
            raise CvatError("Chưa cấu hình CVAT_URL trong backend/.env.")
        _validate_base_url(self.base_url)
        self.timeout = timeout
        self.session = requests.Session()
        host_header = getattr(settings, "CVAT_HOST_HEADER", "")
        if host_header:
            self.session.headers["Host"] = host_header
        resolved_token = token or settings.CVAT_ACCESS_TOKEN
        resolved_username = username or settings.CVAT_USERNAME
        resolved_password = password or settings.CVAT_PASSWORD
        if resolved_token:
            self.session.headers["Authorization"] = f"Bearer {resolved_token}"
        elif resolved_username and resolved_password:
            self.session.auth = (resolved_username, resolved_password)
        else:
            raise CvatError("Chưa cấu hình tài khoản CVAT (CVAT_ACCESS_TOKEN hoặc CVAT_USERNAME/CVAT_PASSWORD).")
        if organization:
            self.session.headers["X-Organization"] = organization

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        url = f"{self.base_url}/api/{path.lstrip('/')}"
        try:
            response = self.session.request(
                method,
                url,
                params=params,
                json=json,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise CvatError(f"Không kết nối được CVAT tại {self.base_url}: {exc}") from exc
        if 300 <= response.status_code < 400:
            raise CvatError(
                f"CVAT trả chuyển hướng HTTP {response.status_code} cho {path} — kiểm tra lại CVAT_URL."
            )
        if response.status_code == 401:
            raise CvatError("CVAT từ chối xác thực. Kiểm tra tài khoản/token CVAT.")
        if response.status_code == 403:
            raise CvatError(f"Tài khoản CVAT không có quyền thực hiện: {path}")
        if response.status_code == 404:
            raise CvatNotFoundError(f"Không tìm thấy trên CVAT: {path}")
        if not response.ok:
            raise CvatError(f"CVAT trả lỗi {response.status_code} cho {path}")
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise CvatError(f"CVAT trả JSON không hợp lệ cho {path}") from exc

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def _get_all(self, path: str, params: dict[str, Any] | None = None) -> list[Any]:
        """CVAT phân trang (results + next). Gom hết các trang an toàn, giới hạn MAX_PAGES."""
        query: dict[str, Any] = {**(params or {}), "page_size": 100, "page": 1}
        items: list[Any] = []
        for _ in range(MAX_PAGES):
            data = self._get(path, query)
            if not isinstance(data, dict) or not isinstance(data.get("results", []), list):
                raise CvatError(f"CVAT trả cấu trúc phân trang không hợp lệ cho {path}")
            items.extend(data.get("results", []))
            if not data.get("next"):
                return items
            query["page"] += 1
        raise CvatError(f"CVAT vượt quá giới hạn phân trang ({MAX_PAGES} trang) cho {path}")

    def about(self) -> dict[str, Any]:
        return _validate_model(CvatAboutPayload, self._get("server/about"), "server/about").model_dump()

    def get_self(self) -> dict[str, Any]:
        """User CVAT sở hữu token/tài khoản đang dùng: {"id", "username", ...}."""
        data = self._get("users/self")
        if not isinstance(data, dict):
            raise CvatError("CVAT trả dữ liệu người dùng không hợp lệ.")
        return data

    def me(self) -> dict[str, Any]:
        """Alias của get_self()."""
        return self.get_self()

    def list_organizations(self) -> list[dict[str, Any]]:
        return self._get_all("organizations")

    def list_memberships(self, org_id: int) -> list[dict[str, Any]]:
        return self._get_all("memberships", {"org_id": org_id})

    def get_user(self, user_id: int) -> dict[str, Any]:
        data = self._get(f"users/{user_id}")
        if not isinstance(data, dict):
            raise CvatError(f"CVAT trả dữ liệu người dùng không hợp lệ cho users/{user_id}.")
        return data

    def invite_to_org(self, org_slug: str, email: str, role: str = "worker") -> Any:
        """Mời một tài khoản CVAT (theo email) vào organization.

        CVAT tự chấp nhận ngay khi ORG_INVITATION_CONFIRM = "No" (mặc định) và email thuộc một tài khoản có sẵn.
        """
        return self._request("POST", "invitations", params={"org": org_slug}, json={"role": role, "email": email})

    def list_org_projects(self, org_id: int) -> list[dict[str, Any]]:
        """CVAT project thuộc một organization (tài khoản hệ thống là admin nên thấy được mọi org)."""
        return self._get_all("projects", {"org_id": org_id})

    def list_projects(self) -> list[dict[str, Any]]:
        return self._get_all("projects")

    def get_project(self, project_id: int) -> dict[str, Any]:
        data = self._get(f"projects/{project_id}")
        if not isinstance(data, dict):
            raise CvatError(f"CVAT trả dữ liệu project không hợp lệ cho projects/{project_id}.")
        return data

    def list_project_tasks(self, project_id: int) -> list[dict[str, Any]]:
        return self._get_all("tasks", {"project_id": project_id})

    def list_project_labels(self, project_id: int) -> list[dict[str, Any]]:
        return self._get_all("labels", {"project_id": project_id})

    def list_tasks(self, project_id: int | None = None, search: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if project_id:
            params["project_id"] = project_id
        if search:
            params["search"] = search
        raw_items = self._get_all("tasks", params)
        return [_validate_model(CvatTaskPayload, item, "task").model_dump() for item in raw_items]

    def get_task(self, task_id: int) -> dict[str, Any]:
        return _validate_model(CvatTaskPayload, self._get(f"tasks/{task_id}"), f"tasks/{task_id}").model_dump()

    def list_task_jobs(self, task_id: int) -> list[dict[str, Any]]:
        """Chỉ lấy annotation jobs (loại ground_truth và consensus replica của cvat-base)."""
        raw_items = self._get_all("jobs", {"task_id": task_id, "type": "annotation"})
        return [_validate_model(CvatJobPayload, item, f"jobs(task={task_id})").model_dump() for item in raw_items]

    def get_job_meta(self, job_id: int) -> CvatJobMetaPayload:
        return _validate_model(
            CvatJobMetaPayload,
            self._get(f"jobs/{job_id}/data/meta"),
            f"jobs/{job_id}/data/meta",
        )

    def count_job_objects(
        self,
        job_id: int,
        *,
        start_frame: int | None = None,
        stop_frame: int | None = None,
    ) -> int:
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

    def set_job_assignee(self, job_id: int, cvat_user_id: int | None) -> Any:
        """Đặt người được giao (assignee) của một CVAT job. None = bỏ giao."""
        return self._request("PATCH", f"jobs/{job_id}", json={"assignee": cvat_user_id})
