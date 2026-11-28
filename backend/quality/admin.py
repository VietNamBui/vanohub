from django.contrib import admin

from .models import Audit, AuditSample, ErrorCategory, JobIssue, ReviewError


@admin.register(ErrorCategory)
class ErrorCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "primary_category", "project", "severity", "applies_to", "is_active"]
    list_filter = ["project", "primary_category", "applies_to", "is_active"]


class AuditSampleInline(admin.TabularInline):
    model = AuditSample
    fields = ("job", "stratum", "auditor", "result", "reviewed_by", "reviewed_at")
    readonly_fields = fields
    extra = 0


@admin.register(Audit)
class AuditAdmin(admin.ModelAdmin):
    list_display = ["id", "batch", "status", "method", "sampling_rate", "eligible_count", "created_at"]
    list_filter = ["project", "status"]
    inlines = [AuditSampleInline]


@admin.register(JobIssue)
class JobIssueAdmin(admin.ModelAdmin):
    list_display = [
        "cvat_issue_id",
        "job",
        "defect_code",
        "primary_category",
        "severity",
        "author_stage",
        "authority_status",
        "status",
        "is_disputed",
        "tampered",
        "source_missing",
    ]
    list_filter = ["project", "status", "severity", "authority_status", "author_stage", "is_disputed", "tampered"]


@admin.register(ReviewError)
class ReviewErrorAdmin(admin.ModelAdmin):
    list_display = ["job", "stage", "category", "severity", "rework_round", "reported_by", "created_at"]
    list_filter = ["stage", "severity"]
