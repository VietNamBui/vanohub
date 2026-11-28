from django.db import migrations


def backfill_error_category_taxonomy(apps, schema_editor):
    Project = apps.get_model("projects", "Project")
    ErrorCategory = apps.get_model("quality", "ErrorCategory")

    name_to_taxonomy = {
        "Thiếu đối tượng": ("E1", "E1"),
        "Thiếu object": ("E1", ""),
        "Sai nhãn lớp": ("E2", "E2"),
        "Sai nhãn": ("E2", ""),
        "Lệch khung / biên": ("E3", "E3"),
        "Sai kích thước cuboid": ("E3", ""),
        "Gán nhầm / thừa": ("E4", "E4"),
        "Sai thuộc tính": ("E5", "E5"),
        "Lỗi liên kết track": ("E6", "E6"),
        "Sai tracking ID": ("E6", ""),
    }

    for project in Project.objects.all().iterator():
        cats = list(ErrorCategory.objects.filter(project=project).order_by("id"))
        used_codes = {cat.code for cat in cats if cat.code}
        has_e6 = False
        for cat in cats:
            if cat.code == "E6" or cat.name == "Lỗi liên kết track":
                has_e6 = True
            mapping = name_to_taxonomy.get(cat.name)
            if mapping is None:
                continue
            primary, default_code = mapping
            update_fields = []
            if not cat.primary_category:
                cat.primary_category = primary
                update_fields.append("primary_category")
            if not cat.code and default_code and default_code not in used_codes:
                cat.code = default_code
                used_codes.add(default_code)
                update_fields.append("code")
            if update_fields:
                cat.save(update_fields=update_fields)

        if cats and not has_e6 and "E6" not in used_codes:
            ErrorCategory.objects.create(
                project=project,
                code="E6",
                primary_category="E6",
                name="Lỗi liên kết track",
                description="Sai hoặc đứt gãy track ID giữa các frame",
                severity="major",
                applies_to="both",
                is_active=True,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("quality", "0006_jobissue_errorcategory_code_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_error_category_taxonomy, migrations.RunPython.noop),
    ]
