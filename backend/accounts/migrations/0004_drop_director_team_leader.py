"""Bỏ vai trò Director và Team Leader (chốt 2026-11-26: chỉ còn PM, QC1, QC2, Annotator — PM quản lý tất cả).

Chỉ xoá dữ liệu; đổi cấu trúc bảng ở migration sau (PostgreSQL không cho đổi bảng trong cùng giao dịch vừa xoá dữ liệu).
Người có thêm vai trò khác vẫn giữ các vai trò đó.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    RoleAssignment = apps.get_model("accounts", "RoleAssignment")
    RoleAssignment.objects.filter(role__in=["director", "team_leader"]).delete()
    RoleAssignment.objects.filter(project__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_user_initial_password"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
