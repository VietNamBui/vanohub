"""Tiện ích múi giờ nghiệp vụ (Asia/Ho_Chi_Minh) và kiểm tra tham số số nguyên dùng chung."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

PG_INT32_MAX = 2_147_483_647


def app_timezone_name() -> str:
    return str(getattr(settings, "APP_TIME_ZONE", "Asia/Ho_Chi_Minh"))


def app_timezone() -> ZoneInfo:
    """Múi giờ nghiệp vụ Việt Nam cố định cho cắt ngày KPI, thống kê và định dạng hạn."""
    return ZoneInfo(app_timezone_name())


def local_now() -> datetime:
    return timezone.localtime(timezone.now(), app_timezone())


def local_datetime(value: datetime) -> datetime:
    if timezone.is_naive(value):
        value = timezone.make_aware(value, app_timezone())
    return timezone.localtime(value, app_timezone())


def local_date(value: datetime | None = None) -> date:
    return local_datetime(value or timezone.now()).date()


def format_local_datetime(value: datetime | None, fmt: str = "%d/%m %H:%M") -> str:
    if value is None:
        return ""
    return local_datetime(value).strftime(fmt)


def parse_int_param(raw, field_name: str, *, min_value: int = 1, max_value: int = PG_INT32_MAX) -> int:
    """Parse tham số số nguyên an toàn; trả 400 ValidationError thay vì 500 ValueError/DataError."""
    if isinstance(raw, bool):
        raise ValidationError({field_name: "Giá trị phải là số nguyên hợp lệ."})
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise ValidationError({field_name: "Giá trị phải là số nguyên hợp lệ."}) from exc
    if value < min_value or value > max_value:
        raise ValidationError({field_name: f"Giá trị phải nằm trong khoảng {min_value}..{max_value}."})
    return value
