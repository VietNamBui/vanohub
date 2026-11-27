from collections import defaultdict
from datetime import timedelta

from accounts import credentials
from accounts.datetime_utils import parse_int_param
from accounts.models import Role, RoleAssignment, User, expand_roles
from accounts.permissions import CAPABILITY_ROLES, Cap, ProjectScopedViewMixin
from accounts.serializers import UserBriefSerializer
from cvat_integration.client import CvatError
from cvat_integration.sync import dataset_labels, sync_organization
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Prefetch, Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from jobs.models import ACTIVE_ANNOTATOR_STATUSES, OPEN_STATUSES, STAGE_STATUSES, Job, JobStatus
from quality.models import AuditSample
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
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
from .serializers import (
    ActivityLogSerializer,
    AnnouncementSerializer,
    BatchSerializer,
    DatasetSerializer,
    DeliverySerializer,
    GuidelineSerializer,
    ProjectDetailSerializer,
    ProjectListSerializer,
    ProjectSettingsSerializer,
)


class StandardPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500


class ProjectViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/projects/ và /api/projects/{id}/ — chỉ organization mà user có vai trò."""

    def get_queryset(self):
        user = self.request.user
        queryset = Project.objects.filter(role_assignments__user=user).distinct()
        queryset = queryset.prefetch_related(
            Prefetch("role_assignments", queryset=RoleAssignment.objects.filter(user=user), to_attr="my_assignments")
        )
        if self.action == "retrieve":
            queryset = queryset.prefetch_related("role_assignments")
        return queryset

    def get_serializer_class(self):
        return ProjectDetailSerializer if self.action == "retrieve" else ProjectListSerializer


class ProjectSettingsView(ProjectScopedViewMixin, APIView):
    """GET/PATCH /api/projects/{id}/settings/ — cấu hình Rework, Sampling, ngưỡng KPI."""

    required_capabilities = {"get": Cap.VIEW_PROJECT, "patch": Cap.MANAGE_SETTINGS}

    def get(self, request, project_id):
        return Response(ProjectSettingsSerializer(self.project).data)

    def patch(self, request, project_id):
        before = ProjectSettingsSerializer(self.project).data
        serializer = ProjectSettingsSerializer(self.project, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        changed = {k: v for k, v in serializer.data.items() if before.get(k) != v}
        if changed:
            ActivityLog.record(project=self.project, actor=request.user, action="project.settings",
                               target=self.project, before={k: before[k] for k in changed}, after=changed)
        return Response(serializer.data)


class ProjectMembersView(ProjectScopedViewMixin, APIView):
    """GET  /api/projects/{id}/members/ — người trong dự án, vai trò, team, số job đang giữ.
    POST /api/projects/{id}/members/ — PM tạo tài khoản mới cho thành viên (hệ thống sinh mật khẩu tạm).
    """

    required_capabilities = {"post": Cap.MANAGE_TEAM, "*": Cap.VIEW_PROJECT}

    def get(self, request, project_id):
        project = self.project
        roles = defaultdict(set)
        users = {}
        for a in RoleAssignment.objects.filter(project=project).select_related("user__cvat_account"):
            roles[a.user_id].add(a.role)
            users[a.user_id] = a.user
        teams = {
            m.user_id: {"id": m.team_id, "name": m.team.name}
            for m in TeamMember.objects.filter(team__project=project).select_related("team")
        }
        active = dict(
            project.jobs.filter(status__in=OPEN_STATUSES, annotator__isnull=False)
            .values_list("annotator").annotate(n=Count("id"))
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
        serializer = CreateMemberSerializer(data=request.data, context={"project": self.project})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        team = data.get("team")
        with transaction.atomic():
            user = User(
                username=data.get("username") or credentials.unique_username(data["full_name"], User),
                first_name=data["full_name"],
                email=data.get("email", ""),
            )
            password = credentials.set_initial_password(user)
            user.save()
            RoleAssignment.objects.bulk_create([
                RoleAssignment(user=user, role=role, project=self.project, granted_by=request.user)
                for role in data["roles"]
            ])
            if team:
                TeamMember.objects.create(team=team, user=user)
            ActivityLog.record(project=self.project, actor=request.user, action="member.create", target=user,
                               after={"roles": data["roles"], "team": team.name if team else None})
        return Response({
            "user": UserBriefSerializer(user).data,
            "username": user.username,
            "password": password,
            "roles": sorted(expand_roles(data["roles"])),
            "team": {"id": team.id, "name": team.name} if team else None,
        }, status=status.HTTP_201_CREATED)


# PM gán / gỡ được các vai trò trong organization, trừ PM (PM lấy từ Owner / Maintainer của CVAT organization).
# Vai trò ngầm định (PM → QC2) đã có thì không gán lại.
GRANTABLE_ROLES = [Role.QC2, Role.QC1, Role.ANNOTATOR]


class ProjectMemberRolesView(ProjectScopedViewMixin, APIView):
    """POST /api/projects/{id}/members/{user_id}/roles/ {"role": "qc1"} — gán thêm vai trò cho thành viên."""

    required_capabilities = {"*": Cap.MANAGE_TEAM}

    def post(self, request, project_id, user_id):
        project = self.project
        role = request.data.get("role")
        try:
            with transaction.atomic():
                user = User.objects.select_for_update().filter(pk=user_id).first()
                if user is None:
                    raise NotFound("Người này không thuộc dự án.")
                current = set(
                    RoleAssignment.objects.filter(project=project, user=user).values_list("role", flat=True)
                )
                if not current:
                    raise NotFound("Người này không thuộc dự án.")
                if role not in GRANTABLE_ROLES:
                    raise ValidationError({"role": f"Không gán được vai trò này. Cho phép: {', '.join(GRANTABLE_ROLES)}."})
                if role in expand_roles(current):
                    raise ValidationError({"role": "Người này đã có vai trò này."})
                RoleAssignment.objects.create(project=project, user=user, role=role, granted_by=request.user)
                ActivityLog.record(project=project, actor=request.user, action="member.add_role", target=user,
                                   after={"role": role})
        except IntegrityError as exc:
            raise ValidationError({"role": "Người này đã có vai trò này."}) from exc
        return Response(_roles_payload(user_id, current | {role}), status=status.HTTP_201_CREATED)


def _roles_payload(user_id, direct):
    return {"user": user_id, "roles": sorted(expand_roles(direct)), "direct_roles": sorted(direct)}


def _role_removal_blocker(project, user, role):
    """Lý do KHÔNG được gỡ vai trò (None = gỡ được). ĐỀ XUẤT, chưa chốt — tránh để job / team mồ côi."""
    if role == Role.QC1 and Job.objects.filter(
            project=project, qc1_reviewer=user, status__in=STAGE_STATUSES["qc1"]).exists():
        return "Đang giữ job ở bước QC1 — giao lại các job đó trước."
    if role == Role.ANNOTATOR and Job.objects.filter(
            project=project, annotator=user, status__in=STAGE_STATUSES["annotation"]).exists():
        return "Đang giữ job đang annotate / rework — giao lại các job đó trước."
    if role == Role.QC2 and AuditSample.objects.filter(
            audit__project=project, audit__status="in_progress", auditor=user, result=AuditSample.Result.PENDING).exists():
        return "Đang được phân audit mẫu QC2 chưa xong — phân lại mẫu trước."
    return None


class ProjectMemberRoleDetailView(ProjectScopedViewMixin, APIView):
    """DELETE /api/projects/{id}/members/{user_id}/roles/{role}/ — gỡ một vai trò của thành viên.

    ĐỀ XUẤT (chưa chốt):
    - Chỉ gỡ được các vai trò PM được gán (QC2, QC1, Annotator); PM lấy từ CVAT organization.
    - Vai trò đi kèm (QC2 của PM) không gỡ riêng được.
    - Phải còn ít nhất một vai trò: gỡ hết = rời dự án, chưa có đặc tả.
    - Không gỡ khi người đó đang giữ việc của vai trò ấy (xem _role_removal_blocker).
    """

    required_capabilities = {"*": Cap.MANAGE_TEAM}

    def delete(self, request, project_id, user_id, role):
        project = self.project
        with transaction.atomic():
            user = User.objects.select_for_update().filter(pk=user_id).first()
            if user is None:
                raise NotFound("Người này không thuộc dự án.")
            assignments = RoleAssignment.objects.filter(project=project, user=user)
            current = set(assignments.values_list("role", flat=True))
            if not current:
                raise NotFound("Người này không thuộc dự án.")
            if role not in GRANTABLE_ROLES:
                raise ValidationError("Không gỡ được vai trò này (PM lấy từ Owner / Maintainer của CVAT organization).")
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
            ActivityLog.record(project=project, actor=request.user, action="member.remove_role", target=user,
                               before={"role": role})
        return Response(_roles_payload(user_id, current - {role}))


class CreateMemberSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150)
    username = serializers.RegexField(
        r"^[A-Za-z0-9_.-]{3,150}$", required=False, allow_blank=True,
        error_messages={"invalid": "Chỉ gồm chữ không dấu, số và . _ - (ít nhất 3 ký tự)."},
    )
    email = serializers.EmailField(required=False, allow_blank=True)
    roles = serializers.ListField(
        child=serializers.ChoiceField(choices=GRANTABLE_ROLES), allow_empty=False,
        error_messages={"empty": "Chọn ít nhất một vai trò."},
    )
    team = serializers.PrimaryKeyRelatedField(queryset=Team.objects.all(), required=False, allow_null=True)

    def validate_full_name(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("Nhập họ tên.")
        return value

    def validate_username(self, value):
        if value and User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("Tên tài khoản đã tồn tại.")
        return value

    def validate_roles(self, value):
        return sorted(set(value))

    def validate_team(self, team):
        if team and team.project_id != self.context["project"].id:
            raise serializers.ValidationError("Team không thuộc dự án này.")
        return team


def _project_member(project, user_id):
    user = User.objects.filter(pk=user_id, role_assignments__project=project).distinct().first()
    if user is None:
        raise NotFound("Người này không thuộc dự án.")
    return user


class MemberCredentialView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/members/{user_id}/credential/ — PM xem tài khoản + mật khẩu tạm của thành viên.

    status: "initial" (còn mật khẩu tạm) | "changed" (người dùng đã tự đổi / tài khoản tạo trước đó)
            | "unreadable" (không giải mã được, vd. đã đổi SECRET_KEY → cấp lại).
    Mỗi lần xem mật khẩu đều ghi lịch sử.
    """

    required_capabilities = {"*": Cap.MANAGE_TEAM}

    def get(self, request, project_id, user_id):
        user = _project_member(self.project, user_id)
        encrypted = user.initial_password_encrypted
        password = credentials.decrypt(encrypted) if encrypted else None
        state = "initial" if password else ("unreadable" if encrypted else "changed")
        if password:
            ActivityLog.record(project=self.project, actor=request.user, action="member.view_password", target=user)
        return Response({"username": user.username, "password": password, "status": state})


