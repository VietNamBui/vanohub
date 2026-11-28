from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from . import views
from .serializers import VanoHubTokenObtainPairSerializer, VanoHubTokenRefreshSerializer

urlpatterns = [
    # Gửi username + password → nhận access token (ngắn hạn) và refresh token (dài hạn).
    path(
        "token/",
        TokenObtainPairView.as_view(serializer_class=VanoHubTokenObtainPairSerializer),
        name="token_obtain_pair",
    ),
    # Gửi refresh token → nhận access token mới khi access token cũ hết hạn.
    path(
        "token/refresh/",
        TokenRefreshView.as_view(serializer_class=VanoHubTokenRefreshSerializer),
        name="token_refresh",
    ),
    path("me/", views.MeView.as_view(), name="me"),
    path("me/password/", views.ChangePasswordView.as_view(), name="change-password"),
]
