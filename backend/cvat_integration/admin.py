from django.contrib import admin

from .models import CvatAccount


@admin.register(CvatAccount)
class CvatAccountAdmin(admin.ModelAdmin):
    list_display = ["user", "cvat_username", "cvat_user_id", "linked_at"]
    search_fields = ["user__username", "cvat_username"]
