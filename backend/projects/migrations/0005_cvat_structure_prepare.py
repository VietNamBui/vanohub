"""Bước 1/2 đổi cấu trúc: Project ↔ CVAT Project, Dataset ↔ CVAT Task, Batch = nhóm job của VanoHub.

Thêm cột mới (cho phép trống) để migration dữ liệu ở jobs.0004 điền vào.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0004_batch_team"),
    ]

    operations = [
        migrations.AlterField(
            model_name="project", name="cvat_project_id",
            field=models.PositiveIntegerField(blank=True, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="project", name="cvat_synced_at", field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RemoveConstraint(model_name="dataset", name="unique_dataset_name_per_project"),
        migrations.AddField(
            model_name="dataset", name="cvat_task_id",
            field=models.PositiveIntegerField(blank=True, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="dataset", name="last_synced_at", field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="batch", name="project",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE,
                                    related_name="batches", to="projects.project"),
        ),
    ]
