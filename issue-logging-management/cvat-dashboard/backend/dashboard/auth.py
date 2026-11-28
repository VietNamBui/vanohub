from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.core.exceptions import ImproperlyConfigured
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import AuthenticationFailed

logger = logging.getLogger(__name__)
User = get_user_model()


def get_cvat_base_url() -> str:
    url = getattr(settings, "CVAT_BASE_URL", "").rstrip("/")
    if not url:
        return ""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    is_loopback = host in ("localhost", "127.0.0.1", "::1")
    if parsed.scheme == "http" and not is_loopback:
        if getattr(settings, "CVAT_REQUIRE_HTTPS", False):
            raise ImproperlyConfigured(
                "CVAT_BASE_URL must use HTTPS for non-loopback hosts when CVAT_REQUIRE_HTTPS is enabled."
            )
        if not getattr(settings, "DEBUG", False):
            logger.warning("CVAT_BASE_URL (%s) uses plain HTTP for non-loopback host.", url)
    return url


def verify_with_cvat(token_str: str) -> dict[str, Any] | None:
    cvat_url = get_cvat_base_url()
    if not cvat_url:
        return None
    try:
        resp = requests.get(
            f"{cvat_url}/api/users/self",
            headers={"Authorization": f"Token {token_str}"},
            timeout=5,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as exc:
        logger.warning("Failed to verify token with CVAT server: %s", exc)
    return None


class CVATAuthentication(BaseAuthentication):
    """
    Unified Authentication against CVAT Server.
    Validates token directly with CVAT /api/users/self when CVAT_BASE_URL is configured.
    Falls back to standard DRF Token / Session for local test/demo mode.
    """

    def authenticate(self, request: Any) -> tuple[AbstractBaseUser, Any] | None:
        auth_header = get_authorization_header(request).split()
        if not auth_header:
            return None

        if auth_header[0].lower() not in (b"token", b"bearer"):
            return None

        if len(auth_header) == 1:
            raise AuthenticationFailed("Header Authorization không hợp lệ. Thiếu chuỗi token.")
        elif len(auth_header) > 2:
            raise AuthenticationFailed("Header Authorization không hợp lệ. Chuỗi token chứa khoảng trắng.")

        try:
            token_key = auth_header[1].decode("utf-8")
        except UnicodeError as exc:
            raise AuthenticationFailed("Header Authorization chứa ký tự không hợp lệ.") from exc

        cvat_url = get_cvat_base_url()
        if cvat_url:
            cvat_user = verify_with_cvat(token_key)
            if not cvat_user:
                raise AuthenticationFailed("Token không hợp lệ hoặc tài khoản không tồn tại trên máy chủ CVAT.")

            username = cvat_user.get("username", "")
            if not username:
                raise AuthenticationFailed("Dữ liệu người dùng từ CVAT không hợp lệ.")

            email = str(cvat_user.get("email", "") or "")
            is_superuser = bool(cvat_user.get("is_superuser", False))
            is_staff = bool(cvat_user.get("is_staff", False) or is_superuser)
            user, created = User.objects.get_or_create(
                username=username,
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
                raise AuthenticationFailed("Tài khoản người dùng đã bị khóa.")

            return (user, token_key)

        # Fallback to local DRF Token for offline development and unit tests
        try:
            token = Token.objects.select_related("user").get(key=token_key)
        except Token.DoesNotExist as exc:
            raise AuthenticationFailed("Token không tồn tại hoặc đã hết hạn.") from exc

        if not token.user.is_active:
            raise AuthenticationFailed("Tài khoản người dùng đã bị khóa.")

        return (token.user, token)
