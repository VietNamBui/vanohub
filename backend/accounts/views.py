from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from .models import User
from .serializers import ChangePasswou bật Near-Real-Time (phải xử lý trước)
Vẽ nháp rồi xóa giữa ngày: Hiện DailyOutputRecord chỉ ghi delta dương (cvat_count - last_counted_objects > 0). Nếu sync mỗi 5 phút:
Annotator vẽ 50 cuboid (sync ghi +50) → xóa 20 còn 30 → vẽ lại 20 thành 50: nhờ last_counted_objects = 50 nên không bị cộng đúp (delta = 0).
Nhưng nếu vẽ nháp 50 rồi xóa vĩnh viễn còn 30 rồi nộp job: KPI ngày vẫn dính 50 (phồng 20) trừ khi cho phép ghi bút toán điều chỉnh âm (objects_count < 0) lúc sync/submit.
OT xuyên 00:00: Sync nền chạy theo đồng hồ hệ thống — nếu không có workday_cutoff_hour (vd 04:00), phần Annotator lưu lúc 00:15 sẽ tự rơi sang KPI ngày hôm sau.
Bắt buộc hướng dẫn vận hành: Dù chọn B hay C, bắt buộc Annotator bật Auto-save (vd 5 phút) hoặc có thói quen bấm Ctrl+S trước khi rời máy/hết ca.rdSerializer, CurrentUserSerializer, ProfileUpdateSerializer, UserBriefSerializer
from .validation import validated_dict


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
    data = validated_dict(serializer)
    request.user.set_password(data["new_password"])
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
        {**dict(UserBriefSerializer(u).data), "email": u.email}
        for u in qs
    ])
