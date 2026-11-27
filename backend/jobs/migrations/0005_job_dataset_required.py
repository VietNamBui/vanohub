import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0004_job_dataset"),
        ("projects", "0006_cvat_structure_finish"),
    ]

    operations = [
        migrations.AlterField(
            model_name="job", name="dataset",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                    related_name="jobs", to="projects.dataset"),
        ),
    ]
