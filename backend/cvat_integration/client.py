"""Client gọi CVAT REST API. Ghi duy nhất một thứ: assignee của CVAT job (xem assignee.py).

Tách riêng file này vì đây là code kỹ thuật (HTTP, xác thực, phân trang), không phải
nghiệp vụ Vanohub. Nhờ vậy test có thể thay client giả mà không cần CVAT thật.

Cấu hình qua biến môi trường (backend/.env):
- CVAT_URL: địa chỉ backend gọi tới, vd. http://localhost:8080
- CVAT_ACCESS_TOKEN (Personal Access Token) hoặc CVAT_USERNAME + CVAT_PASSWORD
"""

import requests
from django.conf import settings


class CvatError(Exception):
    """Lỗi khi gọi CVAT — view sẽ chuyển thành thông báo dễ hiểu cho người dùng."""


class CvatClient:
    def __init__(self, base_url=None, token=None, username=None, password=None, timeout=15):
        self.base_url = (base_url or settings.CVAT_URL or "").rstrip("/")
        if not self.base_url:
            raise CvatError("Chưa cấu hình CVAT_URL trong backend/.env.")
        self.timeout = timeout
        self.session = requests.Session()
        host_header = getattr(settings, "CVAT_HOST_HEADER", "")
        if host_header:
            self.session.headers["Host"] = host_header
        token = token or settings.CVAT_ACCESS_TOKEN
        username = username or settings.CVAT_USERNAME
        password = password or settings.CVAT_PASSWORD
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        elif username and password:
            self.session.auth = (username, password)
        else:
            raise CvatError("Chưa cấu hình tài khoản CVAT (CVAT_ACCESS_TOKEN hoặc CVAT_USERNAME/CVAT_PASSWORD).")

    def _request(self, method, path, params=None, json=None):
        url = f"{self.base_url}/api/{path.lstrip('/')}"
        try:
            response = self.session.request(method, url, params=params, json=json, timeout=self.timeout)
        except requests.RequestException as exc:
            raise CvatError(f"Không kết nối được CVAT tại {self.base_url}: {exc}") from exc
        if response.status_code == 401:
            raise CvatError("CVAT từ chối xác thực. Kiểm tra tài khoản/token CVAT.")
        if response.status_code == 403:
            raise CvatError(f"Tài khoản CVAT không có quyền thực hiện: {path}")
        if response.status_code == 404:
            raise CvatError(f"Không tìm thấy trên CVAT: {path}")
        if not response.ok:
            raise CvatError(f"CVAT trả lỗi {response.status_code} cho {path}")
        return response.json() if response.content else None

    def _get(self, path, params=None):
        return self._request("GET", path, params=params)

    def _get_all(self, path, params=None):
        """CVAT phân trang (results + next). Gom hết các trang."""
        params = {**(params or {}), "page_size": 100, "page": 1}
        items = []
        while True:
            data = self._get(path, params)
            items.extend(data.get("results", []))
            if not data.get("next"):
                return items
            params["page"] += 1

    def about(self):
        return self._get("server/about")

    def list_projects(self):
        return self._get_all("projects")

    def list_organizations(self):
        return self._get_all("organizations")

    def list_memberships(self, org_id):
        return self._get_all("memberships", {"org_id": org_id})

    def get_user(self, user_id):
        return self._get(f"users/{user_id}")

    def invite_to_org(self, org_slug, email, role="worker"):
        """Mời một tài khoản CVAT (theo email) vào organization.

        CVAT tự chấp nhận ngay khi ORG_INVITATION_CONFIRM = "No" (mặc định) và email thuộc một tài khoản có sẵn.
        """
        return self._request("POST", "invitations", params={"org": org_slug}, json={"role": role, "email": email})

    def list_org_projects(self, org_id):
        """CVAT project thuộc một organization (tài khoản hệ thống là admin nên thấy được mọi org)."""
        return self._get_all("projects", {"org_id": org_id})

    def get_project(self, project_id):
        return self._get(f"projects/{project_id}")

    def list_project_tasks(self, project_id):
        return self._get_all("tasks", {"project_id": project_id})

    def list_project_labels(self, project_id):
        return self._get_all("labels", {"project_id": project_id})

    def get_task(self, task_id):
        return self._get(f"tasks/{task_id}")

    def list_task_jobs(self, task_id):
        return self._get_all("jobs", {"task_id": task_id})

    def get_self(self):
        """User CVAT sở hữu token/tài khoản đang dùng: {"id", "username", ...}."""
        return self._get("users/self")

    def set_job_assignee(self, job_id, cvat_user_id):
        """Đặt người được giao (assignee) của một CVAT job. None = bỏ giao."""
        return self._request("PATCH", f"jobs/{job_id}", json={"assignee": cvat_user_id})

    def count_job_objects(self, job_id):
        """Số object = số shape + số track trong annotation của job."""
        data = self._get(f"jobs/{job_id}/annotations")
        return len(data.get("shapes", [])) + len(data.get("tracks", []))
