from collections import defaultdict
from datetime import timedelta
from typing import Any, cast

from django.db import IntegrityError, transaction
from django.db.models import Count, F, Max, Prefetch, Q
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import credentials
from accounts.datetime_utils import format_rfc3339_utc, parse_int_param, parse_query_date_range
from accounts.models import Role, RoleAssignment, User, expand_roles
from accounts.permissions import CAPABILITY_ROLES, Cap, ProjectScopedViewMixin
from accounts.serializers import UserBriefSerializer
from accounts.validation import validated_dict
from cvat_integration.assignee import schedule_assignee_push
from cvat_integration.client import CvatError
from cvat_integration.sync import dataset_labels, sync_organization
from jobs.models import ACTIVE_ANNOTATOR_STATUSES, OPEN_STATUSES, STAGE_STATUSES, Job, JobStatus
from quality.issues import acceptance_blocking_batch_ids, acceptance_blocking_issues_for_jobs
from quality.models import Audit, AuditSample
from quality.qc2 import ensure_qc2_sample
from teams.models import Team, TeamMember

from .models import (
    ActivityLog,
    Announcement,
    AnnouncementRead,
    Batch,
    Dataset,
    DataStatus,
    Delivery,
    Guideline,
    Project,
    UserNotification,
)
from .notifications import BLOCKING_QC2_STATUSES, notify_review_needed, project_users_with_roles
from .serializers import (
    ActivityLogSerializer,
    AddMemberRoleSerializer,
    AnnouncementSerializer,
    BatchNoteSerializer,
    BatchSerializer,
    CreateMemberSerializer,
    DatasetSerializer,
    DeliverySerializer,
    GuidelineSerializer,
    ProjectDetailSerializer,
    ProjectListSerializer,
    ProjectSettingsSerializer,
    ProjectWriteSerializer,
    SyncCvatSerializer,
)

# PM gán / gỡ được các vai trò trong organization, trừ PM (PM lấy từ Owner / Maintainer của CVAT organization).
# Vai trò ngầm định (PM → QC2) đã có thì không gán lại.
GRANTABLE_ROLES = [Role.QC2, Role.QC1, Role.ANNOTATOR]

QC2_NON_BLOCKING_STATUSES = {
    JobStatus.QC1_PASSED,
    JobStatus.PENDING_QC2,
    JobStatus.APPROVED,
    JobStatus.DELIVERED,
}


class StandardPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500


class ProjectViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """/api/projects/ — Người dùng xem organization của mình; PM tạo/sửa organization & gán PM."""

    def _base_queryset(self):
        user = self.request.user
        now = timezone.now()
        done = [JobStatus.APPROVED, JobStatus.DELIVERED]
        queryset = Project.objects.annotate(
            job_count=Count("jobs", distinct=True),
            done_count=Count("jobs", filter=Q(jobs__status__in=done), distinct=True),
            overdue_count=Count(
                "jobs", filter=Q(jobs__deadline__lt=now, jobs__status__in=OPEN_STATUSES), distinct=True
            ),
            escalated_count=Count("jobs", filter=Q(jobs__is_escalated=True), distinct=True),
        ).prefetch_related(
            Prefetch("role_assignments", queryset=RoleAssignment.objects.filter(user=user), to_attr="my_assignments"),
            Prefetch(
                "role_assignments",
                queryset=RoleAssignment.objects.filter(role=Role.PROJECT_MANAGER).select_related("user"),
                to_attr="pm_assignments",
            ),
        )
        if self.action in {"retrieve", "create", "update", "partial_update"}:
            queryset = queryset.prefetch_related("role_assignments")
        return queryset

    def get_queryset(self) -> Any:
        queryset = self._base_queryset()
        if getattr(self.request.user, "is_superuser", False):
            return queryset
        return queryset.filter(role_assignments__user=self.request.user).distinct()

    def get_object(self) -> Any:
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        try:
            parse_int_param(self.kwargs.get(lookup_url_kwarg), "pk")
        except ValidationError as exc:
            raise NotFound("Không tìm thấy organization.") from exc
        return super().get_object()

    def get_serializer_class(self) -> Any:
        if self.action in {"create", "update", "partial_update"}:
            return ProjectWriteSerializer
        return ProjectDetailSerializer if self.action == "retrieve" else ProjectListSerializer

    def _require_any_pm(self):
        user = cast(Any, self.request.user)
        if not user.is_pm():
            raise PermissionDenied("Chỉ Project Manager mới được tạo organization.")

    def _require_project_pm(self, project):
        user = cast(Any, self.request.user)
        if not user.is_superuser and not RoleAssignment.objects.filter(
            project=project, user=user, role=Role.PROJECT_MANAGER
        ).exists():
            raise PermissionDenied(
                "Chỉ Project Manager của organization mới được chỉnh sửa thông tin organization và gán PM."
            )

    def _sync_pms(self, project, pm_ids, actor):
        target_ids = sorted(set(pm_ids))
        if not target_ids:
            raise ValidationError({"pm_ids": "Mỗi organization phải có ít nhất một Project Manager."})
        active_ids = set(
            User.objects.filter(pk__in=target_ids, is_active=True).values_list("id", flat=True)
        )
        missing = [uid for uid in target_ids if uid not in active_ids]
        if missing:
            raise ValidationError({"pm_ids": f"Không tìm thấy tài khoản hoạt động với ID: {missing}."})
        current_ids = set(
            RoleAssignment.objects.select_for_update()
            .filter(project=project, role=Role.PROJECT_MANAGER)
            .values_list("user_id", flat=True)
        )
        to_remove = sorted(current_ids - set(target_ids))
        to_add = [uid for uid in target_ids if uid not in current_ids]
        if to_remove:
            RoleAssignment.objects.filter(
                project=project, role=Role.PROJECT_MANAGER, user_id__in=to_remove
            ).delete()
            User.objects.filter(pk__in=to_remove).update(token_version=F("token_version") + 1)
        for uid in to_add:
            RoleAssignment.objects.get_or_create(
                project=project,
                user_id=uid,
                role=Role.PROJECT_MANAGER,
                defaults={"granted_by": actor},
            )

    def create(self, request, *args, **kwargs):
        self._require_any_pm()
        serializer = ProjectWriteSerializer(data=request.data)
        validated = validated_dict(serializer)
        pm_ids = validated.pop("pm_ids", None)
        if pm_ids is None:
            pm_ids = [cast(Any, request.user).pk]
        try:
            with transaction.atomic():
                project = cast(Project, serializer.save(created_by=request.user))
                self._sync_pms(project, pm_ids, request.user)
                ActivityLog.record(
                    project=project,
                    actor=request.user,
                    action="project.create",
                    target=project,
                    after={"name": project.name, "pm_ids": pm_ids},
                )
        except IntegrityError as exc:
            raise ValidationError("Không thể tạo organization do xung đột dữ liệu.") from exc
        fresh = self._base_queryset().get(pk=project.pk)
        return Response(
            ProjectDetailSerializer(fresh, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        target = self.get_object()
        self._require_project_pm(target)
        serializer = ProjectWriteSerializer(target, data=request.data, partial=partial)
        pm_ids = validated_dict(serializer).pop("pm_ids", None)
        try:
            with transaction.atomic():
                project = Project.objects.select_for_update().filter(pk=target.pk).first()
                if project is None:
                    raise NotFound("Không tìm thấy organization.")
                self._require_project_pm(project)
                serializer.instance = project
                project = cast(Project, serializer.save())
                if pm_ids is not None:
                    self._sync_pms(project, pm_ids, request.user)
                ActivityLog.record(
                    project=project,
                    actor=request.user,
                    action="project.update",
                    target=project,
                    after={"name": project.name, **({"pm_ids": pm_ids} if pm_ids is not None else {})},
                )
        except IntegrityError as exc:
            raise ValidationError("Không thể cập nhật organization do xung đột dữ liệu.") from exc
        fresh = self._base_queryset().get(pk=project.pk)
        return Response(ProjectDetailSerializer(fresh, context=self.get_serializer_context()).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)


class ProjectSettingsView(ProjectScopedViewMixin, APIView):
    """GET/PATCH /api/projects/{id}/settings/ — cấu hình Rework, Sampling, ngưỡng KPI."""

    required_capabilities = {"get": Cap.VIEW_PROJECT, "patch": Cap.MANAGE_SETTINGS}

    def get(self, request, project_id):
        return Response(ProjectSettingsSerializer(self.project).data)

    def patch(self, request, project_id):
        with transaction.atomic():
            project = Project.objects.select_for_update().get(pk=self.project.pk)
            before = dict(ProjectSettingsSerializer(project).data)
            serializer = ProjectSettingsSerializer(project, data=request.data, partial=True)
            validated_dict(serializer)
            serializer.save()
            after = dict(serializer.data)
            changed = {k: v for k, v in after.items() if before.get(k) != v}
            if changed:
                ActivityLog.record(
                    project=project,
                    actor=request.user,
                    action="project.settings",
                    target=project,
                    before={k: before[k] for k in changed},
                    after=changed,
                )
        self._project = project
        return Response(after)


class ProjectMembersView(ProjectScopedViewMixin, APIView):
    """GET  /api/projects/{id}/members/ — người trong organization, vai trò, team, số job đang giữ.
    POST /api/projects/{id}/members/ — PM tạo tài khoản mới cho thành viên (hệ thống sinh mật khẩu tạm).
    """

    required_capabilities = {"post": Cap.MANAGE_TEAM, "*": Cap.VIEW_PROJECT}

    def get(self, request, project_id):
        project = self.project
        roles: dict[int, set[str]] = defaultdict(set)
        users: dict[int, User] = {}
        for a in RoleAssignment.objects.filter(project=project).select_related("user__cvat_account"):
            roles[a.user_id].add(a.role)
            users[a.user_id] = a.user
        teams = {
            m.user_id: {"id": m.team_id, "name": m.team.name}
            for m in TeamMember.objects.filter(team__project=project).select_related("team")
        }
        active = dict(
            project.jobs.filter(status__in=OPEN_STATUSES, annotator__isnull=False)
            .values_list("annotator")
            .annotate(n=Count("id"))
        )
        can_manage_team = self.has_cap(Cap.MANAGE_TEAM)
        data = [
            {
                "user": UserBriefSerializer(user).data,
                "roles": sorted(expand_roles(roles[uid])),
                "direct_roles": sorted(roles[uid]),
                "team": teams.get(uid),
                "active_jobs": active.get(uid, 0),
                "cvat_linked": hasattr(user, "cvat_account"),
                "cvat_username": user.cvat_account.cvat_username if hasattr(user, "cvat_account") else None,
                "has_initial_password": bool(user.initial_password_encrypted) if can_manage_team else False,
            }
            for uid, user in sorted(users.items(), key=lambda kv: kv[1].username)
        ]
        role = request.query_params.get("role")
        if role:
            data = [m for m in data if role in m["roles"]]
        return Response(data)

    def post(self, request, project_id):
        data = validated_dict(CreateMemberSerializer(data=request.data, context={"project": self.project}))
        explicit_username = (data.get("username") or "").strip()
        team_obj = data.get("team")
        with transaction.atomic():
            team = None
            if team_obj is not None:
                team = Team.objects.select_for_update().filter(pk=team_obj.pk, project=self.project).first()
                if team is None:
                    raise ValidationError({"team": "Team không thuộc organization này."})

            user: User | None = None
            password = ""
            if explicit_username:
                user_candidate = User(
                    username=explicit_username,
                    first_name=data["full_name"],
                    email=data.get("email", ""),
                )
                password = credentials.set_initial_password(user_candidate)
                try:
                    with transaction.atomic():
                        user_candidate.save()
                    user = user_candidate
                except IntegrityError as exc:
                    raise ValidationError({"username": "Tên tài khoản đã tồn tại."}) from exc
            else:
                for _ in range(10):
                    candidate = credentials.unique_username(data["full_name"], User)
                    user_try = User(
                        username=candidate,
                        first_name=data["full_name"],
                        email=data.get("email", ""),
                    )
                    password_try = credentials.set_initial_password(user_try)
                    try:
                        with transaction.atomic():
                            user_try.save()
                        user = user_try
                        password = password_try
                        break
                    except IntegrityError:
                        continue
                if user is None:
                    raise ValidationError(
                        {"username": "Không thể tạo tên tài khoản duy nhất, vui lòng nhập thủ công."}
                    )

            try:
                with transaction.atomic():
                    RoleAssignment.objects.bulk_create([
                        RoleAssignment(user=user, role=role, project=self.project, granted_by=request.user)
                        for role in data["roles"]
                    ])
                    if team is not None:
                        TeamMember.objects.create(team=team, user=user)
            except IntegrityError as exc:
                raise ValidationError("Dữ liệu thành viên xung đột với bản ghi hiện có.") from exc

            ActivityLog.record(
                project=self.project,
                actor=request.user,
                action="member.create",
                target=user,
                after={"roles": data["roles"], "team": team.name if team else None},
            )
        response = Response(
            {
                "user": UserBriefSerializer(user).data,
                "username": user.username,
                "password": password,
                "roles": sorted(expand_roles(data["roles"])),
                "team": {"id": team.id, "name": team.name} if team else None,
            },
            status=status.HTTP_201_CREATED,
        )
        response["Cache-Control"] = "no-store"
        return response


def _roles_payload(user_id: int, direct: set[str]) -> dict[str, Any]:
    return {"user": user_id, "roles": sorted(expand_roles(direct)), "direct_roles": sorted(direct)}


def _parse_user_pk(user_id: Any) -> int:
    try:
        return parse_int_param(user_id, "user_id")
    except ValidationError as exc:
        raise NotFound("Người này không thuộc organization.") from exc


class ProjectMemberRolesView(ProjectScopedViewMixin, APIView):
    """POST /api/projects/{id}/members/{user_id}/roles/ {"role": "qc1"} — gán thêm vai trò cho thành viên."""

    required_capabilities = {"*": Cap.MANAGE_TEAM}

    def post(self, request, project_id, user_id):
        project = self.project
        parsed_user_id = _parse_user_pk(user_id)
        try:
            with transaction.atomic():
                user = User.objects.select_for_update().filter(pk=parsed_user_id).first()
                if user is None:
                    raise NotFound("Người này không thuộc organization.")
                current = set(
                    RoleAssignment.objects.filter(project=project, user=user).values_list("role", flat=True)
                )
                if not current:
                    raise NotFound("Người này không thuộc organization.")
                role = validated_dict(AddMemberRoleSerializer(data=request.data))["role"]
                if role in expand_roles(current):
                    raise ValidationError({"role": "Người này đã có vai trò này."})
                RoleAssignment.objects.create(project=project, user=user, role=role, granted_by=request.user)
                ActivityLog.record(
                    project=project,
                    actor=request.user,
                    action="member.add_role",
                    target=user,
                    after={"role": role},
                )
        except IntegrityError as exc:
            raise ValidationError({"role": "Người này đã có vai trò này."}) from exc
        return Response(_roles_payload(parsed_user_id, current | {role}), status=status.HTTP_201_CREATED)


def _role_removal_blocker(project, user, role):
    """Lý do KHÔNG được gỡ vai trò (None = gỡ được) — tránh để job / audit mồ côi."""
    if role == Role.QC1 and Job.objects.filter(
        project=project, qc1_reviewer=user, status__in=STAGE_STATUSES["qc1"]
    ).exists():
        return "Đang giữ job ở bước QC1 — giao lại các job đó trước."
    if role == Role.ANNOTATOR and Job.objects.filter(
        project=project, annotator=user, status__in=STAGE_STATUSES["annotation"]
    ).exists():
        return "Đang giữ job đang annotate / rework — giao lại các job đó trước."
    if role == Role.QC2 and AuditSample.objects.filter(
        audit__project=project,
        audit__status=Audit.Status.IN_PROGRESS,
        auditor=user,
        result=AuditSample.Result.PENDING,
    ).exists():
        return "Đang được phân audit mẫu QC2 chưa xong — phân lại mẫu trước."
    return None


class ProjectMemberRoleDetailView(ProjectScopedViewMixin, APIView):
    """DELETE /api/projects/{id}/members/{user_id}/roles/{role}/ — gỡ một vai trò của thành viên."""

    required_capabilities = {"*": Cap.MANAGE_TEAM}

    def delete(self, request, project_id, user_id, role):
        project = self.project
        parsed_user_id = _parse_user_pk(user_id)
        with transaction.atomic():
            user = User.objects.select_for_update().filter(pk=parsed_user_id).first()
            if user is None:
                raise NotFound("Người này không thuộc organization.")
            assignments = RoleAssignment.objects.filter(project=project, user=user)
            current = set(assignments.values_list("role", flat=True))
            if not current:
                raise NotFound("Người này không thuộc organization.")
            if role not in GRANTABLE_ROLES:
                raise ValidationError(
                    "Không gỡ được vai trò này (PM lấy từ Owner / Maintainer của CVAT organization)."
                )
            if role not in current:
                if role in expand_roles(current):
                    raise ValidationError("Vai trò này đi kèm vai trò PM — không gỡ riêng được.")
                raise ValidationError("Người này không có vai trò này.")
            if current == {role}:
                raise ValidationError("Phải còn ít nhất một vai trò. Gán vai trò khác trước khi gỡ vai trò này.")
            reason = _role_removal_blocker(project, user, role)
            if reason:
                raise ValidationError(reason)
            deleted, _ = assignments.filter(role=role).delete()
            if deleted == 0:
                raise ValidationError("Người này không có vai trò này.")
            user.token_version += 1
            user.save(update_fields=["token_version"])
            ActivityLog.record(
                project=project,
                actor=request.user,
                action="member.remove_role",
                target=user,
                before={"role": role},
            )
        return Response(_roles_payload(parsed_user_id, current - {role}))


def _project_member(project, user_id):
    parsed_user_id = _parse_user_pk(user_id)
    user = User.objects.filter(pk=parsed_user_id, role_assignments__project=project).distinct().first()
    if user is None:
        raise NotFound("Người này không thuộc organization.")
    return user


def _ensure_credential_target_manageable(actor, project, target):
    if actor.is_superuser:
        return
    if target.is_superuser or target.is_staff:
        raise ValidationError("Không thao tác mật khẩu của tài khoản quản trị hệ thống.")
    if target.role_assignments.filter(role=Role.PROJECT_MANAGER).exists():
        raise ValidationError("Không thao tác mật khẩu của Project Manager.")
    if target.role_assignments.exclude(project=project).exists():
        raise ValidationError("Thành viên thuộc nhiều organization — liên hệ quản trị viên hệ thống.")


class MemberCredentialView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/members/{user_id}/credential/ — PM xem tài khoản + mật khẩu tạm của thành viên."""

    required_capabilities = {"*": Cap.MANAGE_TEAM}

    def get(self, request, project_id, user_id):
        user = _project_member(self.project, user_id)
        _ensure_credential_target_manageable(request.user, self.project, user)
        encrypted = user.initial_password_encrypted
        password = credentials.decrypt(encrypted) if encrypted else None
        state = "initial" if password else ("unreadable" if encrypted else "changed")
        if password:
            ActivityLog.record(project=self.project, actor=request.user, action="member.view_password", target=user)
        response = Response({"username": user.username, "password": password, "status": state})
        response["Cache-Control"] = "no-store"
        return response


class MemberResetPasswordView(ProjectScopedViewMixin, APIView):
    """POST /api/projects/{id}/members/{user_id}/reset-password/ — cấp lại mật khẩu tạm."""

    required_capabilities = {"*": Cap.MANAGE_TEAM}

    def post(self, request, project_id, user_id):
        parsed_user_id = _parse_user_pk(user_id)
        with transaction.atomic():
            user = User.objects.select_for_update().filter(pk=parsed_user_id).first()
            if user is None or not RoleAssignment.objects.filter(project=self.project, user=user).exists():
                raise NotFound("Người này không thuộc organization.")
            if user.pk == request.user.pk:
                raise ValidationError("Tự đổi mật khẩu của mình ở menu tài khoản.")
            _ensure_credential_target_manageable(request.user, self.project, user)
            password = credentials.set_initial_password(user)
            user.token_version += 1
            user.save(update_fields=["password", "initial_password_encrypted", "token_version"])
            ActivityLog.record(project=self.project, actor=request.user, action="member.reset_password", target=user)
        response = Response({"username": user.username, "password": password, "status": "initial"})
        response["Cache-Control"] = "no-store"
        return response


class PermissionMatrixView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/permission-matrix/ — ma trận quyền đang áp dụng (chỉ đọc)."""

    required_capabilities = {"*": Cap.VIEW_PROJECT}

    def get(self, request, project_id):
        self.get_project()
        return Response({
            "capabilities": {cap: sorted(roles) for cap, roles in CAPABILITY_ROLES.items()},
            "implied_roles": {Role.PROJECT_MANAGER: [Role.QC2]},
        })


def _set_status(obj, new_status, *, project, actor, action, note=""):
    before = obj.status
    if before == DataStatus.DELIVERED:
        raise ValidationError("Đã bàn giao, không thể thay đổi trạng thái.")
    if before == new_status:
        raise ValidationError(f"Đối tượng đã ở trạng thái {new_status}.")
    obj.status = new_status
    obj.save(update_fields=["status"])
    ActivityLog.record(
        project=project,
        actor=actor,
        action=action,
        target=obj,
        before={"status": before},
        after={"status": new_status},
        note=note,
    )


class DatasetViewSet(
    ProjectScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """"Project" (CVAT project) của organization. Không tạo / xoá trên VanoHub: tạo trên CVAT rồi đồng bộ về."""

    serializer_class = DatasetSerializer
    required_capabilities = {"list": Cap.VIEW_JOBS, "retrieve": Cap.VIEW_JOBS, "*": Cap.MANAGE_DATA}

    def _base_queryset(self):
        return Dataset.objects.filter(project=self.project).annotate(
            task_count=Count("batches", distinct=True),
            job_count=Count("jobs", distinct=True),
            done_count=Count(
                "jobs",
                filter=Q(jobs__status__in=[JobStatus.APPROVED, JobStatus.DELIVERED]),
                distinct=True,
            ),
        )

    def get_queryset(self) -> Any:
        queryset = self._base_queryset()
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(name__icontains=search)
        return queryset

    def get_object(self):
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        try:
            parse_int_param(self.kwargs.get(lookup_url_kwarg), "pk")
        except ValidationError as exc:
            raise NotFound("Không tìm thấy project trong organization.") from exc
        return super().get_object()

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        fresh = self._base_queryset().get(pk=instance.pk)
        return Response(self.get_serializer(fresh).data)

    def perform_update(self, serializer):
        instance = cast(Dataset, serializer.instance)
        with transaction.atomic():
            locked = (
                Dataset.objects.select_for_update(of=("self",))
                .filter(pk=instance.pk, project=self.project)
                .first()
            )
            if locked is None:
                raise NotFound("Không tìm thấy project trong organization.")
            if locked.status != DataStatus.ACTIVE:
                raise ValidationError("Project đã khoá hoặc đã bàn giao, không thể chỉnh sửa.")
            before_desc = locked.description
            serializer.instance = locked
            dataset = cast(Dataset, serializer.save())
            if dataset.description != before_desc:
                ActivityLog.record(
                    project=self.project,
                    actor=self.request.user,
                    action="dataset.update",
                    target=dataset,
                    before={"description": before_desc},
                    after={"description": dataset.description},
                )

    @action(detail=True)
    def labels(self, request, project_id, pk=None):
        """Bộ nhãn của CVAT project (đặt trên CVAT) — chỉ đọc."""
        dataset = self.get_object()
        if not dataset.cvat_project_id:
            return Response({"labels": [], "detail": "Project này không gắn CVAT."})
        try:
            return Response({"labels": dataset_labels(dataset)})
        except CvatError as exc:
            return Response({"labels": [], "detail": str(exc)})

    def _set_dataset_status(self, request, pk, new_status, action_name):
        try:
            dataset_pk = parse_int_param(pk, "pk")
        except ValidationError as exc:
            raise NotFound("Không tìm thấy project trong organization.") from exc
        with transaction.atomic():
            dataset = (
                Dataset.objects.select_for_update(of=("self",))
                .filter(pk=dataset_pk, project=self.project)
                .first()
            )
            if dataset is None:
                raise NotFound("Không tìm thấy project trong organization.")
            _set_status(dataset, new_status, project=self.project, actor=request.user, action=action_name)
        fresh = self._base_queryset().get(pk=dataset.pk)
        return Response(self.get_serializer(fresh).data)

    @action(detail=True, methods=["post"])
    def lock(self, request, project_id, pk=None):
        return self._set_dataset_status(request, pk, DataStatus.LOCKED, "dataset.lock")

    @action(detail=True, methods=["post"])
    def unlock(self, request, project_id, pk=None):
        return self._set_dataset_status(request, pk, DataStatus.ACTIVE, "dataset.unlock")


class ProjectCvatSyncView(ProjectScopedViewMixin, APIView):
    """POST /api/projects/{id}/cvat-sync/ {"count_objects": bool} — kéo project / task / job của organization từ CVAT."""

    required_capabilities = {"*": Cap.MANAGE_DATA}

    def post(self, request, project_id):
        count_objects = validated_dict(SyncCvatSerializer(data=request.data))["count_objects"]
        try:
            result = sync_organization(self.project, actor=request.user, count_objects=count_objects)
        except CvatError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(result)


class BatchViewSet(
    ProjectScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """"Task" (CVAT task). Không tạo trên VanoHub — đồng bộ từ CVAT. PM đặt deadline, team, khoá/mở, xác nhận QC2."""

    serializer_class = BatchSerializer
    required_capabilities = {
        "list": Cap.VIEW_PROJECT,
        "retrieve": Cap.VIEW_JOBS,
        "confirm_qc2": Cap.MANAGE_DATA,
        "*": Cap.MANAGE_DATA,
    }

    def _base_queryset(self):
        done = [JobStatus.APPROVED, JobStatus.DELIVERED]
        return (
            Batch.objects.filter(project=self.project)
            .select_related("team", "dataset", "qc2_confirmed_by")
            .annotate(
                job_count=Count("jobs", distinct=True),
                done_count=Count("jobs", filter=Q(jobs__status__in=done), distinct=True),
                qc1_passed_count=Count("jobs", filter=Q(jobs__status=JobStatus.QC1_PASSED), distinct=True),
                blocking_qc2_count=Count("jobs", filter=Q(jobs__status__in=BLOCKING_QC2_STATUSES), distinct=True),
                pending_qc2_count=Count("jobs", filter=Q(jobs__status=JobStatus.PENDING_QC2), distinct=True),
                escalated_count=Count("jobs", filter=Q(jobs__is_escalated=True), distinct=True),
                locked_jobs=Count("jobs", filter=Q(jobs__is_locked=True), distinct=True),
                pending_qc2_samples=Count(
                    "audits__samples",
                    filter=Q(audits__samples__result=AuditSample.Result.PENDING),
                    distinct=True,
                ),
            )
            .order_by("dataset__name", "name")
        )

    def get_queryset(self) -> Any:
        queryset = self._base_queryset()
        params = self.request.query_params
        if params.get("dataset"):
            queryset = queryset.filter(dataset_id=parse_int_param(params["dataset"], "dataset"))
        if params.get("status"):
            queryset = queryset.filter(status=params["status"])
        if params.get("search"):
            queryset = queryset.filter(name__icontains=params["search"])
        return queryset

    def get_object(self):
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        try:
            parse_int_param(self.kwargs.get(lookup_url_kwarg), "pk")
        except ValidationError as exc:
            raise NotFound("Không tìm thấy task trong organization.") from exc
        return super().get_object()

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        if self.project.issue_gate_enabled:
            context["blocked_batch_ids"] = acceptance_blocking_batch_ids(self.project)
        return context

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        fresh = self._base_queryset().get(pk=instance.pk)
        return Response(self.get_serializer(fresh).data)

    def perform_update(self, serializer):
        instance = cast(Batch, serializer.instance)
        try:
            with transaction.atomic():
                dataset_id = (
                    Batch.objects.filter(pk=instance.pk, project=self.project)
                    .values_list("dataset_id", flat=True)
                    .first()
                )
                if dataset_id is None:
                    raise NotFound("Không tìm thấy task trong organization.")
                locked_dataset = (
                    Dataset.objects.select_for_update(of=("self",))
                    .filter(pk=dataset_id, project=self.project)
                    .first()
                )
                locked_batch = (
                    Batch.objects.select_for_update(of=("self",))
                    .select_related("team", "dataset", "qc2_confirmed_by")
                    .filter(pk=instance.pk, project=self.project)
                    .first()
                )
                if locked_batch is None or locked_dataset is None or locked_batch.dataset_id != locked_dataset.id:
                    raise NotFound("Không tìm thấy task trong organization.")
                if locked_batch.status != DataStatus.ACTIVE:
                    raise ValidationError("Task đã khoá hoặc đã bàn giao, không thể chỉnh sửa.")
                if locked_dataset.status != DataStatus.ACTIVE:
                    raise ValidationError("Project của task đã khoá hoặc đã bàn giao, không thể chỉnh sửa.")
                before_deadline = locked_batch.deadline
                before_team = locked_batch.team
                serializer.instance = locked_batch
                batch = cast(Batch, serializer.save())
                if batch.deadline != before_deadline:
                    # Deadline đặt theo task → khoá Batch → Job theo thứ tự id trước khi cập nhật.
                    target_jobs = list(
                        Job.objects.select_for_update(of=("self",))
                        .filter(batch=batch)
                        .exclude(status__in=[JobStatus.APPROVED, JobStatus.DELIVERED])
                        .order_by("id")
                    )
                    if target_jobs:
                        Job.objects.filter(pk__in=[j.pk for j in target_jobs]).update(deadline=batch.deadline)
                if batch.team_id != (before_team and before_team.id):
                    ActivityLog.record(
                        project=self.project,
                        actor=self.request.user,
                        action="batch.assign_team",
                        target=batch,
                        before={"team": before_team and before_team.name},
                        after={"team": batch.team and batch.team.name},
                    )
                if batch.deadline != before_deadline:
                    ActivityLog.record(
                        project=self.project,
                        actor=self.request.user,
                        action="batch.deadline",
                        target=batch,
                        before={"deadline": format_rfc3339_utc(before_deadline)},
                        after={"deadline": format_rfc3339_utc(batch.deadline)},
                    )
        except IntegrityError as exc:
            raise ValidationError("Không thể cập nhật task do dữ liệu tham chiếu không hợp lệ.") from exc

    def _set_batch_status(self, request, pk, new_status, action_name):
        note = validated_dict(BatchNoteSerializer(data=request.data))["note"].strip()
        try:
            batch_pk = parse_int_param(pk, "pk")
        except ValidationError as exc:
            raise NotFound("Không tìm thấy task trong organization.") from exc
        with transaction.atomic():
            batch = (
                Batch.objects.select_for_update(of=("self",))
                .filter(pk=batch_pk, project=self.project)
                .first()
            )
            if batch is None:
                raise NotFound("Không tìm thấy task trong organization.")
            _set_status(batch, new_status, project=self.project, actor=request.user, action=action_name, note=note)
        fresh = self._base_queryset().get(pk=batch.pk)
        return Response(self.get_serializer(fresh).data)

    @action(detail=True, methods=["post"])
    def lock(self, request, project_id, pk=None):
        return self._set_batch_status(request, pk, DataStatus.LOCKED, "batch.lock")

    @action(detail=True, methods=["post"])
    def unlock(self, request, project_id, pk=None):
        return self._set_batch_status(request, pk, DataStatus.ACTIVE, "batch.unlock")

    @action(detail=True, methods=["post"], url_path="confirm-qc2")
    def confirm_qc2(self, request, project_id, pk=None):
        """PM xác nhận chuyển cả task sang QC2 khi 100% job trong task đã đạt QC1 (không có job khoá)."""
        note = validated_dict(BatchNoteSerializer(data=request.data))["note"].strip()
        try:
            batch_pk = parse_int_param(pk, "pk")
        except ValidationError as exc:
            raise NotFound("Không tìm thấy task trong organization.") from exc

        with transaction.atomic():
            dataset_id = (
                Batch.objects.filter(pk=batch_pk, project=self.project)
                .values_list("dataset_id", flat=True)
                .first()
            )
            if dataset_id is None:
                raise NotFound("Không tìm thấy task trong organization.")
            dataset = (
                Dataset.objects.select_for_update(of=("self",))
                .filter(pk=dataset_id, project=self.project)
                .first()
            )
            batch = (
                Batch.objects.select_for_update(of=("self",))
                .filter(pk=batch_pk, project=self.project)
                .first()
            )
            if batch is None or dataset is None or batch.dataset_id != dataset.id:
                raise NotFound("Không tìm thấy task trong organization.")
            if batch.status != DataStatus.ACTIVE:
                raise ValidationError("Task đã khoá hoặc đã bàn giao.")
            if dataset.status != DataStatus.ACTIVE:
                raise ValidationError("Project của task đã khoá hoặc đã bàn giao.")

            jobs = list(Job.objects.select_for_update(of=("self",)).filter(batch=batch).order_by("id"))
            if not jobs:
                raise ValidationError("Task chưa có job nào.")
            locked_count = sum(1 for j in jobs if j.is_locked)
            if locked_count > 0:
                raise ValidationError("Task còn job đang bị khoá — mở khoá trước khi xác nhận chuyển QC2.")
            blocking_count = sum(1 for j in jobs if j.status not in QC2_NON_BLOCKING_STATUSES)
            if blocking_count > 0:
                raise ValidationError(
                    f"Còn {blocking_count} job chưa đạt QC1 — chỉ xác nhận chuyển QC2 khi 100% job trong task đã đạt QC1."
                )
            ready_jobs = [j for j in jobs if j.status == JobStatus.QC1_PASSED]
            if not ready_jobs:
                raise ValidationError("Task không có job nào ở trạng thái Đạt QC1 cần chuyển sang QC2.")
            issue_blockers = acceptance_blocking_issues_for_jobs(self.project, jobs)
            if issue_blockers:
                ids_str = ", ".join(f"#{b.cvat_issue_id}" for b in issue_blockers[:5])
                raise ValidationError(
                    f"Không thể xác nhận chuyển QC2 vì còn {len(issue_blockers)} issue chưa xử lý ({ids_str})."
                )

            now = timezone.now()
            transitioned_ids = [j.pk for j in ready_jobs]
            Job.objects.filter(pk__in=transitioned_ids).update(status=JobStatus.PENDING_QC2, updated_at=now)
            for job in ready_jobs:
                job.status = JobStatus.PENDING_QC2
                job.updated_at = now
            batch.qc2_confirmed_by = request.user
            batch.qc2_confirmed_at = now
            batch.save(update_fields=["qc2_confirmed_by", "qc2_confirmed_at"])

            for job in ready_jobs:
                ensure_qc2_sample(job)

            UserNotification.objects.filter(
                project=self.project,
                category=UserNotification.Category.REVIEW_NEEDED,
                is_pinned_pending=True,
            ).filter(
                Q(job_id__in=transitioned_ids)
                | Q(batch=batch)
                | Q(
                    job__isnull=True,
                    batch__isnull=True,
                    title__in=[
                        f"Task {batch.name} sẵn sàng xác nhận chuyển QC2",
                        f"Batch {batch.name} sẵn sàng xác nhận chuyển QC2",
                    ],
                )
            ).update(is_pinned_pending=False)

            ActivityLog.record(
                project=self.project,
                actor=request.user,
                action="batch.confirm_qc2",
                target=batch,
                after={"moved_to_pending_qc2": len(transitioned_ids)},
                note=note,
            )
            recipients = project_users_with_roles(self.project, Role.PROJECT_MANAGER, Role.QC2)
            notify_review_needed(
                self.project,
                recipients,
                title=f"Task {batch.name} đã được xác nhận chuyển QC2",
                body=f"{len(transitioned_ids)} job đã sẵn sàng kiểm tra QC2.",
                action_url=f"/projects/{self.project.id}/qc2/work",
                batch=batch,
                actor=request.user,
            )
            schedule_assignee_push(transitioned_ids)

        fresh = self._base_queryset().get(pk=batch.pk)
        return Response(self.get_serializer(fresh).data)


class DeliveryViewSet(
    ProjectScopedViewMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Bàn giao theo task: mọi job của task ở trạng thái Đã duyệt, không bị khoá, không còn lượt QC2 chờ kiểm."""

    serializer_class = DeliverySerializer
    required_capabilities = {
        "list": [Cap.MANAGE_DELIVERY, Cap.VIEW_DASHBOARD],
        "candidates": [Cap.MANAGE_DELIVERY, Cap.VIEW_DASHBOARD],
        "*": Cap.MANAGE_DELIVERY,
    }

    def get_queryset(self) -> Any:
        return Delivery.objects.filter(project=self.project).select_related("batch__dataset", "delivered_by")

    @action(detail=False)
    def candidates(self, request, project_id):
        """Các task chưa bàn giao + mức độ sẵn sàng + trạng thái hạn bàn giao (DH07)."""
        now = timezone.now()
        soon_cutoff = now + timedelta(hours=24)
        batches = list(
            Batch.objects.filter(project=self.project)
            .exclude(status=DataStatus.DELIVERED)
            .select_related("dataset")
            .annotate(
                job_count=Count("jobs", distinct=True),
                approved_count=Count("jobs", filter=Q(jobs__status=JobStatus.APPROVED), distinct=True),
                locked_jobs=Count("jobs", filter=Q(jobs__is_locked=True), distinct=True),
                pending_qc2_samples=Count(
                    "audits__samples",
                    filter=Q(audits__samples__result=AuditSample.Result.PENDING),
                    distinct=True,
                ),
                in_progress_audits=Count(
                    "audits",
                    filter=Q(audits__status=Audit.Status.IN_PROGRESS),
                    distinct=True,
                ),
            )
        )
        blocking_by_batch: dict[int, int] = defaultdict(int)
        if self.project.issue_gate_enabled and batches:
            batch_ids = [b.id for b in batches]
            batch_jobs = list(Job.objects.filter(project=self.project, batch_id__in=batch_ids).only("id", "batch_id"))
            job_to_batch = {j.pk: j.batch_id for j in batch_jobs}
            for ji in acceptance_blocking_issues_for_jobs(self.project, batch_jobs):
                b_id = job_to_batch.get(ji.job_id)
                if b_id is not None:
                    blocking_by_batch[b_id] += 1
        rows: list[dict[str, Any]] = []
        for b in batches:
            if not b.deadline:
                due_state = "none"
            elif b.deadline < now:
                due_state = "overdue"
            elif b.deadline <= soon_cutoff:
                due_state = "soon"
            else:
                due_state = "normal"
            blocking_issues = blocking_by_batch.get(b.id, 0)
            rows.append({
                "batch": b.id,
                "batch_name": b.name,
                "dataset_name": b.dataset.name,
                "status": b.status,
                "dataset_status": b.dataset.status,
                "deadline": format_rfc3339_utc(b.deadline),
                "is_overdue": bool(b.deadline and b.deadline < now),
                "due_state": due_state,
                "job_count": b.job_count,
                "approved_count": b.approved_count,
                "locked_jobs": b.locked_jobs,
                "pending_qc2_samples": b.pending_qc2_samples,
                "in_progress_audits": getattr(b, "in_progress_audits", 0),
                # Giữ khoá open_audits theo số mẫu QC2 chờ kiểm để tương thích UI DeliveryPage.tsx hiện tại.
                "open_audits": b.pending_qc2_samples,
                "blocking_issues": blocking_issues,
                "ready": (
                    b.status == DataStatus.ACTIVE
                    and b.dataset.status == DataStatus.ACTIVE
                    and b.job_count > 0
                    and b.approved_count == b.job_count
                    and b.pending_qc2_samples == 0
                    and b.locked_jobs == 0
                    and blocking_issues == 0
                ),
            })
        return Response(rows)

    def perform_create(self, serializer):
        batch_id = validated_dict(serializer)["batch"].pk
        try:
            with transaction.atomic():
                dataset_id = (
                    Batch.objects.filter(pk=batch_id, project=self.project)
                    .values_list("dataset_id", flat=True)
                    .first()
                )
                if dataset_id is None:
                    raise ValidationError({"batch": "Task không thuộc organization này."})
                dataset = (
                    Dataset.objects.select_for_update(of=("self",))
                    .filter(pk=dataset_id, project=self.project)
                    .first()
                )
                batch = (
                    Batch.objects.select_for_update(of=("self",))
                    .filter(pk=batch_id, project=self.project)
                    .first()
                )
                if batch is None or dataset is None or batch.dataset_id != dataset.id:
                    raise ValidationError("Task vừa thay đổi project, vui lòng thử lại.")
                if batch.status == DataStatus.DELIVERED or Delivery.objects.filter(batch=batch).exists():
                    raise ValidationError("Task đã được bàn giao.")
                if batch.status != DataStatus.ACTIVE or dataset.status != DataStatus.ACTIVE:
                    raise ValidationError("Task hoặc Project đang bị khoá — mở khoá trước khi ghi nhận bàn giao.")
                jobs = list(Job.objects.select_for_update(of=("self",)).filter(batch=batch).order_by("id"))
                job_count = len(jobs)
                approved_count = sum(1 for j in jobs if j.status == JobStatus.APPROVED)
                locked_jobs = sum(1 for j in jobs if j.is_locked)
                if job_count == 0 or approved_count != job_count:
                    raise ValidationError("Chỉ bàn giao được khi mọi job trong task đã ở trạng thái Đã duyệt.")
                if locked_jobs > 0:
                    raise ValidationError("Task còn job đang bị khoá — mở khoá trước khi bàn giao.")
                if AuditSample.objects.filter(audit__batch=batch, result=AuditSample.Result.PENDING).exists():
                    raise ValidationError("Task còn lượt QC2 chưa kiểm.")
                issue_blockers = acceptance_blocking_issues_for_jobs(self.project, jobs)
                if issue_blockers:
                    ids_str = ", ".join(f"#{b.cvat_issue_id}" for b in issue_blockers[:5])
                    raise ValidationError(
                        f"Không thể bàn giao vì còn {len(issue_blockers)} issue chưa xử lý ({ids_str})."
                    )
                delivery = cast(
                    Delivery,
                    serializer.save(project=self.project, batch=batch, delivered_by=self.request.user),
                )
                Job.objects.filter(pk__in=[j.pk for j in jobs]).update(status=JobStatus.DELIVERED)
                batch.status = DataStatus.DELIVERED
                batch.save(update_fields=["status"])
                # Bàn giao xong → chốt các đợt QC2 đang mở của task và gỡ ghim thông báo chờ duyệt của task.
                batch.audits.filter(status=Audit.Status.IN_PROGRESS).update(
                    status=Audit.Status.COMPLETED, completed_at=timezone.now()
                )
                UserNotification.objects.filter(
                    project=self.project,
                    category=UserNotification.Category.REVIEW_NEEDED,
                    is_pinned_pending=True,
                ).filter(
                    Q(batch=batch)
                    | Q(job__batch=batch)
                    | Q(
                        job__isnull=True,
                        batch__isnull=True,
                        title__in=[
                            f"Task {batch.name} đã được xác nhận chuyển QC2",
                            f"Task {batch.name} sẵn sàng xác nhận chuyển QC2",
                            f"Batch {batch.name} sẵn sàng xác nhận chuyển QC2",
                        ],
                    )
                ).update(is_pinned_pending=False)
                ActivityLog.record(
                    project=self.project,
                    actor=self.request.user,
                    action="batch.deliver",
                    target=batch,
                    after={
                        "delivery": delivery.id,
                        "jobs": job_count,
                        "recipient": delivery.recipient,
                        "output_path": delivery.output_path,
                    },
                )
        except IntegrityError as exc:
            raise ValidationError("Task đã được bàn giao.") from exc

    def perform_update(self, serializer):
        allowed = {"recipient", "output_path", "note", "client_feedback"}
        validated = validated_dict(serializer)
        extra = set(validated) - allowed
        if extra:
            raise ValidationError(f"Không được sửa: {', '.join(sorted(extra))}")
        instance = cast(Delivery, serializer.instance)
        with transaction.atomic():
            locked = (
                Delivery.objects.select_for_update(of=("self",))
                .select_related("batch__dataset", "delivered_by")
                .filter(pk=instance.pk, project=self.project)
                .first()
            )
            if locked is None:
                raise NotFound("Không tìm thấy bản ghi bàn giao.")
            before = {field: getattr(locked, field) for field in validated}
            serializer.instance = locked
            delivery = cast(Delivery, serializer.save())
            after = {field: getattr(delivery, field) for field in validated}
            changed = {k: v for k, v in after.items() if before.get(k) != v}
            if changed:
                ActivityLog.record(
                    project=self.project,
                    actor=self.request.user,
                    action="delivery.update",
                    target=delivery,
                    before={k: before[k] for k in changed},
                    after=changed,
                )


class ActivityLogViewSet(ProjectScopedViewMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = ActivityLogSerializer
    pagination_class = StandardPagination
    required_capabilities = {"*": Cap.VIEW_ACTIVITY}

    def get_queryset(self) -> Any:
        queryset = ActivityLog.objects.filter(project=self.project).select_related("actor")
        params = self.request.query_params
        if params.get("actor"):
            queryset = queryset.filter(actor_id=parse_int_param(params["actor"], "actor"))
        if params.get("action"):
            queryset = queryset.filter(action__startswith=params["action"])
        date_from, date_to = parse_query_date_range(
            params,
            from_key="date_from",
            to_key="date_to",
            allow_datetime=True,
        )
        if date_from is not None:
            queryset = queryset.filter(created_at__gte=date_from)
        if date_to is not None:
            queryset = queryset.filter(created_at__lte=date_to)
        return queryset


def _visible_announcements(project, user, *, can_see_all: bool) -> list[Announcement]:
    """Lọc thông báo organization phù hợp vai trò & team của user trước khi phân trang/cắt giới hạn."""
    queryset = Announcement.objects.filter(project=project).select_related("sender", "target_team")
    if can_see_all:
        return list(queryset)
    my_roles = {
        r.value
        for r in expand_roles(
            RoleAssignment.objects.filter(user=user, project=project).values_list("role", flat=True)
        )
    }
    my_team_ids = set(
        TeamMember.objects.filter(user=user, team__project=project).values_list("team_id", flat=True)
    )
    return [
        a
        for a in queryset
        if (not a.target_roles or set(a.target_roles) & my_roles)
        and (a.target_team_id is None or a.target_team_id in my_team_ids)
    ]


class AnnouncementViewSet(
    ProjectScopedViewMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """PM gửi thông báo; mọi người trong organization đọc thông báo dành cho vai trò/team của mình."""

    serializer_class = AnnouncementSerializer
    required_capabilities = {"list": Cap.VIEW_PROJECT, "*": Cap.SEND_ANNOUNCEMENT}

    def get_queryset(self) -> Any:
        return _visible_announcements(
            self.project, self.request.user, can_see_all=self.has_cap(Cap.SEND_ANNOUNCEMENT)
        )

    def perform_create(self, serializer):
        announcement = serializer.save(project=self.project, sender=self.request.user)
        ActivityLog.record(
            project=self.project,
            actor=self.request.user,
            action="announcement.send",
            target=announcement,
            after={"roles": announcement.target_roles},
        )


class GuidelineViewSet(
    ProjectScopedViewMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Mỗi lần lưu tạo phiên bản mới; không sửa phiên bản cũ → giữ được lịch sử."""

    serializer_class = GuidelineSerializer
    required_capabilities = {"list": Cap.VIEW_GUIDELINES, "*": Cap.MANAGE_QUALITY_CATALOG}

    def get_queryset(self) -> Any:
        return Guideline.objects.filter(project=self.project).select_related("created_by")

    def perform_create(self, serializer):
        with transaction.atomic():
            # Khoá dòng Project để hai người lưu cùng lúc không tạo trùng số phiên bản.
            Project.objects.select_for_update().get(pk=self.project.pk)
            last = Guideline.objects.filter(project=self.project).aggregate(v=Max("version"))["v"]
            guideline = serializer.save(project=self.project, created_by=self.request.user, version=(last or 0) + 1)
        ActivityLog.record(
            project=self.project,
            actor=self.request.user,
            action="guideline.publish",
            target=guideline,
            after={"version": guideline.version},
        )


class ProjectNotificationsView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/notifications/ — Thông báo hợp nhất (sự kiện cá nhân, cảnh báo hạn, thông báo chung)."""

    required_capabilities = {"*": Cap.VIEW_PROJECT}

    def get(self, request, project_id):
        user = request.user
        now = timezone.now()
        items: list[dict[str, Any]] = []
        can_annotate = self.has_cap(Cap.ANNOTATE_JOBS)

        # 1. Thông báo cá nhân đã lưu trong DB
        persisted = list(
            UserNotification.objects.filter(recipient=user, project=self.project).select_related("job")[:40]
        )
        notified_deadline_job_ids = {
            n.job_id for n in persisted if n.category == UserNotification.Category.DEADLINE and n.job_id
        }
        for n in persisted:
            if n.action_url:
                action_url = n.action_url
            elif n.job_id:
                action_url = (
                    f"/projects/{self.project.pk}/annotator/jobs/{n.job_id}"
                    if can_annotate
                    else f"/projects/{self.project.pk}/jobs"
                )
            else:
                action_url = f"/projects/{self.project.pk}"
            items.append({
                "id": f"sys-{n.id}",
                "notification_id": n.id,
                "source": "system",
                "category": n.category,
                "title": n.title,
                "body": n.body,
                "job_id": n.job_id,
                "action_url": action_url,
                "is_read": n.is_read,
                "is_pinned_pending": n.is_pinned_pending,
                "created_at": format_rfc3339_utc(n.created_at),
            })

        # 2. Cảnh báo job sắp / quá hạn (<= 24h) theo phạm vi từng vai trò
        if user.notify_deadline:
            cutoff = now + timedelta(hours=24)
            seen_deadline_jobs: set[int] = set(notified_deadline_job_ids)

            def _append_deadline(job: Job, action_url: str, suffix: str) -> None:
                if job.id in seen_deadline_jobs or job.deadline is None:
                    return
                seen_deadline_jobs.add(job.id)
                overdue = job.deadline < now
                hours = max(1, round(abs((job.deadline - now).total_seconds()) / 3600))
                items.append({
                    "id": f"due-{self.project.id}-{job.id}",
                    "notification_id": None,
                    "source": "deadline",
                    "category": UserNotification.Category.DEADLINE,
                    "title": f"{job.name} đã quá hạn" if overdue else f"{job.name} sắp đến hạn",
                    "body": (
                        f"Quá hạn {hours} giờ — {suffix}" if overdue else f"Còn {hours} giờ — {suffix}"
                    ),
                    "job_id": job.id,
                    "action_url": action_url,
                    "is_read": False,
                    "is_pinned_pending": True,
                    "created_at": format_rfc3339_utc(job.updated_at),
                })

            if can_annotate:
                for j in Job.objects.filter(
                    project=self.project,
                    annotator=user,
                    status__in=ACTIVE_ANNOTATOR_STATUSES,
                    deadline__isnull=False,
                    deadline__lte=cutoff,
                ).order_by("deadline", "id")[:8]:
                    _append_deadline(j, f"/projects/{self.project.id}/annotator/jobs/{j.id}", "ưu tiên xử lý ngay.")

            if self.has_cap(Cap.PERFORM_QC1):
                for j in Job.objects.filter(
                    project=self.project,
                    qc1_reviewer=user,
                    status__in=[JobStatus.PENDING_QC1, JobStatus.QC1_REVIEWING],
                    deadline__isnull=False,
                    deadline__lte=cutoff,
                ).order_by("deadline", "id")[:8]:
                    _append_deadline(j, f"/projects/{self.project.id}/qc1/work", "cần kiểm tra QC1 trước hạn.")

            if self.has_cap(Cap.PERFORM_AUDIT):
                qc2_job_ids = list(
                    AuditSample.objects.filter(
                        audit__project=self.project,
                        audit__status=Audit.Status.IN_PROGRESS,
                        auditor=user,
                        result=AuditSample.Result.PENDING,
                    ).values_list("job_id", flat=True)
                )
                if qc2_job_ids:
                    for j in Job.objects.filter(
                        pk__in=qc2_job_ids, deadline__isnull=False, deadline__lte=cutoff
                    ).order_by("deadline", "id")[:8]:
                        _append_deadline(j, f"/projects/{self.project.id}/qc2/work", "mẫu QC2 sắp/quá hạn.")

            if self.has_cap(Cap.MANAGE_JOBS):
                for j in Job.objects.filter(
                    project=self.project,
                    status__in=OPEN_STATUSES,
                    deadline__isnull=False,
                    deadline__lte=cutoff,
                ).order_by("deadline", "id")[:6]:
                    url = (
                        f"/projects/{self.project.id}/jobs?"
                        f"{'overdue=1' if (j.deadline is not None and j.deadline < now) else 'due_soon=1'}"
                    )
                    _append_deadline(j, url, "job sắp/quá hạn.")

        # 3. Thông báo organization (Announcement) phù hợp vai trò / team — lọc trước rồi mới cắt 20 mục
        visible_announcements = _visible_announcements(
            self.project, user, can_see_all=self.has_cap(Cap.SEND_ANNOUNCEMENT)
        )[:20]
        read_ann_ids = set(
            AnnouncementRead.objects.filter(
                user=user,
                announcement_id__in=[a.id for a in visible_announcements],
            ).values_list("announcement_id", flat=True)
        )
        for a in visible_announcements:
            sender_name = a.sender.get_full_name() or a.sender.username if a.sender else "Hệ thống"
            items.append({
                "id": f"ann-{a.id}",
                "notification_id": None,
                "source": "announcement",
                "category": UserNotification.Category.ANNOUNCEMENT,
                "title": f"Thông báo từ {sender_name}",
                "body": a.content,
                "job_id": None,
                "action_url": f"/projects/{self.project.id}/announcements",
                "is_read": a.sender_id == user.id or a.id in read_ann_ids,
                "is_pinned_pending": False,
                "created_at": format_rfc3339_utc(a.created_at),
            })

        items.sort(key=lambda x: x["created_at"] or "", reverse=True)
        items.sort(key=lambda x: 0 if (not x["is_read"] and x["is_pinned_pending"]) else 1)

        unread_count = sum(1 for item in items if not item["is_read"])
        return Response({
            "all_count": len(items),
            "unread_count": unread_count,
            "items": items[:50],
        })


class MarkNotificationsReadView(ProjectScopedViewMixin, APIView):
    """POST /api/projects/{id}/notifications/mark-read/ — Đánh dấu đã đọc (một hoặc tất cả)."""

    required_capabilities = {"*": Cap.VIEW_PROJECT}

    def post(self, request, project_id):
        notif_id = request.data.get("notification_id")
        if notif_id is not None:
            if isinstance(notif_id, str):
                raw = notif_id.strip()
                if raw.startswith("ann-"):
                    ann_pk = parse_int_param(raw[4:], "notification_id")
                    if not Announcement.objects.filter(pk=ann_pk, project=self.project).exists():
                        return Response({"updated": 0})
                    _, created = AnnouncementRead.objects.get_or_create(
                        announcement_id=ann_pk, user=request.user
                    )
                    return Response({"updated": 1 if created else 0})
                sys_pk = parse_int_param(raw[4:] if raw.startswith("sys-") else raw, "notification_id")
            else:
                sys_pk = parse_int_param(notif_id, "notification_id")

            updated = UserNotification.objects.filter(
                pk=sys_pk,
                recipient=request.user,
                project=self.project,
                is_read=False,
            ).update(is_read=True)
            return Response({"updated": updated})

        # Đánh dấu đọc tất cả: giữ nguyên thông báo đang ghim chờ xử lý (is_pinned_pending=True)
        updated = UserNotification.objects.filter(
            recipient=request.user,
            project=self.project,
            is_read=False,
            is_pinned_pending=False,
        ).update(is_read=True)

        visible_announcements = _visible_announcements(
            self.project, request.user, can_see_all=self.has_cap(Cap.SEND_ANNOUNCEMENT)
        )
        candidate_ann_ids = [a.id for a in visible_announcements if a.sender_id != request.user.id]
        if candidate_ann_ids:
            already_read = set(
                AnnouncementRead.objects.filter(
                    user=request.user, announcement_id__in=candidate_ann_ids
                ).values_list("announcement_id", flat=True)
            )
            to_create = [
                AnnouncementRead(announcement_id=aid, user=request.user)
                for aid in candidate_ann_ids
                if aid not in already_read
            ]
            if to_create:
                AnnouncementRead.objects.bulk_create(to_create, ignore_conflicts=True)
                updated += len(to_create)
        return Response({"updated": updated})
