from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import RoleAssignment, User


class RoleAssignmentInline(admin.TabularInline):
    """Hiện bảng vai trò ngay trong trang sửa User."""

    model = RoleAssignment
    fk_name = "user"  # RoleAssignment có 2 FK tới User (user, granted_by) → chỉ rõ dùng FK nào.
    fields = ["role", "project", "granted_by", "created_at"]
    readonly_fields = ["created_at"]
    extra = 0


@admin.register(User)
class VanohubUserAdmin(UserAdmin):
    inlines = [RoleAssignmentInline]


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ["user", "role", "project", "granted_by", "created_at"]
    list_filter = ["role", "project"]
    search_fields = ["user__username", "user__email", "project__name"]
