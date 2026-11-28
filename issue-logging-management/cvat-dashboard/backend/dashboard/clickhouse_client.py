from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)


def get_clickhouse_client() -> Any | None:
    """Returns ClickHouse client if clickhouse-connect is available and configured."""
    conf = getattr(settings, "CLICKHOUSE_CONFIG", {})
    host = conf.get("HOST")
    if not host:
        return None

    try:
        import clickhouse_connect  # type: ignore

        return clickhouse_connect.get_client(
            host=host,
            port=conf.get("PORT", 8123),
            database=conf.get("DB", "cvat"),
            username=conf.get("USER", "default"),
            password=conf.get("PASSWORD", ""),
        )
    except Exception as exc:
        logger.warning("ClickHouse connection not available: %s", exc)
        return None


def fetch_clickhouse_productivity_summary(days: int = 7) -> list[dict[str, Any]]:
    """
    Fetches aggregate working time and event counts per user from ClickHouse.
    Returns empty list if ClickHouse is unconfigured or unreachable.
    """
    client = get_clickhouse_client()
    if not client:
        return []

    since = datetime.now(UTC) - timedelta(days=days)
    query = """
    SELECT
        toDate(timestamp) AS d,
        user_id,
        anyIf(user_name, user_name IS NOT NULL) AS uname,
        sumIf(duration, scope = 'send:working_time') AS working_time_ms,
        countIf(scope LIKE 'qc:%') AS qc_events_count,
        count() AS total_events
    FROM events
    WHERE timestamp >= {since:DateTime64(3)} AND user_id IS NOT NULL
    GROUP BY d, user_id
    ORDER BY d DESC, working_time_ms DESC
    """
    try:
        rows = client.query(query, parameters={"since": since}).result_rows
        return [
            {
                "date": str(r[0]),
                "user_id": int(r[1]),
                "username": str(r[2] or f"User #{r[1]}"),
                "working_time_ms": int(r[3] or 0),
                "qc_events_count": int(r[4] or 0),
                "total_events": int(r[5] or 0),
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning("ClickHouse productivity query failed: %s", exc)
        return []
    finally:
        with contextlib.suppress(Exception):
            client.close()
