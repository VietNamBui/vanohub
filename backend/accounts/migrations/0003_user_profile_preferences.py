# Generated manually to add user profile and notification preference fields.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_roleassignment"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="avatar_url",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="user",
            name="notify_deadline",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="user",
            name="notify_qc_pass",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="user",
            name="notify_request_updates",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="user",
            name="notify_rework",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="user",
            name="timezone_name",
            field=models.CharField(default="Asia/Ho_Chi_Minh", max_length=64),
        ),
    ]
