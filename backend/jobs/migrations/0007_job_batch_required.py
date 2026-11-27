import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Tách khỏi 0006: PostgreSQL không cho đổi bảng trong cùng giao dịch vừa xoá dữ liệu."""

    dependencies = [
        ("jobs", "0006_job_task_required"),
    ]

    operations = [
        migrations.AddField(model_name="job", name="cvat_start_frame", field=models.PositiveIntegerField(default=0)),
        migrations.AlterField(
            model_name="job", name="batch",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="jobs", to="projects.batch"),
        ),
    ]
