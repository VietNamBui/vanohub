from django.db import migrations


class Migration(migrations.Migration):
    """Bỏ Team Leader (chốt 2026-11-26): team không còn trường leader."""

    dependencies = [
        ("teams", "0001_initial"),
    ]

    operations = [
        migrations.RemoveField(model_name="team", name="leader"),
    ]
