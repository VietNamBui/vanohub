from django.conf import settings
from django.db import transaction
from rest_framework import status as http_status
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from projects.models import ActivityLog

from .assignee import jobs_held_by, push_assignees
from .client import CvatClient, CvatError
from .models import CvatAccount
from .sync import sync_organizations, sync_organizations_quietly


@api_view(["GET"])
def status(request):
    """GET /api/cvat/status/ — kiểm tra Vanohub có gọi được CVAT không (không trả thông tin bí mật)."""
    try:
        about = CvatClient(timeout=5).about()
        return Response({"connected": True, "url": settings.CVAT_PUBLIC_URL, "version": about.get("version")})
    except CvatError as exc:
        return Response({"connected": False, "url": settings.CVAT_PUBLIC_URL, "detail": str(exc)})


def _link_state(user, sync=None):
    account = CvatAccount.objects.filter(user=user).first()
    data = {
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


def _sync_held_jobs(user):
    """Đẩy assignee cho các job user đang giữ. Lỗi CVAT không chặn việc liên kết, chỉ báo lại."""
    try:
        result = push_assignees(jobs_held_by(user))
        return {"pushed": result["pushed"], "error": "; ".join(result["warnings"]) or None}
    except CvatError as exc:
        return {"pushed": 0, "error": str(exc)}


def _log(user, action, **extra):
    """Ghi lịch sử vào mọi dự án user tham gia (ActivityLog gắn theo dự án)."""
    projects = {a.project for a in user.role_assignments.exclude(project=None).select_related("project")}
    for project in projects:
        ActivityLog.record(project=project, actor=user, action=action, target=user, after=extra or None)


@api_view(["GET", "POST", "DELETE"])
def link(request):
    """/api/cvat/link/ — liên kết tài khoản CVAT của CHÍNH người đang đăng nhập.

    POST {"token": "<CVAT Personal Access Token>"}: VanoHub gọi CVAT /users/self bằng token đó
    để biết token thuộc user CVAT nào, lưu ID + username rồi BỎ token (không lưu).
    """
    user = request.user
    if request.method == "GET":
        return Response(_link_state(user))

    if request.method == "DELETE":
        deleted, _ = CvatAccount.objects.filter(user=user).delete()
        if not deleted:
            raise ValidationError("Bạn chưa liên kết tài khoản CVAT.")
        _log(user, "cvat.unlink")
        # Người giữ job không còn liên kết → bỏ assignee bên CVAT.
        return Response(_link_state(user, _sync_held_jobs(user)))

    token = str(request.data.get("token") or "").strip()
    if not token:
        raise ValidationError({"token": "Dán Access Token tạo trong CVAT."})
    try:
        me = CvatClient(token=token, timeout=10).get_self()
    except CvatError as exc:
        message = str(exc)
        if "xác thực" in message:
            message = "Token không hợp lệ hoặc đã hết hạn / bị thu hồi. Tạo token mới trong CVAT rồi thử lại."
        return Response({"detail": message}, status=http_status.HTTP_400_BAD_REQUEST)

    cvat_id, cvat_username = me.get("id"), me.get("username", "")
    if not cvat_id:
        return Response({"detail": "CVAT không trả về thông tin người dùng."}, status=http_status.HTTP_502_BAD_GATEWAY)
    owner = CvatAccount.objects.filter(cvat_user_id=cvat_id).exclude(user=user).select_related("user").first()
    if owner:
        raise ValidationError({"token": f"Tài khoản CVAT “{cvat_username}” đã được liên kết với một người khác trên VanoHub."})

    with transaction.atomic():
        CvatAccount.objects.update_or_create(user=user, defaults={"cvat_user_id": cvat_id, "cvat_username": cvat_username})
        _log(user, "cvat.link", cvat_username=cvat_username, cvat_user_id=cvat_id)
    data = _link_state(user, _sync_held_jobs(user))
    # Organization trên CVAT mà tài khoản này là thành viên → hiện trên VanoHub ngay.
    data["organizations"] = sync_organizations_quietly(user)
    return Response(data, status=http_status.HTTP_200_OK)


@api_view(["POST"])
def sync_organizations_view(request):
    """POST /api/cvat/sync-organizations/ — kéo CVAT organization (và vai trò thành viên) về VanoHub.

    Ai cũng gọi được: chỉ phản chiếu đúng việc phân quyền trên CVAT, không tự cấp thêm quyền nào khác.
    """
    try:
        return Response(sync_organizations(request.user))
    except CvatError as exc:
        return Response({"detail": str(exc)}, status=http_status.HTTP_502_BAD_GATEWAY)
