from typing import Any, cast

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.tokens import Token

from .models import User


class VanoHubJWTAuthentication(JWTAuthentication):
    """Xác thực Bearer access token kèm kiểm tra User.token_version để thu hồi tức thì."""

    def get_user(self, validated_token: Token) -> Any:
        user = cast(User, super().get_user(validated_token))
        token_version = validated_token.get("tv")
        if token_version is None or token_version != user.token_version:
            raise AuthenticationFailed(
                "Phiên đăng nhập đã hết hiệu lực, vui lòng đăng nhập lại.",
                code="token_revoked",
            )
        return user
