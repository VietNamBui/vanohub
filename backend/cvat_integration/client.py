"""Client gọi CVAT REST API. Ghi duy nhất: assignee của CVAT job và lời mời organization (xem assignee.py).

Tách riêng file này vì đây là code kỹ thuật (HTTP, xác thực, phân trang), không phải
nghiệp vụ VanoHub. Nhờ vậy test có thể thay client giả mà không cần CVAT thật.

Cấu hình qua biến môi trường (backend/.env):
- CVAT_URL: địa chỉ backend gọi tới, vd. http://localhost:8080
- CVAT_ACCESS_TOKEN (Personal Access Token) hoặc CVAT_USERNAME + CVAT_PASSWORD
- CVAT_HOST_HEADER (tùy chọn): header Host khi CVAT đứng sau reverse proxy nội bộ
Organization trên CVAT được truyền trực tiếp qua tham số `organization` (từ `Project.cvat_org_slug`).
"""

import ipaddress
import json as json_module
import logging
import re
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import requests
from django.conf import settings
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from .schemas import CvatAboutPayload, CvatAnnotationsPayload, CvatJobMetaPayload, CvatJobPayload, CvatTaskPayload

logger = logging.getLogger(__name__)

MAX_PAGES = 1000
DEFAULT_MAX_RESPONSE_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_REQUEST_DURATION = 120.0
_STREAM_CHUNK_SIZE = 65536
_HOST_LABEL_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?$"
)


class CvatError(Exception):
    """Lỗi khi gọi CVAT — view sẽ chuyển thành thông báo dễ hiểu cho người dùng."""


class CvatNotFoundError(CvatError):
    """Tài nguyên không còn tồn tại trên CVAT (HTTP 404)."""


def _validate_model[ModelT: BaseModel](model_cls: type[ModelT], payload: Any, label: str) -> ModelT:
    try:
        return model_cls.model_validate(payload)
    except PydanticValidationError as exc:
        logger.warning("CVAT payload invalid (%s): %s", label, exc.errors(include_url=False, include_input=False))
        raise CvatError(f"Dữ liệu CVAT không hợp lệ ({label}).") from exc


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


def _validate_host_header(raw_host: str, *, base_url: str) -> str:
    """Validate optional CVAT_HOST_HEADER against CRLF, whitespace, userinfo/path injection, and invalid host[:port]."""
    if not raw_host:
        return ""
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw_host):
        raise CvatError("CVAT_HOST_HEADER chứa ký tự điều khiển không hợp lệ.")
    host = raw_host.strip()
    if not host or any(ch.isspace() for ch in host) or any(ch in host for ch in ("/", "\\", "@", "?", "#")):
        raise CvatError("CVAT_HOST_HEADER không hợp lệ.")
    try:
        parsed = urlparse(f"http://{host}")
        port = parsed.port
    except ValueError as exc:
        raise CvatError("CVAT_HOST_HEADER không hợp lệ: cần dạng <host>[:port].") from exc
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or (port is not None and not (1 <= port <= 65535))
    ):
        raise CvatError("CVAT_HOST_HEADER không hợp lệ: cần dạng <host>[:port].")
    if host.startswith("["):
        try:
            ipaddress.ip_address(parsed.hostname)
        except ValueError as exc:
            raise CvatError("CVAT_HOST_HEADER không hợp lệ: địa chỉ IPv6 sai định dạng.") from exc
    elif not _HOST_LABEL_RE.fullmatch(parsed.hostname):
        raise CvatError("CVAT_HOST_HEADER không hợp lệ: tên miền sai định dạng.")

    parsed_base = urlparse(base_url)
    if parsed_base.scheme == "https" and parsed_base.hostname and parsed_base.hostname.lower() != parsed.hostname.lower():
        logger.warning(
            "CVAT_HOST_HEADER (%s) differs from HTTPS CVAT_URL host (%s); TLS SNI uses CVAT_URL hostname.",
            parsed.hostname,
            parsed_base.hostname,
        )
    return host


