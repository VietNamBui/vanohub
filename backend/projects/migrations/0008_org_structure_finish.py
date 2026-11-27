import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0007_org_structure_prepare"),
        ("jobs", "0007_job_batch_required"),
    ]

    operations = [
        migrations.RemoveField(model_name="project", name="cvat_project_id"),
        migrations.RemoveField(model_name="dataset", name="cvat_task_id"),
        migrations.AlterField(
            model_name="batch", name="dataset",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                    related_name="batches", to="projects.dataset"),
        ),
    ]
