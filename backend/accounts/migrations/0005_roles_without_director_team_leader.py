import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Vai trò chỉ còn PM / QC2 / QC1 / Annotator; mọi vai trò đều gắn với một organization (model Project)."""

    dependencies = [
        ("accounts", "0004_drop_director_team_leader"),
        ("projects", "0008_org_structure_finish"),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="roleassignment", name="role_scope_matches_role"),
        migrations.RemoveConstraint(model_name="roleassignment", name="unique_role_per_scope"),
        migrations.AlterField(
            model_name="roleassignment", name="role",
            field=models.CharField(choices=[("project_manager", "Project Manager"), ("qc2", "QC2 Auditor"),
                                            ("qc1", "QC1 Reviewer"), ("annotator", "Annotator")], max_length=32),
        ),
        migrations.AlterField(
            model_name="roleassignment", name="project",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="role_assignments",
                                    to="projects.project"),
        ),
        migrations.AddConstraint(
            model_name="roleassignment",
            constraint=models.UniqueConstraint(fields=("user", "role", "project"), name="unique_role_per_project"),
        ),
    ]
