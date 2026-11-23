from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import User
from .serializers import CurrentUserSerializer


@api_view(["GET"])
def me(request):
    """Trả về user đang đăng nhập kèm các vai trò được gán.

    Không khai báo permission_classes → dùng mặc định IsAuthenticated trong settings.
    """
    user = User.objects.prefetch_related("role_assignments__project").get(pk=request.user.pk)
    return Response(CurrentUserSerializer(user).data)