class MemberResetPasswordView(ProjectScopedViewMixin, APIView):
    """POST /api/projects/{id}/members/{user_id}/reset-password/ — cấp lại mật khẩu tạm.

    ĐỀ XUẤT: PM không cấp lại được cho PM khác (kể cả ở organization khác) và cho chính mình.
    """

    required_capabilities = {"*": Cap.MANAGE_TEAM}

    def post(self, request, project_id, user_id):
        user = _project_member(self.project, user_id)
        if user.pk == request.user.pk:
            raise ValidationError("Tự đổi mật khẩu của mình ở menu tài khoản.")
        if user.role_assignments.filter(role=Role.PROJECT_MANAGER).exists():
            raise ValidationError("Không cấp lại mật khẩu cho Project Manager.")
        password = credentials.set_initial_password(user)
        user.save(update_fields=["password", "initial_password_encrypted"])
        ActivityLog.record(project=self.project, actor=request.user, action="member.reset_password", target=user)
        return Response({"username": user.username, "password": password, "status": "initial"})


class PermissionMatrixView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/permission-matrix/ — ma trận quyền đang áp dụng (chỉ đọc)."""

    required_capabilities = {"*": Cap.VIEW_PROJECT}

    def get(self, request, project_id):
        self.get_project()
        return Response({
            "capabilities": {cap: sorted(roles) for cap, roles in CAPABILITY_ROLES.items()},
            "implied_roles": {Role.PROJECT_MANAGER: [Role.QC2]},
        })


def _set_status(obj, new_status, *, project, actor, action):
    before = obj.status
    if before == DataStatus.DELIVERED:
        raise ValidationError("Đã bàn giao, không thể thay đổi trạng thái.")
    if before == new_status:
        raise ValidationError(f"Đối tượng đã ở trạng thái {new_status}.")
    obj.status = new_status
    obj.save(update_fields=["status"])
    ActivityLog.record(project=project, actor=actor, action=action, target=obj,
                       before={"status": before}, after={"status": new_status})


class DatasetViewSet(ProjectScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                     mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """"Project" (CVAT project) của organization. Không tạo / xoá trên VanoHub: tạo trên CVAT rồi đồng bộ về."""

    serializer_class = DatasetSerializer
    required_capabilities = {"list": Cap.VIEW_JOBS, "retrieve": Cap.VIEW_JOBS, "*": Cap.MANAGE_DATA}

    def _base_queryset(self):
        return Dataset.objects.filter(project=self.project).annotate(
            task_count=Count("batches", distinct=True),
            job_count=Count("jobs", distinct=True),
            done_count=Count("jobs", filter=Q(jobs__status__in=[JobStatus.APPROVED, JobStatus.DELIVERED]), distinct=True),
        )

    def get_queryset(self):
        queryset = self._base_queryset()
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(name__icontains=search)
        return queryset

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

    @action(detail=True, methods=["post"])
    def lock(self, request, project_id, pk=None):
        dataset = self.get_object()
        _set_status(dataset, DataStatus.LOCKED, project=self.project, actor=request.user, action="dataset.lock")
        fresh = self._base_queryset().get(pk=dataset.pk)
        return Response(self.get_serializer(fresh).data)

    @action(detail=True, methods=["post"])
    def unlock(self, request, project_id, pk=None):
        dataset = self.get_object()
        _set_status(dataset, DataStatus.ACTIVE, project=self.project, actor=request.user, action="dataset.unlock")
        fresh = self._base_queryset().get(pk=dataset.pk)
        return Response(self.get_serializer(fresh).data)


class ProjectCvatSyncView(ProjectScopedViewMixin, APIView):
    """POST /api/projects/{id}/cvat-sync/ {"count_objects": bool} — kéo project / task / job của organization từ CVAT."""

    required_capabilities = {"*": Cap.MANAGE_DATA}

    def post(self, request, project_id):
        try:
            result = sync_organization(self.project, request.user,
                                       count_objects=bool(request.data.get("count_objects")))
        except CvatError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(result)


class BatchViewSet(ProjectScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                   mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """"Task" (CVAT task). Không tạo trên VanoHub — đồng bộ từ CVAT. PM đặt deadline, team phụ trách, khoá / mở khoá."""

    serializer_class = BatchSerializer
    required_capabilities = {"list": Cap.VIEW_PROJECT, "retrieve": Cap.VIEW_JOBS, "*": Cap.MANAGE_DATA}

    def _base_queryset(self):
        done = [JobStatus.APPROVED, JobStatus.DELIVERED]
        return (
            Batch.objects.filter(project=self.project)
            .select_related("team", "dataset")
            .annotate(
                job_count=Count("jobs"),
                done_count=Count("jobs", filter=Q(jobs__status__in=done)),
                pending_qc2_count=Count("jobs", filter=Q(jobs__status=JobStatus.PENDING_QC2)),
                escalated_count=Count("jobs", filter=Q(jobs__is_escalated=True)),
            )
            .order_by("dataset__name", "name")
        )

    def get_queryset(self):
        queryset = self._base_queryset()
        params = self.request.query_params
        if params.get("dataset"):
            queryset = queryset.filter(dataset_id=parse_int_param(params["dataset"], "dataset"))
        if params.get("status"):
            queryset = queryset.filter(status=params["status"])
        if params.get("search"):
            queryset = queryset.filter(name__icontains=params["search"])
        return queryset

    def perform_update(self, serializer):
        before_deadline = serializer.instance.deadline
        before_team = serializer.instance.team
        batch = serializer.save()
        if batch.deadline != before_deadline:
            # Deadline đặt theo task → job của task nhận theo (job đã xong thì không đổi).
            batch.jobs.exclude(status__in=[JobStatus.APPROVED, JobStatus.DELIVERED]).update(deadline=batch.deadline)
        if batch.team_id != (before_team and before_team.id):
            ActivityLog.record(project=self.project, actor=self.request.user, action="batch.assign_team", target=batch,
                               before={"team": before_team and before_team.name},
                               after={"team": batch.team and batch.team.name})
        if batch.deadline != before_deadline:
            ActivityLog.record(project=self.project, actor=self.request.user, action="batch.deadline", target=batch,
                               before={"deadline": before_deadline and before_deadline.isoformat()},
                               after={"deadline": batch.deadline and batch.deadline.isoformat()})

    @action(detail=True, methods=["post"])
    def lock(self, request, project_id, pk=None):
        batch = self.get_object()
        _set_status(batch, DataStatus.LOCKED, project=self.project, actor=request.user, action="batch.lock")
        fresh = self._base_queryset().get(pk=batch.pk)
        return Response(self.get_serializer(fresh).data)

    @action(detail=True, methods=["post"])
    def unlock(self, request, project_id, pk=None):
        batch = self.get_object()
        _set_status(batch, DataStatus.ACTIVE, project=self.project, actor=request.user, action="batch.unlock")
        fresh = self._base_queryset().get(pk=batch.pk)
        return Response(self.get_serializer(fresh).data)


class DeliveryViewSet(ProjectScopedViewMixin, mixins.ListModelMixin, mixins.CreateModelMixin,
                      mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Bàn giao theo batch. Điều kiện (ĐỀ XUẤT, L4 bỏ qua): mọi job của batch đã ở trạng thái Đã duyệt."""

    serializer_class = DeliverySerializer
    required_capabilities = {"list": [Cap.MANAGE_DELIVERY, Cap.VIEW_DASHBOARD], "*": Cap.MANAGE_DELIVERY}

    def get_queryset(self):
        return Delivery.objects.filter(project=self.project).select_related("batch__dataset", "delivered_by")

    @action(detail=False)
    def candidates(self, request, project_id):
        """Các task chưa bàn giao + mức độ sẵn sàng."""
        batches = (
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
            )
        )
        return Response([
            {
                "batch": b.id,
                "batch_name": b.name,
                "dataset_name": b.dataset.name,
                "job_count": b.job_count,
                "approved_count": b.approved_count,
                "open_audits": b.pending_qc2_samples,
                "ready": (
                    b.job_count > 0
                    and b.approved_count == b.job_count
                    and b.pending_qc2_samples == 0
                    and b.locked_jobs == 0
                ),
            }
            for b in batches
        ])

    def perform_create(self, serializer):
        batch_id = serializer.validated_data["batch"].pk
        try:
            with transaction.atomic():
                batch = (
                    Batch.objects.select_for_update(of=("self",))
                    .select_related("dataset")
                    .get(pk=batch_id, project=self.project)
                )
                if batch.status == DataStatus.DELIVERED or Delivery.objects.filter(batch=batch).exists():
                    raise ValidationError("Batch đã được bàn giao.")
                jobs = list(Job.objects.select_for_update(of=("self",)).filter(batch=batch).order_by("id"))
                job_count = len(jobs)
                approved_count = sum(1 for j in jobs if j.status == JobStatus.APPROVED)
                locked_jobs = sum(1 for j in jobs if j.is_locked)
                if job_count == 0 or approved_count != job_count:
                    raise ValidationError("Chỉ bàn giao được khi mọi job trong batch đã ở trạng thái Đã duyệt.")
                if locked_jobs > 0:
                    raise ValidationError("Task còn job đang bị khoá — mở khoá trước khi bàn giao.")
                if AuditSample.objects.filter(audit__batch=batch, result=AuditSample.Result.PENDING).exists():
                    raise ValidationError("Task còn lượt QC2 chưa kiểm.")
                delivery = serializer.save(project=self.project, batch=batch, delivered_by=self.request.user)
                Job.objects.filter(pk__in=[j.pk for j in jobs]).update(status=JobStatus.DELIVERED)
                batch.status = DataStatus.DELIVERED
                batch.save(update_fields=["status"])
                # Bàn giao xong → chốt các đợt QC2 của task.
                batch.audits.filter(status="in_progress").update(status="completed", completed_at=timezone.now())
                ActivityLog.record(
                    project=self.project,
                    actor=self.request.user,
                    action="batch.deliver",
                    target=batch,
                    after={"delivery": delivery.id, "jobs": job_count},
                )
        except IntegrityError as exc:
            raise ValidationError("Batch đã được bàn giao.") from exc

    def perform_update(self, serializer):
        # Sau khi bàn giao chỉ cho sửa ghi chú và phản hồi khách hàng.
        allowed = {"note", "client_feedback"}
        extra = set(serializer.validated_data) - allowed
        if extra:
            raise ValidationError(f"Không được sửa: {', '.join(sorted(extra))}")
        serializer.save()


