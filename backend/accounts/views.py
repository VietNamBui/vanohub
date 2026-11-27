from typing import Any, cast

from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import User
from .serializers import (
    ChangePasswordSerializer,
    CurrentUserSerializer,
    ProfileUpdateSerializer,
    UserBriefSerializer,
)


def _load_current_user(user_pk: Any) -> User:
    return (
        User.objects.select_related("cvat_account")
        .prefetch_related("role_assignments__project")
        .get(pk=user_pk)
    )


class MeView(APIView):
    """Đọc hoặc cập nhật hồ sơ & tuỳ chọn thông báo của user đang đăng nhập.

    Không khai báo permission_classes → dùng mặc định IsAuthenticated trong settings.
    """

    def get(self, request: Request) -> Response:
        user = _load_current_user(request.user.pk)
        return Response(CurrentUserSerializer(user).data)

    def patch(self, request: Request) -> Response:
        user = _load_current_user(request.user.pk)
        serializer = ProfileUpdateSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        user = _load_current_user(request.user.pk)
        return Response(CurrentUserSerializer(user).data)


class ChangePasswordView(APIView):
    """POST /api/auth/me/password/ (và alias /api/auth/change-password/) — người dùng tự đổi mật khẩu.

    Đổi xong thì xoá bản mã hoá của mật khẩu tạm → PM không còn xem được mật khẩu nữa.
    """

    def post(self, request: Request) -> Response:
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserListView(APIView):
    """GET /api/auth/users/ — Danh sách tài khoản đang hoạt động (chỉ PM hoặc superuser)."""

    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        if not user.is_pm():
            raise PermissionDenied("Chỉ Project Manager mới xem được danh sách người dùng toàn tổ chức.")
        qs = User.objects.filter(is_active=True).order_by("username")
        q = (request.query_params.get("search") or "").strip()
        if q:
            qs = qs.filter(
                Q(username__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(email__icontains=q)
            )
        return Response([{**dict(UserBriefSerializer(u).data), "email": u.email} for u in qs])


me = MeView.as_view()
change_password = ChangePasswordView.as_view()
users_list = UserListView.as_view()
