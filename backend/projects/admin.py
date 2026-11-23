from django.contrib import admin

from accounts.models import RoleAssignment

from .models import ActivityLog, Announcement, Batch, Dataset, Delivery, Guideline, Project


class ProjectRoleAssignmentInline(admin.TabularInline):
    """Gán PM / QC2 / ... cho dự án ngay trong trang sửa Project."""

    model = RoleAssignment
    fk_name = "project"
    fields = ["user", "role", "granted_by", "created_at"]
    readonly_fields = ["created_at"]
    autocomplete_fields = ["user"]
    extra = 1


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["name", "created_by", "created_at"]
    search_fields = ["name"]
    readonly_fields = ["created_by", "created_at", "updated_at"]
    inlines = [ProjectRoleAssignmentInline]

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)




@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = ["name", "project", "status", "created_at"]
    list_filter = ["project", "status"]
    search_fields = ["name"]


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ["name", "dataset", "status", "deadline", "cvat_task_id", "last_synced_at"]
    list_filter = ["status", "dataset__project"]
    search_fields = ["name"]


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = ["batch", "project", "delivered_by", "delivered_at"]


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "project", "actor", "action", "target_label"]
    list_filter = ["project", "action"]
    readonly_fields = [f.name for f in ActivityLog._meta.fields]  # nhật ký chỉ xem, không sửa


admin.site.register(Announcement)
admin.site.register(Guideline)