class ActivityLogViewSet(ProjectScopedViewMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = ActivityLogSerializer
    pagination_class = StandardPagination
    required_capabilities = {"*": Cap.VIEW_ACTIVITY}

    def get_queryset(self):
        queryset = ActivityLog.objects.filter(project=self.project).select_related("actor")
        params = self.request.query_params
        if params.get("actor"):
            queryset = queryset.filter(actor_id=parse_int_param(params["actor"], "actor"))
        if params.get("action"):
            queryset = queryset.filter(action__startswith=params["action"])
        if params.get("date_from") and parse_date(params["date_from"]):
            queryset = queryset.filter(created_at__date__gte=parse_date(params["date_from"]))
        if params.get("date_to") and parse_date(params["date_to"]):
            queryset = queryset.filter(created_at__date__lte=parse_date(params["date_to"]))
        return queryset


def _visible_announcements(project, user, *, can_see_all):
    """Lọc thông báo dự án phù hợp vai trò & team của user trước khi phân trang/cắt giới hạn."""
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
        a for a in queryset
        if (not a.target_roles or set(a.target_roles) & my_roles)
        and (a.target_team_id is None or a.target_team_id in my_team_ids)
    ]


class AnnouncementViewSet(ProjectScopedViewMixin, mixins.ListModelMixin, mixins.CreateModelMixin,
                          viewsets.GenericViewSet):
    """PM gửi thông báo; mọi người trong dự án đọc thông báo dành cho vai trò/team của mình."""

    serializer_class = AnnouncementSerializer
    required_capabilities = {"list": Cap.VIEW_PROJECT, "*": Cap.SEND_ANNOUNCEMENT}

    def get_queryset(self):
        return _visible_announcements(
            self.project, self.request.user, can_see_all=self.has_cap(Cap.SEND_ANNOUNCEMENT)
        )

    def perform_create(self, serializer):
        announcement = serializer.save(project=self.project, sender=self.request.user)
        ActivityLog.record(project=self.project, actor=self.request.user, action="announcement.send",
                           target=announcement, after={"roles": announcement.target_roles})


