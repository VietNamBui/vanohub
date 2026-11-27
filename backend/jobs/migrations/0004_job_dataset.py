"""Job thuộc trực tiếp một Dataset (CVAT task); Batch thành tuỳ chọn. Chuyển dữ liệu cũ:

- Batch.project  ← Batch.dataset.project
- Job.dataset    ← Job.batch.dataset (job giữ nguyên batch hiện tại)
- Dataset.cvat_task_id ← cvat_task_id của batch (nếu dataset chỉ có đúng một task)
"""

import django.db.models.deletion
from django.db import migrations, models


def forwards(apps, schema_editor):
    Batch = apps.get_model("projects", "Batch")
    Dataset = apps.get_model("projects", "Dataset")
    Job = apps.get_model("jobs", "Job")
    for batch in Batch.objects.select_related("dataset"):
        batch.project_id = batch.dataset.project_id
        batch.save(update_fields=["project"])
    for job in Job.objects.select_related("batch"):
        job.dataset_id = job.batch.dataset_id
        job.save(update_fields=["dataset"])
    used = set()
    for dataset in Dataset.objects.all():
        task_ids = {t for t in Batch.objects.filter(dataset=dataset).values_list("cvat_task_id", flat=True) if t}
        if len(task_ids) == 1 and (task_id := task_ids.pop()) not in used:
            used.add(task_id)
            dataset.cvat_task_id = task_id
            dataset.save(update_fields=["cvat_task_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0003_job_cvat_assignee"),
        ("projects", "0005_cvat_structure_prepare"),
    ]

    operations = [
        migrations.AddField(
            model_name="job", name="dataset",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE,
                                    related_name="jobs", to="projects.dataset"),
        ),
        migrations.AlterField(
            model_name="job", name="batch",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="jobs", to="projects.batch"),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
