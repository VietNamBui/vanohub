"""python manage.py drain_cvat_outbox — đẩy hàng đợi assignee CVAT còn tồn (cron / worker)."""

from typing import Any

from django.core.management.base import BaseCommand

from cvat_integration.assignee import drain_cvat_outbox


class Command(BaseCommand):
    help = "Đẩy các yêu cầu cập nhật assignee CVAT đang chờ trong CvatAssigneeOutbox."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--limit", type=int, default=100, help="Số lượng job tối đa xử lý trong một lượt.")
        parser.add_argument("--force", action="store_true", help="Bỏ qua thời gian chờ retry (next_retry_at).")
        parser.add_argument("--max-attempts", type=int, default=10, help="Số lần thử tối đa trước khi đánh dấu dead.")

    def handle(
        self,
        *args: Any,
        limit: int = 100,
        force: bool = False,
        max_attempts: int = 10,
        **options: Any,
    ) -> None:
        stats = drain_cvat_outbox(batch_limit=max(1, limit), force=force, max_attempts=max(1, max_attempts))
        if stats.get("locked"):
            self.stdout.write("Outbox đang được worker khác xử lý (advisory lock).")
            return
        self.stdout.write(
            f"Outbox: claimed={stats['claimed']}, pushed={stats['pushed']}, "
            f"failed={stats['failed']}, dead={stats['dead']}, skipped={stats['skipped']}"
        )
