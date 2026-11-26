"""Bước 1/2 đổi sang ánh xạ CVAT Organization → Project → Task → Job (chốt 2026-11-25).

Project (model) = CVAT organization, Dataset = CVAT project, Batch = CVAT task. Thêm cột mới (cho phép trống).
"""

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0006_cvat_structure_finish"),
    ]

    operations = [
        migrations.AddField(
            model_name="project", name="cvat_org_id",
            field=models.PositiveIntegerField(blank=True, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="project", name="cvat_org_slug", field=models.CharField(blank=True, max_length=60),
        ),
        migrations.AlterField(
            model_name="project", name="sampling_rate",
            field=models.PositiveSmallIntegerField(
                default=20, help_text="% số frame của mỗi job được QC2 kiểm.",
                validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(100)],
            ),
        ),
        migrations.AddField(
            model_name="dataset", name="cvat_project_id",
            field=models.PositiveIntegerField(blank=True, null=True, unique=True),
        ),
        migrations.RemoveConstraint(model_name="batch", name="unique_batch_name_per_project"),
        migrations.AddField(
            model_name="batch", name="dataset",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE,
                                    related_name="batches", to="projects.dataset"),
        ),
        migrations.AddField(
            model_name="batch", name="cvat_task_id",
            field=models.PositiveIntegerField(blank=True, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="batch", name="last_synced_at", field=models.DateTimeField(blank=True, null=True),
        ),
    ]
