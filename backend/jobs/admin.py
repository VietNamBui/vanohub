from django.contrib import admin

from .models import Job


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ["name", "project", "dataset", "batch", "status", "annotator", "qc1_reviewer", "deadline",
                    "rework_round", "is_escalated", "is_locked", "cvat_job_id"]
    list_filter = ["project", "status", "is_escalated", "is_locked"]
    search_fields = ["name", "cvat_job_id"]
    autocomplete_fields = ["annotator", "qc1_reviewer"]
