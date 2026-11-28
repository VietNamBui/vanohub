from __future__ import annotations

import contextlib
import logging
from typing import Any

import requests
from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ImproperlyConfigured
from rest_framework import permissions, status
from rest_framework.authentication import get_authorization_header
from rest_framework.authtoken.models import Token
from rest_framework.response import Response
from rest_framework.views import APIView

from .auth import get_cvat_base_url, verify_with_cvat
from .models import WorkflowUser

logger = logging.getLogger(__name__)
User = get_user_model()


class LoginView(APIView):
    """
    Unified Login endpoint.
    If CVAT_BASE_URL is set, delegates login directly to CVAT (/api/auth/login).
    If user doesn't exist in CVAT, authentication fails immediately.
    """

    permission_classes = [permissions.AllowAny]
    throttle_scope = "login"

    def post(self, request: Any) -> Response:
        username = str(request.data.get("username") or "").strip()
        password = str(request.data.get("password") or "")

        if not username or not password:
            return Response(
                {"detail": "Vui lòng cung cấp cả tên đăng nhập và mật khẩu."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            cvat_url = get_cvat_base_url()
        except ImproperlyConfigured as exc:
            logger.error("CVAT configuration error: %s", exc)
            return Response(
                {"detail": "Cấu hình kết nối CVAT không hợp lệ (yêu cầu HTTPS)."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if cvat_url:
            try:
                resp = requests.post(
                    f"{cvat_url}/api/auth/login",
                    json={"username": username, "password": password},
                    timeout=8,
                )
            except Exception as exc:
                logger.error("CVAT login connection error: %s", exc)
                return Response(
                    {"detail": f"Không thể kết nối đến máy chủ CVAT ({cvat_url}): {exc}"},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            if resp.status_code != 200:
                return Response(
                    {"detail": "Tài khoản hoặc mật khẩu không chính xác trên máy chủ CVAT."},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

            data = resp.json()
            cvat_token = data.get("key")
            if not cvat_token:
                return Response(
                    {"detail": "Máy chủ CVAT không trả về token hợp lệ."},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            # Fail closed: require verified user identity from CVAT /api/users/self
            cvat_user = verify_with_cvat(cvat_token)
            if not cvat_user or not cvat_user.get("username"):
                return Response(
                    {"detail": "Không thể xác minh thông tin tài khoản từ máy chủ CVAT."},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            resolved_username = str(cvat_user["username"]).strip()
            email = str(cvat_user.get("email") or "")
            is_superuser = bool(cvat_user.get("is_superuser", False))
            is_staff = bool(cvat_user.get("is_staff", False) or is_superuser)

            user, created = User.objects.get_or_create(
                username=resolved_username,
                defaults={
                    "email": email,
                    "is_staff": is_staff,
                    "is_superuser": is_superuser,
                },
            )
            if not created:
                changed: list[str] = []
                if user.email != email:
                    user.email = email
                    changed.append("email")
                if user.is_staff != is_staff:
                    user.is_staff = is_staff
                    changed.append("is_staff")
                if user.is_superuser != is_superuser:
                    user.is_superuser = is_superuser
                    changed.append("is_superuser")
                if changed:
                    user.save(update_fields=changed)

            if not user.is_active:
                return Response(
                    {"detail": "Tài khoản người dùng đã bị khóa."},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Sync local token so both local and remote checks match
            Token.objects.get_or_create(user=user)
            return Response({
                "token": cvat_token,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "is_staff": user.is_staff,
                    "is_superuser": user.is_superuser,
                },
            })

        # Local test/offline mode
        user = authenticate(request, username=username, password=password)
        if not user:
            return Response(
                {"detail": "Tên đăng nhập hoặc mật khẩu không chính xác."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            "token": token.key,
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "is_staff": user.is_staff,
                "is_superuser": user.is_superuser,
            },
        })


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any) -> Response:
        cvat_url = get_cvat_base_url()
        auth_header = get_authorization_header(request).split()
        if cvat_url and len(auth_header) == 2:
            token_key = auth_header[1].decode("utf-8", errors="ignore")
            with contextlib.suppress(Exception):
                requests.post(
                    f"{cvat_url}/api/auth/logout",
                    headers={"Authorization": f"Token {token_key}"},
                    timeout=5,
                )

        if hasattr(request.user, "auth_token"):
            with contextlib.suppress(Exception):
                request.user.auth_token.delete()

        return Response({"detail": "Đăng xuất thành công."})


class CurrentUserView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: Any) -> Response:
        user = request.user
        wf_user = (
            WorkflowUser.objects.filter(django_user=user).first()
            or WorkflowUser.objects.filter(cvat_username__iexact=getattr(user, "username", "")).first()
        )
        if wf_user is not None:
            role = wf_user.role
        elif user.is_superuser:
            role = "admin"
        elif user.is_staff:
            role = "staff"
        else:
            role = "annotator"
        return Response({
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser,
            "role": role,
        })
