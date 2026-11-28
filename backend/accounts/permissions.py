"""Phân quyền theo organization (Multi-Role RBAC + Scope).

Ý tưởng: thay vì kiểm tra "có phải PM không" rải rác trong từng view, mỗi thao tác
được gắn với một *capability* (quyền nghiệp vụ). Bảng CAPABILITY_ROLES bên dưới chính
là "ma trận quyền": capability nào dành cho vai trò nào.

Vì PM kéo theo QC2 (expand_roles), capability dành cho QC2 tự động có ở PM,
nhưng capability dành cho PM KHÔNG có ở người chỉ có QC2.
"""

from typing import Any, cast

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from .datetime_utils import parse_int_param
from .models import Role, RoleAssignment, expand_roles

ALL_PROJECT_ROLES = set(Role)


class Cap:
    """Tên các capability. Dùng hằng số để tránh gõ sai chuỗi."""

    VIEW_PROJECT = "view_project"
    VIEW_DASHBOARD = "view_dashboard"
    VIEW_JOBS = "view_jobs"
    MANAGE_DATA = "manage_data"  # Project (Dataset), Task (Batch), đồng bộ CVAT, khoá
    MANAGE_JOBS = "manage_jobs"  # giao lại, deadline, khoá job, xử lý escalation
    MANAGE_TEAM = "manage_team"  # team, roster, điều chuyển, tạo thành viên
    MANAGE_SETTINGS = "manage_settings"  # rework, sampling, ngưỡng KPI
    MANAGE_AUDITS = "manage_audits"  # quản lý audit QC2, phân auditor
    PERFORM_AUDIT = "perform_audit"  # QC2 Pass / Reject, ghi lỗi
    MANAGE_QUALITY_CATALOG = "manage_quality_catalog"  # danh mục lỗi, guideline
    VIEW_GUIDELINES = "view_guidelines"
    MANAGE_DELIVERY = "manage_delivery"
    SEND_ANNOUNCEMENT = "send_announcement"
    VIEW_ACTIVITY = "view_activity"
    ANNOTATE_JOBS = "annotate_jobs"  # Annotator: xem job được giao, bắt đầu / nộp bài / làm lại rework
    PERFORM_QC1 = "perform_qc1"  # QC1: xem hàng chờ QC1, bắt đầu / Pass / Reject QC1


CAPABILITY_ROLES = {
    Cap.VIEW_PROJECT: ALL_PROJECT_ROLES,
    Cap.VIEW_DASHBOARD: {Role.PROJECT_MANAGER},
    Cap.VIEW_JOBS: {Role.PROJECT_MANAGER},
    Cap.MANAGE_DATA: {Role.PROJECT_MANAGER},
    Cap.MANAGE_JOBS: {Role.PROJECT_MANAGER},
    Cap.MANAGE_TEAM: {Role.PROJECT_MANAGER},
    Cap.MANAGE_SETTINGS: {Role.PROJECT_MANAGER},
    Cap.MANAGE_AUDITS: {Role.PROJECT_MANAGER},
    Cap.PERFORM_AUDIT: {Role.QC2},
    Cap.MANAGE_QUALITY_CATALOG: {Role.PROJECT_MANAGER},
    Cap.VIEW_GUIDELINES: ALL_PROJECT_ROLES,
    Cap.MANAGE_DELIVERY: {Role.PROJECT_MANAGER},
    Cap.SEND_ANNOUNCEMENT: {Role.PROJECT_MANAGER},
    Cap.VIEW_ACTIVITY: {Role.PROJECT_MANAGER},
    Cap.ANNOTATE_JOBS: {Role.ANNOTATOR},
    Cap.PERFORM_QC1: {Role.QC1},
}


def capabilities_for_roles(roles):
    return {cap for cap, allowed in CAPABILITY_ROLES.items() if allowed & set(roles)}


def get_project_capabilities(user, project):
    direct = list(
        RoleAssignment.objects.filter(user=user, project=project).values_list("role", flat=True)
    )
    if getattr(user, "is_superuser", False):
        direct.append(Role.PROJECT_MANAGER)
    return capabilities_for_roles(expand_roles(direct))


class HasProjectCapability(BasePermission):
    """Permission class của DRF: chặn với 403 nếu thiếu capability cần cho thao tác."""

    message = "Bạn không có quyền thực hiện thao tác này trong organization."

    def has_permission(self, request: Request, view: APIView) -> Any:
        if not request.user or not request.user.is_authenticated:
            return False
        scoped_view: Any = view
        scoped_view.get_project()
        required = scoped_view.get_required_capability()
        if required is None:
            return True
        if isinstance(required, (list, tuple, set)):  # chỉ cần một trong các capability
            return any(cap in scoped_view.capabilities for cap in required)
        return required in scoped_view.capabilities


class ProjectScopedViewMixin:
    """Dùng cho mọi view nằm dưới /api/projects/<project_id>/...

    - self.project: organization lấy từ URL (404 nếu user không thuộc organization).
    - self.capabilities: các capability của user trong organization.
    - required_capabilities: {action hoặc HTTP method: capability}. Khoá "*" là mặc định.
    """

    kwargs: dict[str, Any]
    request: Any
    capabilities: set[str]
    permission_classes: Any = [HasProjectCapability]
    required_capabilities: dict[str, Any] = {"*": Cap.VIEW_PROJECT}

    def get_serializer_context(self) -> dict[str, Any]:
        parent_fn = getattr(super(), "get_serializer_context", None)
        context: dict[str, Any] = cast(dict[str, Any], parent_fn()) if callable(parent_fn) else {}
        context["project"] = self.get_project()
        return context

    def get_project(self):
        if not hasattr(self, "_project"):
            from projects.models import Project  # import trễ để tránh import vòng

            try:
                project_id = parse_int_param(self.kwargs.get("project_id"), "project_id")
            except ValidationError as exc:
                raise NotFound() from exc
            self._project = get_object_or_404(Project, pk=project_id)
            self.capabilities = get_project_capabilities(self.request.user, self._project)
            if not self.capabilities:
                raise NotFound()  # Không tiết lộ organization có tồn tại hay không.
        return self._project

    @property
    def project(self):
        return self.get_project()

    def get_required_capability(self):
        method = (self.request.method or "").lower()
        key = getattr(self, "action", None) or method
        return self.required_capabilities.get(key, self.required_capabilities.get("*"))

    def has_cap(self, capability):
        self.get_project()
        return capability in self.capabilities