class GuidelineViewSet(ProjectScopedViewMixin, mixins.ListModelMixin, mixins.CreateModelMixin,
                       viewsets.GenericViewSet):
    """Mỗi lần lưu tạo phiên bản mới; không sửa phiên bản cũ → giữ được lịch sử."""

    serializer_class = GuidelineSerializer
    required_capabilities = {"list": Cap.VIEW_GUIDELINES, "*": Cap.MANAGE_QUALITY_CATALOG}

    def get_queryset(self):
        return Guideline.objects.filter(project=self.project).select_related("created_by")

    def perform_create(self, serializer):
        with transaction.atomic():
            # Khoá dòng Project để hai người lưu cùng lúc không tạo trùng số phiên bản.
            Project.objects.select_for_update().get(pk=self.project.pk)
            last = Guideline.objects.filter(project=self.project).aggregate(v=Max("version"))["v"]
            guideline = serializer.save(project=self.project, created_by=self.request.user, version=(last or 0) + 1)
        ActivityLog.record(project=self.project, actor=self.request.user, action="guideline.publish",
                           target=guideline, after={"version": guideline.version})


class ProjectNotificationsView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/notifications/ — Thông báo hợp nhất (sự kiện cá nhân, cảnh báo hạn, thông báo dự án)."""

    required_capabilities = {"*": Cap.VIEW_PROJECT}

    def get(self, request, project_id):
        user = request.user
        now = timezone.now()
        items = []
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
                "created_at": n.created_at.isoformat(),
            })

        # 2. Cảnh báo job sắp / quá hạn đang giữ
        if user.notify_deadline and can_annotate:
            urgent_jobs = (
                Job.objects.filter(
                    project=self.project,
                    annotator=user,
                    status__in=ACTIVE_ANNOTATOR_STATUSES,
                    deadline__isnull=False,
                    deadline__lte=now + timedelta(hours=24),
                )
                .exclude(pk__in=notified_deadline_job_ids)
                .order_by("deadline", "id")[:10]
            )
            for j in urgent_jobs:
                overdue = j.deadline < now
                hours = max(1, round(abs((j.deadline - now).total_seconds()) / 3600))
                items.append({
                    "id": f"due-{j.id}",
                    "notification_id": None,
                    "source": "deadline",
                    "category": UserNotification.Category.DEADLINE,
                    "title": f"{j.name} đã quá hạn" if overdue else f"{j.name} sắp đến hạn",
                    "body": (
                        f"Quá hạn {hours} giờ — ưu tiên xử lý ngay."
                        if overdue
                        else f"Còn {hours} giờ — ưu tiên làm trước."
                    ),
                    "job_id": j.id,
                    "action_url": f"/projects/{self.project.id}/annotator/jobs/{j.id}",
                    "is_read": False,
                    "is_pinned_pending": True,
                    "created_at": j.updated_at.isoformat(),
                })

        # 3. Thông báo dự án (Announcement) phù hợp vai trò / team — lọc trước rồi mới cắt 20 mục
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
                "created_at": a.created_at.isoformat(),
            })

        items.sort(key=lambda x: x["created_at"], reverse=True)
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
