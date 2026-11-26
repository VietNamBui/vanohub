from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from .models import User
from .serializers import ChangePasswordSerializer, CurrentUserSerializer, ProfileUpdateSerializer, UserBriefSerializer


@api_view(["GET", "PATCH"])
def me(request):
    """Đọc hoặc cập nhật hồ sơ & tuỳ chọn thông báo của user đang đăng nhập.

    Không khai báo permission_classes → dùng mặc định IsAuthenticated trong settings.
    """
    user = User.objects.prefetch_related("role_assignments__project").get(pk=request.user.pk)
    if request.method == "PATCH":
        serializer = ProfileUpdateSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        user = User.objects.prefetch_related("role_assignments__project").get(pk=request.user.pk)
    return Response(CurrentUserSerializer(user).data)


@api_view(["POST"])
def change_password(request):
    """Đổi mật khẩu cho tài khoản đang đăng nhập."""
    serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    request.user.set_password(serializer.validated_data["new_password"])
    request.user.save(update_fields=["password"])
    return Response({"detail": "Đã cập nhật mật khẩu."}, status=status.HTTP_200_OK)


@api_view(["GET"])
def users_list(request):
    """GET /api/auth/users/ — Danh sách tài khoản đang hoạt động (dành cho PM để gán PM / thành viên)."""
    if not request.user.is_pm():
        raise PermissionDenied("Chỉ Project Manager mới xem được danh sách người dùng toàn tổ chức.")
    qs = User.objects.filter(is_active=True).order_by("username")
    q = (request.query_params.get("search") or "").strip()
    if q:
        from django.db.models import Q

        qs = qs.filter(
            Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q)
        )
    return Response([
        {**UserBriefSerializer(u).data, "email": u.email}
        for u in qs
    ])
