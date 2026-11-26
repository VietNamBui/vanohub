from typing import Any, cast

from django.conf import settings
from rest_framework import status as http_status
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from .client import CvatClient, CvatError


@api_view(["GET"])
def status(request):
    """GET /api/cvat/status/ — kiểm tra Vanohub có gọi được CVAT không (không trả thông tin bí mật)."""
    try:
        about = CvatClient(timeout=5).about()
        return Response({"connected": True, "url": settings.CVAT_PUBLIC_URL, "version": about.get("version")})
    except CvatError as exc:
        return Response({"connected": False, "url": settings.CVAT_PUBLIC_URL, "detail": str(exc)})


@api_view(["GET"])
def tasks(request):
    """GET /api/cvat/tasks/?project_id=&search= — danh sách CVAT task (chỉ PM) để chọn khi ánh xạ batch."""
    user = cast(Any, request.user)
    if not user.is_pm():
        raise PermissionDenied("Chỉ Project Manager mới được xem danh sách CVAT task.")
    project_id = request.query_params.get("project_id")
    search = (request.query_params.get("search") or "").strip() or None
    try:
        raw = CvatClient(timeout=10).list_tasks(
            project_id=int(project_id) if project_id and str(project_id).isdigit() else None,
            search=search,
        )
    except CvatError as exc:
        return Response({"detail": str(exc)}, status=http_status.HTTP_502_BAD_GATEWAY)
    return Response([
        {
            "id": t["id"],
            "name": t.get("name") or f"Task #{t['id']}",
            "project_id": t.get("project_id"),
            "status": t.get("status", ""),
            "size": t.get("size") or 0,
            "subset": t.get("subset", ""),
        }
        for t in raw
    ])
