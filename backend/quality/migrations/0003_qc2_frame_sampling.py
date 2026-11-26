"""QC2 theo frame: mỗi lượt QC2 của job lưu các frame cần kiểm; một job có thể có nhiều lượt (sau rework)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("quality", "0002_review_error_category_restrict"),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="auditsample", name="unique_job_per_audit"),
        migrations.AddField(model_name="auditsample", name="frames", field=models.JSONField(default=list)),
        migrations.AddField(model_name="auditsample", name="rework_round",
                            field=models.PositiveSmallIntegerField(default=0)),
    ]
