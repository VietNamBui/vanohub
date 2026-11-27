from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .models import User
from .serializers import CurrentUserSerializer, ProfileUpdateSerializer


@api_view(["GET", "PATCH"])
def me(request):
    """Đọc hoặc cập nhật hồ sơ & tuỳ chọn thông báo của user đang đăng nhập.

    Không khai báo permission_classes → dùng mặc định IsAuthenticated trong settings.
    """
    user = User.objects.select_related("cvat_account").prefetch_related("role_assignments__project").get(pk=request.user.pk)
    if request.method == "PATCH":
        serializer = ProfileUpdateSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        user = User.objects.select_related("cvat_account").prefetch_related("role_assignments__project").get(pk=request.user.pk)
    return Response(CurrentUserSerializer(user).data)


@api_view(["POST"])
def change_password(request):
    """POST /api/auth/me/password/ {"current_password", "new_password"} — người dùng tự đổi mật khẩu.

    Đổi xong thì xoá bản mã hoá của mật khẩu tạm → PM không còn xem được mật khẩu nữa.
    """
    user = request.user
    current = request.data.get("current_password") or ""
    new = request.data.get("new_password") or ""
    if not user.check_password(current):
        raise ValidationError({"current_password": "Mật khẩu hiện tại không đúng."})
    if new == current:
        raise ValidationError({"new_password": "Mật khẩu mới phải khác mật khẩu hiện tại."})
    try:
        validate_password(new, user)
    except DjangoValidationError as exc:
        raise ValidationError({"new_password": list(exc.messages)}) from exc
    user.set_password(new)
    user.initial_password_encrypted = ""
    user.save(update_fields=["password", "initial_password_encrypted"])
    return Response(status=204)
