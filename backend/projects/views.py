from collections import defaultdict

from django.db import transaction
from django.db.models import Count, Max, Prefetch, Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import credentials
from accounts.models import Role, RoleAssignment, User, expand_roles
from accounts.permissions import CAPABILITY_ROLES, Cap, ProjectScopedViewMixin
from accounts.serializers import UserBriefSerializer
from cvat_integration.client import CvatError
from cvat_integration.sync import dataset_labels, sync_organization
from jobs.models import OPEN_STATUSES, STAGE_STATUSES, Job, JobStatus
from quality.models import AuditSample
from teams.models import Team, TeamMember

from .models import ActivityLog, Announcement, Batch, DataStatus, Dataset, Delivery, Guideline, Project
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
        data = [
            {
                "user": UserBriefSerializer(user).data,
                "roles": sorted(expand_roles(roles[uid])),
                "direct_roles": sorted(roles[uid]),
                "team": teams.get(uid),
                "active_jobs": active.get(uid, 0),
                "cvat_linked": hasattr(user, "cvat_account"),
                "cvat_username": user.cvat_account.cvat_username if hasattr(user, "cvat_account") else None,
                "has_initial_password": bool(user.initial_password_encrypted),
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
        current = set(RoleAssignment.objects.filter(project=project, user_id=user_id).values_list("role", flat=True))
        if not current:
            raise NotFound("Người này không thuộc dự án.")
        role = request.data.get("role")
        if role not in GRANTABLE_ROLES:
            raise ValidationError({"role": f"Không gán được vai trò này. Cho phép: {', '.join(GRANTABLE_ROLES)}."})
        if role in expand_roles(current):
            raise ValidationError({"role": "Người này đã có vai trò này."})
        assignment = RoleAssignment.objects.create(project=project, user_id=user_id, role=role)
        ActivityLog.record(project=project, actor=request.user, action="member.add_role", target=assignment.user,
                           after={"role": role})
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
        assignments = RoleAssignment.objects.filter(project=project, user_id=user_id).select_related("user")
        current = {a.role for a in assignments}
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
        user = assignments[0].user
        reason = _role_removal_blocker(project, user, role)
        if reason:
            raise ValidationError(reason)
        assignments.filter(role=role).delete()
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

    def get_queryset(self):
        queryset = Dataset.objects.filter(project=self.project).annotate(
            task_count=Count("batches", distinct=True),
            job_count=Count("jobs", distinct=True),
            done_count=Count("jobs", filter=Q(jobs__status__in=[JobStatus.APPROVED, JobStatus.DELIVERED]), distinct=True),
        )
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
        return Response(self.get_serializer(self.get_object()).data)

    @action(detail=True, methods=["post"])
    def unlock(self, request, project_id, pk=None):
        dataset = self.get_object()
        _set_status(dataset, DataStatus.ACTIVE, project=self.project, actor=request.user, action="dataset.unlock")
        return Response(self.get_serializer(self.get_object()).data)


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
    required_capabilities = {"list": [Cap.VIEW_JOBS, Cap.MANAGE_AUDITS], "retrieve": Cap.VIEW_JOBS, "*": Cap.MANAGE_DATA}

    def get_queryset(self):
        done = [JobStatus.APPROVED, JobStatus.DELIVERED]
        queryset = (
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
        params = self.request.query_params
        if params.get("dataset"):
            queryset = queryset.filter(dataset_id=params["dataset"])
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
        _set_status(self.get_object(), DataStatus.LOCKED, project=self.project, actor=request.user, action="batch.lock")
        return Response(self.get_serializer(self.get_object()).data)

    @action(detail=True, methods=["post"])
    def unlock(self, request, project_id, pk=None):
        _set_status(self.get_object(), DataStatus.ACTIVE, project=self.project, actor=request.user, action="batch.unlock")
        return Response(self.get_serializer(self.get_object()).data)


class DeliveryViewSet(ProjectScopedViewMixin, mixins.ListModelMixin, mixins.CreateModelMixin,
                      mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Bàn giao theo batch. Điều kiện (ĐỀ XUẤT, L4 bỏ qua): mọi job của batch đã ở trạng thái Đã duyệt."""

    serializer_class = DeliverySerializer
    required_capabilities = {"list": [Cap.MANAGE_DELIVERY, Cap.VIEW_DASHBOARD], "*": Cap.MANAGE_DELIVERY}

    def get_queryset(self):
        return Delivery.objects.filter(project=self.project).select_related("batch", "delivered_by")

    @action(detail=False)
    def candidates(self, request, project_id):
        """Các batch chưa bàn giao + mức độ sẵn sàng."""
        batches = (
            Batch.objects.filter(project=self.project)
            .exclude(status=DataStatus.DELIVERED)
            .annotate(
                job_count=Count("jobs"),
                approved_count=Count("jobs", filter=Q(jobs__status=JobStatus.APPROVED)),
                open_audits=Count("audits", filter=Q(audits__status="in_progress"), distinct=True),
            )
        )
        return Response([
            {
                "batch": b.id, "batch_name": b.name,
                "job_count": b.job_count, "approved_count": b.approved_count, "open_audits": b.open_audits,
                "ready": b.job_count > 0 and b.approved_count == b.job_count and b.open_audits == 0,
            }
            for b in batches
        ])

    def perform_create(self, serializer):
        batch = serializer.validated_data["batch"]
        jobs = batch.jobs.all()
        if batch.status == DataStatus.DELIVERED:
            raise ValidationError("Batch đã được bàn giao.")
        if not jobs.exists() or jobs.exclude(status=JobStatus.APPROVED).exists():
            raise ValidationError("Chỉ bàn giao được khi mọi job trong batch đã ở trạng thái Đã duyệt.")
        if AuditSample.objects.filter(audit__batch=batch, result=AuditSample.Result.PENDING).exists():
            raise ValidationError("Task còn lượt QC2 chưa kiểm.")
        with transaction.atomic():
            delivery = serializer.save(project=self.project, delivered_by=self.request.user)
            jobs.update(status=JobStatus.DELIVERED)
            batch.status = DataStatus.DELIVERED
            batch.save(update_fields=["status"])
            # Bàn giao xong → chốt các đợt QC2 của task.
            batch.audits.filter(status="in_progress").update(status="completed", completed_at=timezone.now())
            ActivityLog.record(project=self.project, actor=self.request.user, action="batch.deliver", target=batch,
                               after={"delivery": delivery.id, "jobs": jobs.count()})

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
            queryset = queryset.filter(actor_id=params["actor"])
        if params.get("action"):
            queryset = queryset.filter(action__startswith=params["action"])
        if params.get("date_from") and parse_date(params["date_from"]):
            queryset = queryset.filter(created_at__date__gte=parse_date(params["date_from"]))
        if params.get("date_to") and parse_date(params["date_to"]):
            queryset = queryset.filter(created_at__date__lte=parse_date(params["date_to"]))
        return queryset


class AnnouncementViewSet(ProjectScopedViewMixin, mixins.ListModelMixin, mixins.CreateModelMixin,
                          viewsets.GenericViewSet):
    """PM gửi thông báo; mọi người trong dự án đọc thông báo dành cho vai trò/team của mình."""

    serializer_class = AnnouncementSerializer
    required_capabilities = {"list": Cap.VIEW_PROJECT, "*": Cap.SEND_ANNOUNCEMENT}

    def get_queryset(self):
        queryset = Announcement.objects.filter(project=self.project).select_related("sender", "target_team")
        if self.has_cap(Cap.SEND_ANNOUNCEMENT):
            return queryset
        user = self.request.user
        my_roles = expand_roles(
            RoleAssignment.objects.filter(user=user, project=self.project).values_list("role", flat=True)
        )
        my_team_ids = set(TeamMember.objects.filter(user=user, team__project=self.project).values_list("team_id", flat=True))
        return [
            a for a in queryset
            if (not a.target_roles or set(a.target_roles) & my_roles)
            and (a.target_team_id is None or a.target_team_id in my_team_ids)
        ]

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