class CvatClient:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        organization: str | None = None,
        timeout: int = 15,
        max_duration_seconds: float | None = None,
        max_response_bytes: int | None = None,
    ) -> None:
        self.base_url = (base_url or settings.CVAT_URL or "").rstrip("/")
        if not self.base_url:
            raise CvatError("Chưa cấu hình CVAT_URL trong backend/.env.")
        _validate_base_url(self.base_url)

        raw_host_header = getattr(settings, "CVAT_HOST_HEADER", "")
        host_header = _validate_host_header(
            raw_host_header if isinstance(raw_host_header, str) else str(raw_host_header),
            base_url=self.base_url,
        )

        resolved_token = (token or settings.CVAT_ACCESS_TOKEN or "").strip()
        resolved_username = username or settings.CVAT_USERNAME
        resolved_password = password or settings.CVAT_PASSWORD
        if resolved_token:
            if any(ch.isspace() or ord(ch) < 33 or ord(ch) > 126 for ch in resolved_token):
                raise CvatError("Access Token CVAT chứa ký tự không hợp lệ.")
        elif not (resolved_username and resolved_password):
            raise CvatError("Chưa cấu hình tài khoản CVAT (CVAT_ACCESS_TOKEN hoặc CVAT_USERNAME/CVAT_PASSWORD).")

        self.timeout = timeout
        self.max_duration_seconds = float(
            max_duration_seconds
            if max_duration_seconds is not None
            else getattr(settings, "CVAT_MAX_REQUEST_DURATION", DEFAULT_MAX_REQUEST_DURATION)
        )
        self.max_response_bytes = int(
            max_response_bytes
            if max_response_bytes is not None
            else getattr(settings, "CVAT_MAX_RESPONSE_BYTES", DEFAULT_MAX_RESPONSE_BYTES)
        )
        self.session = requests.Session()
        self.session.trust_env = False
        if host_header:
            self.session.headers["Host"] = host_header
        if resolved_token:
            self.session.headers["Authorization"] = f"Bearer {resolved_token}"
        else:
            self.session.auth = (resolved_username, resolved_password)
        if organization:
            self.session.headers["X-Organization"] = organization

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "CvatClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _read_json_body(self, response: Any, path: str, *, max_bytes: int) -> Any:
        raw_headers = getattr(response, "headers", None)
        if isinstance(raw_headers, Mapping):
            raw_len = raw_headers.get("Content-Length")
            if isinstance(raw_len, str) and raw_len.strip().isdigit() and int(raw_len.strip()) > max_bytes:
                raise CvatError(f"Phản hồi CVAT vượt quá giới hạn dung lượng cho {path}.")

        if isinstance(response, requests.Response):
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=_STREAM_CHUNK_SIZE):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise CvatError(f"Phản hồi CVAT vượt quá giới hạn dung lượng cho {path}.")
                chunks.append(chunk)
            if total == 0:
                return None
            try:
                return json_module.loads(b"".join(chunks).decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise CvatError(f"CVAT trả JSON không hợp lệ cho {path}") from exc

        content = getattr(response, "content", b"")
        if isinstance(content, (bytes, bytearray)):
            if len(content) > max_bytes:
                raise CvatError(f"Phản hồi CVAT vượt quá giới hạn dung lượng cho {path}.")
            if not content:
                return None
        try:
            return response.json()
        except ValueError as exc:
            raise CvatError(f"CVAT trả JSON không hợp lệ cho {path}") from exc

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: Any = None,
        *,
        timeout: float | None = None,
        max_bytes: int | None = None,
    ) -> Any:
        url = f"{self.base_url}/api/{path.lstrip('/')}"
        effective_timeout = self.timeout if timeout is None else timeout
        effective_max_bytes = self.max_response_bytes if max_bytes is None else max_bytes
        try:
            response = self.session.request(
                method,
                url,
                params=params,
                json=json,
                timeout=effective_timeout,
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as exc:
            logger.warning("CVAT request failed: %s %s (%s)", method, path, type(exc).__name__)
            raise CvatError(f"Không kết nối được CVAT tại {self.base_url} ({type(exc).__name__}).") from exc
        try:
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
            return self._read_json_body(response, path, max_bytes=effective_max_bytes)
        finally:
            close_fn = getattr(response, "close", None)
            if callable(close_fn):
                close_fn()

    def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        max_bytes: int | None = None,
    ) -> Any:
        return self._request("GET", path, params=params, timeout=timeout, max_bytes=max_bytes)

    def _get_all(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        max_duration_seconds: float | None = None,
    ) -> list[Any]:
        """CVAT phân trang (results + next). Gom hết các trang an toàn, giới hạn MAX_PAGES và tổng thời gian."""
        query: dict[str, Any] = {**(params or {}), "page_size": 100, "page": 1}
        items: list[Any] = []
        started = time.monotonic()
        budget = self.max_duration_seconds if max_duration_seconds is None else max_duration_seconds
        for _ in range(MAX_PAGES):
            elapsed = time.monotonic() - started
            if budget > 0 and elapsed >= budget:
                raise CvatError(f"Quá thời gian phản hồi khi phân trang CVAT cho {path}.")
            page_timeout = min(self.timeout, max(0.1, budget - elapsed)) if budget > 0 else self.timeout
            data = self._get(path, query, timeout=page_timeout)
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
        allow_missing_meta: bool = False,
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
            if not allow_missing_meta:
                raise
            meta = None
        if meta is None:
            return payload.count_object_frames(start_frame=start_frame, stop_frame=stop_frame)
        if start_frame is not None and meta.start_frame is not None:
            resolved_start: int | None = max(start_frame, meta.start_frame)
        else:
            resolved_start = start_frame if start_frame is not None else meta.start_frame
        resolved_stop = meta.resolve_stop_frame(stop_frame)
        return payload.count_object_frames(
            start_frame=resolved_start,
            stop_frame=resolved_stop,
            frame_step=meta.frame_step,
            deleted_frames=meta.deleted_frames,
            included_frames=meta.included_frames,
        )

    def set_job_assignee(self, job_id: int, cvat_user_id: int | None) -> Any:
        """Đặt người được giao (assignee) của một CVAT job. None = bỏ giao."""
        return self._request("PATCH", f"jobs/{job_id}", json={"assignee": cvat_user_id})
