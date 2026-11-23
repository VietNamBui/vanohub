from django.contrib import admin

from .models import Team, TeamMember


class TeamMemberInline(admin.TabularInline):
    model = TeamMember
    autocomplete_fields = ["user"]
    extra = 1


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ["name", "project", "leader"]
    list_filter = ["project"]
    inlines = [TeamMemberInline]
