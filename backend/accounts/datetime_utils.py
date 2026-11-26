"""Tiện ích chuẩn hóa ngày giờ lấy backend/config/settings.py làm gốc.

- Lưu trữ DB theo UTC (TIME_ZONE='UTC', USE_TZ=True), đồng nhất với PostgreSQL & ClickHouse của CVAT.
- Đầu vào/đầu ra API datetime tuân thủ chặt RFC 3339 (ISO 8601 kèm múi giờ Z hoặc ±HH:MM).
- Cắt ngày nghiệp vụ cố định theo múi giờ Việt Nam (settings.APP_TIME_ZONE = 'Asia/Ho_Chi_Minh').
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

# RFC 3339 Section 5.6 (strict): YYYY-MM-DDTHH:MM:SS[.fraction](Z|±HH:MM)
RFC3339_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:[Zz]|[+-]\d{2}:\d{2})$"
)
# ISO 8601 date-only: YYYY-MM-DD
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def app_timezone_name() -> str:
    return str(getattr(settings, "APP_TIME_ZONE", "Asia/Ho_Chi_Minh"))


def app_timezone() -> ZoneInfo:
    """Múi giờ nghiệp vụ cố định của hệ thống (Asia/Ho_Chi_Minh)."""
    return ZoneInfo(app_timezone_name())


def format_rfc3339_utc(value: datetime | None) -> str | None:
    """Định dạng datetime về chuỗi RFC 3339 chuẩn UTC kết thúc bằng 'Z'."""
    if value is None:
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value, UTC)
    iso = value.astimezone(UTC).isoformat()
    if iso.endswith("+00:00"):
        return iso[:-6] + "Z"
    return iso


def parse_rfc3339_datetime(raw: str) -> datetime:
    """Parse chặt chuỗi RFC 3339 (bắt buộc kèm Z hoặc ±HH:MM) và chuẩn hóa về UTC."""
    text = raw.strip()
    if not RFC3339_DATETIME_RE.match(text):
        raise ValueError(
            "Thời gian phải đúng chuẩn RFC 3339 kèm múi giờ (VD: 2026-11-26T08:30:00Z hoặc 2026-11-26T15:30:00+07:00)."
        )
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("Giá trị ngày giờ không hợp lệ theo lịch.") from exc
    if timezone.is_naive(parsed):
        raise ValueError("Thời gian phải có thông tin múi giờ (Z hoặc ±HH:MM).")
    return parsed.astimezone(UTC)


def parse_query_date_bound(
    raw: str,
    *,
    field_name: str,
    tz: ZoneInfo | None = None,
    end_of_day: bool = False,
    allow_datetime: bool = True,
) -> datetime:
    """Parse query param ngày/giờ sang mốc UTC; ném DRF ValidationError (400) nếu sai định dạng."""
    target_tz = tz or app_timezone()
    text = raw.strip()
    if ISO_DATE_RE.match(text):
        try:
            day = date.fromisoformat(text)
        except ValueError as exc:
            raise ValidationError({field_name: "Giá trị ngày không hợp lệ theo lịch."}) from exc
        boundary = time.max if end_of_day else time.min
        return datetime.combine(day, boundary, tzinfo=target_tz).astimezone(UTC)

    if allow_datetime:
        try:
            return parse_rfc3339_datetime(text)
        except ValueError as exc:
            raise ValidationError(
                {
                    field_name: (
                        "Tham số ngày/giờ phải theo chuẩn ISO 8601 YYYY-MM-DD "
                        "hoặc RFC 3339 kèm múi giờ (VD: 2026-11-26T08:30:00Z)."
                    )
                }
            ) from exc

    raise ValidationError({field_name: "Ngày phải đúng chuẩn ISO 8601 YYYY-MM-DD (VD: 2026-11-26)."})


def parse_query_date_range(
    params: Mapping[str, str],
    *,
    from_key: str,
    to_key: str,
    tz: ZoneInfo | None = None,
    allow_datetime: bool = True,
) -> tuple[datetime | None, datetime | None]:
    """Parse cặp tham số lọc khoảng thời gian và kiểm tra from <= to."""
    raw_from = params.get(from_key)
    raw_to = params.get(to_key)
    start = (
        parse_query_date_bound(
            raw_from, field_name=from_key, tz=tz, end_of_day=False, allow_datetime=allow_datetime
        )
        if raw_from
        else None
    )
    end = (
        parse_query_date_bound(
            raw_to, field_name=to_key, tz=tz, end_of_day=True, allow_datetime=allow_datetime
        )
        if raw_to
        else None
    )
    if start is not None and end is not None and start > end:
        raise ValidationError({to_key: f"Mốc '{to_key}' phải lớn hơn hoặc bằng '{from_key}'."})
    return start, end


class RFC3339DateTimeField(serializers.DateTimeField):
    """DRF DateTimeField siết chặt RFC 3339 (bắt buộc có Z/±HH:MM) và luôn chuẩn hóa UTC."""

    def default_timezone(self):
        return UTC

    def to_internal_value(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            if timezone.is_naive(value):
                self.fail("invalid")
            return value.astimezone(UTC)
        if isinstance(value, date) or not isinstance(value, str):
            raise serializers.ValidationError(
                "Thời gian phải là chuỗi RFC 3339 kèm múi giờ (VD: 2026-11-26T08:30:00Z)."
            )
        try:
            return parse_rfc3339_datetime(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def to_representation(self, value: Any) -> Any:
        if not value:
            return None
        if isinstance(value, datetime):
            return format_rfc3339_utc(value)
        return super().to_representation(value)
