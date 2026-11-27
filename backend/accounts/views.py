from typing import Any

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import User
from .serializers import (
    ChangePasswordSerializer,
    CurrentUserSerializer,
    ProfileUpdateSerializer,
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
    """POST /api/auth/me/password/ — người dùng tự đổi mật khẩu.

    Đổi xong thì xoá bản mã hoá của mật khẩu tạm → PM không còn xem được mật khẩu nữa.
    """

    def post(self, request: Request) -> Response:
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


me = MeView.as_view()
change_password = ChangePasswordView.as_view()
