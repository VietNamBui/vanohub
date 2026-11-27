"""Job bắt buộc thuộc một Task (Batch = CVAT task). Job theo ánh xạ cũ (chưa có task) không còn đúng → xoá;
đồng bộ CVAT tạo lại theo cấu trúc mới. Batch / dataset theo ánh xạ cũ cũng xoá (dữ liệu batch: đã chốt xoá hết).
"""

from django.db import migrations


def forwards(apps, schema_editor):
    Job = apps.get_model("jobs", "Job")
    Batch = apps.get_model("projects", "Batch")
    Dataset = apps.get_model("projects", "Dataset")
    Job.objects.filter(batch__isnull=True).delete()
    Job.objects.filter(batch__dataset__isnull=True).delete()
    Batch.objects.filter(dataset__isnull=True).delete()
    Dataset.objects.filter(cvat_task_id__isnull=False).delete()  # dataset = CVAT task (ánh xạ cũ)


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0005_job_dataset_required"),
        ("projects", "0007_org_structure_prepare"),
        ("quality", "0002_review_error_category_restrict"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
