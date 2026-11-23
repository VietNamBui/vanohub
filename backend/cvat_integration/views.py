from django.conf import settings
from rest_framework.decorators import api_view
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
