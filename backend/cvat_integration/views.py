import logging
from collections.abc import Mapping
from typing import Any, cast

from django.conf import settings
from django.db import transaction
from rest_framework import status as http_status
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from accounts.datetime_utils import parse_int_param
from accounts.models import User
from projects.models import ActivityLog, Project

from .assignee import jobs_held_by, push_assignees
from .client import CvatClient, CvatError
from .models import CvatAccount
from .sync import sync_organizations, sync_organizations_quietly

logger = logging.getLogger(__name__)


def _sanitize_cvat_status_error(exc: CvatError) -> str:
    msg = str(exc)
    if "Chưa cấu hình" in msg:
        return "Chưa cấu hình kết nối CVAT trên máy chủ."
    if "xác thực" in msg:
        return "CVAT từ chối xác thực tài khoản hệ thống."
    return "Không kết nối được tới máy chủ CVAT."


@api_view(["GET"])
def status(request: Request) -> Response:
    """GET /api/cvat/status/ — kiểm tra VanoHub có gọi được CVAT không (không trả thông tin bí mật)."""
    try:
        about = CvatClient(timeout=5).about()
        return Response({"connected": True, "url": settings.CVAT_PUBLIC_URL, "version": about.get("version")})
    except CvatError as exc:
        logger.warning("CVAT status check failed: %s", exc)
        return Response(
            {
                "connected": False,
                "url": settings.CVAT_PUBLIC_URL,
                "detail": _sanitize_cvat_status_error(exc),
            }
        )


@api_view(["GET"])
def tasks(request: Request) -> Response:
    """GET /api/cvat/tasks/?project_id=&search= — danh sách CVAT task (chỉ PM/superuser)."""
    user = cast(User, request.user)
    if not user.is_pm():
        raise PermissionDenied("Chỉ Project Manager mới được xem danh sách CVAT task.")
    raw_project_id = request.query_params.get("project_id")
    project_id = (
        parse_int_param(raw_project_id, "project_id")
        if raw_project_id is not None and str(raw_project_id).strip() != ""
        else None
    )
    search = (request.query_params.get("search") or "").strip() or None
    try:
        raw = CvatClient(timeout=10).list_tasks(project_id=project_id, search=search)
    except CvatError as exc:
        logger.warning("CVAT list_tasks failed: %s", exc)
        return Response({"detail": _sanitize_cvat_status_error(exc)}, status=http_status.HTTP_502_BAD_GATEWAY)
    return Response(
        [
            {
                "id": t["id"],
                "name": t.get("name") or f"Task #{t['id']}",
                "project_id": t.get("project_id"),
                "status": t.get("status", ""),
                "size": t.get("size") or 0,
                "subset": t.get("subset", ""),
            }
            for t in raw
        ]
    )


def _link_state(user: User, sync: dict[str, Any] | None = None) -> dict[str, Any]:
    account = CvatAccount.objects.filter(user=user).first()
    data: dict[str, Any] = {
        "linked": account is not None,
        "cvat_user_id": account.cvat_user_id if account else None,
        "cvat_username": account.cvat_username if account else None,
        "linked_at": account.linked_at if account else None,
        "cvat_url": settings.CVAT_PUBLIC_URL,
        "jobs_held": jobs_held_by(user).count(),
    }
    if sync is not None:
        data["sync"] = sync
    return data


def _sync_held_jobs(user: User) -> dict[str, Any]:
    """Đẩy assignee cho các job user đang giữ. Lỗi CVAT không chặn việc liên kết, chỉ báo lại."""
    try:
        result = push_assignees(jobs_held_by(user))
        return {"pushed": result["pushed"], "error": "; ".join(result["warnings"]) or None}
    except CvatError as exc:
        return {"pushed": 0, "error": str(exc)}


def _log(user: User, action: str, **extra: Any) -> None:
    """Ghi lịch sử vào mọi dự án user tham gia (ActivityLog gắn theo dự án)."""
    projects = {a.project for a in user.role_assignments.select_related("project")}
    for project in projects:
        ActivityLog.record(project=project, actor=user, action=action, target=user, after=extra or None)


