"""python manage.py sync_cvat — đồng bộ toàn bộ từ CVAT (dùng cho cron / Task Scheduler).

1. CVAT organization → "Organization" VanoHub (+ vai trò theo thành viên).
2. Mỗi organization: CVAT project → Project, task → Task, job → Job, trạng thái, assignee, lượt QC2.
"""

from typing import Any

from django.core.management.base import BaseCommand

from cvat_integration.client import CvatError
from cvat_integration.sync import sync_organization, sync_organizations
from projects.models import Project


class Command(BaseCommand):
    help = "Đồng bộ organization, project, task và job từ CVAT."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--count-objects", action="store_true", help="Đếm lại số object của từng job (chậm).")

    def handle(self, *args: Any, count_objects: bool = False, **options: Any) -> None:
        result = sync_organizations()
        self.stdout.write(
            f"Organization: tạo {len(result['created'])}, thêm PM {len(result['pm_added'])}, "
            f"chưa có PM {len(result['waiting'])}"
        )
        for project in Project.objects.filter(cvat_org_id__isnull=False):
            try:
                summary = sync_organization(project, None, count_objects=count_objects)
                self.stdout.write(f"  {project.name}: {summary}")
            except CvatError as exc:
                self.stderr.write(f"  {project.name}: LỖI {exc}")
