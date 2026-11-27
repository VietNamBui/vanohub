"""Bước 2/2: Batch không còn gắn Dataset / CVAT task; tên batch duy nhất trong dự án."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0005_cvat_structure_prepare"),
        ("jobs", "0004_job_dataset"),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="batch", name="unique_batch_name_per_dataset"),
        migrations.RemoveField(model_name="batch", name="dataset"),
        migrations.RemoveField(model_name="batch", name="cvat_task_id"),
        migrations.RemoveField(model_name="batch", name="last_synced_at"),
        migrations.AlterField(
            model_name="batch", name="project",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                    related_name="batches", to="projects.project"),
        ),
        migrations.AddConstraint(
            model_name="batch",
            constraint=models.UniqueConstraint(fields=("project", "name"), name="unique_batch_name_per_project"),
        ),
    ]