@api_view(["GET", "POST", "DELETE"])
def link(request: Request) -> Response:
    """/api/cvat/link/ — liên kết tài khoản CVAT của CHÍNH người đang đăng nhập.

    POST {"token": "<CVAT Personal Access Token>"}: VanoHub gọi CVAT /users/self bằng token đó
    để biết token thuộc user CVAT nào, lưu ID + username rồi BỎ token (không lưu).
    """
    user = cast(User, request.user)
    if request.method == "GET":
        return Response(_link_state(user))

    if request.method == "DELETE":
        deleted, _ = CvatAccount.objects.filter(user=user).delete()
        if not deleted:
            raise ValidationError("Bạn chưa liên kết tài khoản CVAT.")
        _log(user, "cvat.unlink")
        # Người giữ job không còn liên kết → bỏ assignee bên CVAT.
        return Response(_link_state(user, _sync_held_jobs(user)))

    if not isinstance(request.data, Mapping):
        raise ValidationError({"detail": "Dữ liệu yêu cầu không hợp lệ."})
    raw_token = request.data.get("token")
    if not isinstance(raw_token, str) or not raw_token.strip():
        raise ValidationError({"token": "Dán Access Token tạo trong CVAT."})
    token = raw_token.strip()
    try:
        me = CvatClient(token=token, timeout=10).get_self()
    except CvatError as exc:
        message = str(exc)
        if "xác thực" in message:
            message = "Token không hợp lệ hoặc đã hết hạn / bị thu hồi. Tạo token mới trong CVAT rồi thử lại."
        return Response({"detail": message}, status=http_status.HTTP_400_BAD_REQUEST)

    cvat_id, cvat_username = me.get("id"), me.get("username", "")
    if not isinstance(cvat_id, int) or isinstance(cvat_id, bool) or cvat_id <= 0:
        return Response({"detail": "CVAT không trả về thông tin người dùng."}, status=http_status.HTTP_502_BAD_GATEWAY)
    owner = CvatAccount.objects.filter(cvat_user_id=cvat_id).exclude(user=user).select_related("user").first()
    if owner:
        raise ValidationError(
            {"token": f"Tài khoản CVAT “{cvat_username}” đã được liên kết với một người khác trên VanoHub."}
        )

    with transaction.atomic():
        CvatAccount.objects.update_or_create(
            user=user,
            defaults={"cvat_user_id": cvat_id, "cvat_username": str(cvat_username or "")},
        )
        _log(user, "cvat.link", cvat_username=cvat_username, cvat_user_id=cvat_id)
    data = _link_state(user, _sync_held_jobs(user))
    # Organization trên CVAT mà tài khoản này là thành viên → hiện trên VanoHub ngay.
    data["organizations"] = _filter_sync_result_for_user(user, sync_organizations_quietly(user))
    return Response(data, status=http_status.HTTP_200_OK)


def _filter_sync_result_for_user(user: User, result: dict[str, Any]) -> dict[str, Any]:
    """Chỉ trả kết quả thuộc các organization mà user là thành viên (trừ superuser)."""
    if user.is_superuser or "error" in result:
        return result
    allowed_names = set(Project.objects.filter(role_assignments__user=user).values_list("name", flat=True))
    return {
        "created": [name for name in result.get("created", []) if name in allowed_names],
        "updated": [name for name in result.get("updated", []) if name in allowed_names],
        "pm_added": [item for item in result.get("pm_added", []) if item.get("organization") in allowed_names],
        "members_added": [
            item for item in result.get("members_added", []) if item.get("organization") in allowed_names
        ],
        "waiting": [],
    }


@api_view(["POST"])
def sync_organizations_view(request: Request) -> Response:
    """POST /api/cvat/sync-organizations/ — kéo CVAT organization (và vai trò thành viên) về VanoHub.

    Chỉ PM (của ít nhất một organization) hoặc superuser được kích hoạt; non-superuser chỉ thấy
    kết quả của các organization mà mình thuộc về.
    """
    user = cast(User, request.user)
    if not user.is_pm():
        raise PermissionDenied("Chỉ Project Manager hoặc quản trị viên mới có quyền đồng bộ organization từ CVAT.")
    try:
        result = sync_organizations(user)
        return Response(_filter_sync_result_for_user(user, result))
    except CvatError as exc:
        return Response({"detail": str(exc)}, status=http_status.HTTP_502_BAD_GATEWAY)
