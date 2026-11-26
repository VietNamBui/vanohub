"""Runtime + static validation helpers for DRF serializers."""

from collections.abc import Mapping
from typing import Any, cast

from rest_framework.exceptions import ValidationError
from rest_framework.serializers import BaseSerializer


def validated_dict(serializer: BaseSerializer[Any]) -> dict[str, Any]:
    """Ensure serializer is validated and narrow validated_data to dict[str, Any]."""
    if not hasattr(serializer, "_validated_data"):
        serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    if not isinstance(data, Mapping):
        raise ValidationError("Dữ liệu đầu vào phải là JSON object.")
    return cast(dict[str, Any], data)
