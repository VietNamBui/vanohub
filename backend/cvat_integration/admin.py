from django.contrib import admin

from .models import CvatAccount, CvatAssigneeOutbox


@admin.register(CvatAccount)
class CvatAccountAdmin(admin.ModelAdmin):
    list_display = ["user", "cvat_username", "cvat_user_id", "linked_at"]
    search_fields = ["user__username", "cvat_username"]


@admin.register(CvatAssigneeOutbox)
class CvatAssigneeOutboxAdmin(admin.ModelAdmin):
    list_display = ["id", "job_id", "cvat_job_id", "target_cvat_user_id", "status", "attempts", "next_retry_at"]
    list_filter = ["status"]
    search_fields = ["job_id", "cvat_job_id"]
