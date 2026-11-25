from collections import defaultdict

from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Max, Prefetch, Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Role, RoleAssignment, expand_roles
from accounts.permissions import CAPABILITY_ROLES, DIRECTOR_CAPABILITIES, Cap, ProjectScopedViewMixin
from accounts.serializers import UserBriefSerializer
from cvat_integration.client import CvatError
from cvat_integration.sync import import_task_jobs, sync_batch
from jobs.models import ACTIVE_ANNOTATOR_STATUSES, OPEN_STATUSES, Job, JobStatus
from teams.models import TeamMember

from .models import (
    ActivityLog,
    Announcement,
    Batch,
    DataStatus,
    Dataset,
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
    """GET /api/projects/ và /api/projects/{id}/ — chỉ dự án trong phạm vi (Director thấy tất cả)."""

    def get_queryset(self):
        user = self.request.user
        queryset = Project.objects.all()
        if not user.is_director():
            queryset = queryset.filter(role_assignments__user=user).distinct()
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
    """GET /api/projects/{id}/members/ — người trong dự án, vai trò, team, số job đang giữ."""

    def get(self, request, project_id):
        project = self.project
        roles = defaultdict(set)
        users = {}
        for a in RoleAssignment.objects.filter(project=project).select_related("user"):
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
                "team": teams.get(uid),
                "active_jobs": active.get(uid, 0),
            }
            for uid, user in sorted(users.items(), key=lambda kv: kv[1].username)
        ]
        role = request.query_params.get("role")
        if role:
            data = [m for m in data if role in m["roles"]]
        return Response(data)


# ĐỀ XUẤT (chưa chốt): PM gán thêm được các vai trò trong dự án, trừ PM và Director
# (hai vai trò này do Director quản lý). Vai trò ngầm định (PM → QC2, TL → QC1) đã có thì không gán lại.
GRANTABLE_ROLES = [Role.QC2, Role.TEAM_LEADER, Role.QC1, Role.ANNOTATOR]


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
        return Response({"user": user_id, "roles": sorted(expand_roles(current | {role}))},
                        status=status.HTTP_201_CREATED)


class PermissionMatrixView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/permission-matrix/ — ma trận quyền đang áp dụng (chỉ đọc)."""

    def get(self, request, project_id):
        self.get_project()
        return Response({
            "capabilities": {cap: sorted(roles) for cap, roles in CAPABILITY_ROLES.items()},
            "director_capabilities": sorted(DIRECTOR_CAPABILITIES),
            "implied_roles": {Role.PROJECT_MANAGER: [Role.QC2], Role.TEAM_LEADER: [Role.QC1]},
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
                     mixins.CreateModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Dataset của dự án. Không có xoá: chưa có đặc tả xoá an toàn."""

    serializer_class = DatasetSerializer
    required_capabilities = {"list": Cap.VIEW_JOBS, "retrieve": Cap.VIEW_JOBS, "*": Cap.MANAGE_DATA}

    def get_queryset(self):
        queryset = Dataset.objects.filter(project=self.project).annotate(
            batch_count=Count("batches", distinct=True),
            job_count=Count("batches__jobs", distinct=True),
            done_count=Count("batches__jobs", filter=Q(batches__jobs__status__in=[JobStatus.APPROVED, JobStatus.DELIVERED]), distinct=True),
        )
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(name__icontains=search)
        return queryset

    def perform_create(self, serializer):
        dataset = serializer.save(project=self.project, created_by=self.request.user)
        ActivityLog.record(project=self.project, actor=self.request.user, action="dataset.create", target=dataset)

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


class BatchViewSet(ProjectScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                   mixins.CreateModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = BatchSerializer
    required_capabilities = {"list": [Cap.VIEW_JOBS, Cap.MANAGE_AUDITS], "retrieve": Cap.VIEW_JOBS, "*": Cap.MANAGE_DATA}

    def get_queryset(self):
        done = [JobStatus.APPROVED, JobStatus.DELIVERED]
        queryset = (
            Batch.objects.filter(dataset__project=self.project)
            .select_related("dataset", "team")
            .annotate(
                job_count=Count("jobs"),
                done_count=Count("jobs", filter=Q(jobs__status__in=done)),
                pending_qc2_count=Count("jobs", filter=Q(jobs__status=JobStatus.PENDING_QC2)),
                escalated_count=Count("jobs", filter=Q(jobs__is_escalated=True)),
            )
        )
        params = self.request.query_params
        if params.get("dataset"):
            queryset = queryset.filter(dataset_id=params["dataset"])
        if params.get("status"):
            queryset = queryset.filter(status=params["status"])
        if params.get("search"):
            queryset = queryset.filter(name__icontains=params["search"])
        return queryset

    def perform_create(self, serializer):
        batch = serializer.save(created_by=self.request.user)
        ActivityLog.record(project=self.project, actor=self.request.user, action="batch.create", target=batch)

    def perform_update(self, serializer):
        before_deadline = serializer.instance.deadline
        before_team = serializer.instance.team
        batch = serializer.save()
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

    @action(detail=True, methods=["post"], url_path="import-cvat")
    def import_cvat(self, request, project_id, pk=None):
        """Nhập các job của một CVAT Task vào batch này."""
        batch = self.get_object()
        task_id = request.data.get("cvat_task_id")
        if not str(task_id or "").isdigit():
            raise ValidationError({"cvat_task_id": "Nhập ID task CVAT (số nguyên)."})
        if batch.cvat_task_id and batch.cvat_task_id != int(task_id):
            raise ValidationError({"cvat_task_id": f"Batch đã gắn với CVAT task {batch.cvat_task_id}."})
        try:
            result = import_task_jobs(batch, int(task_id), request.user)
        except CvatError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(result)

    @action(detail=True, methods=["post"], url_path="sync-cvat")
    def sync_cvat(self, request, project_id, pk=None):
        batch = self.get_object()
        if not batch.cvat_task_id:
            raise ValidationError("Batch chưa gắn với CVAT task.")
        try:
            result = sync_batch(batch, request.user, count_objects=bool(request.data.get("count_objects")))
        except CvatError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(result)


class DeliveryViewSet(ProjectScopedViewMixin, mixins.ListModelMixin, mixins.CreateModelMixin,
                      mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Bàn giao theo batch. Điều kiện (ĐỀ XUẤT, L4 bỏ qua): mọi job của batch đã ở trạng thái Đã duyệt."""

    serializer_class = DeliverySerializer
    required_capabilities = {"list": [Cap.MANAGE_DELIVERY, Cap.VIEW_DASHBOARD], "*": Cap.MANAGE_DELIVERY}

    def get_queryset(self):
        return Delivery.objects.filter(project=self.project).select_related("batch__dataset", "delivered_by")

    @action(detail=False)
    def candidates(self, request, project_id):
        """Các batch chưa bàn giao + mức độ sẵn sàng."""
        batches = (
            Batch.objects.filter(dataset__project=self.project)
            .exclude(status=DataStatus.DELIVERED)
            .select_related("dataset")
            .annotate(
                job_count=Count("jobs"),
                approved_count=Count("jobs", filter=Q(jobs__status=JobStatus.APPROVED)),
                open_audits=Count("audits", filter=Q(audits__status="in_progress"), distinct=True),
            )
        )
        return Response([
            {
                "batch": b.id, "batch_name": b.name, "dataset_name": b.dataset.name,
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
        if batch.audits.filter(status="in_progress").exists():
            raise ValidationError("Batch còn audit QC2 chưa chốt.")
        with transaction.atomic():
            delivery = serializer.save(project=self.project, delivered_by=self.request.user)
            jobs.update(status=JobStatus.DELIVERED)
            batch.status = DataStatus.DELIVERED
            batch.save(update_fields=["status"])
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


class ProjectNotificationsView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/notifications/ — Thông báo hợp nhất (sự kiện cá nhân, cảnh báo hạn, thông báo dự án)."""

    required_capabilities = {"*": Cap.VIEW_PROJECT}

    def get(self, request, project_id):
        user = request.user
        now = timezone.now()
        items = []

        # 1. Thông báo cá nhân đã lưu trong DB
        persisted = list(
            UserNotification.objects.filter(recipient=user, project=self.project).select_related("job")[:40]
        )
        notified_deadline_job_ids = {
            n.job_id for n in persisted if n.category == UserNotification.Category.DEADLINE and n.job_id
        }
        for n in persisted:
            items.append({
                "id": f"sys-{n.id}",
                "notification_id": n.id,
                "source": "system",
                "category": n.category,
                "title": n.title,
                "body": n.body,
                "job_id": n.job_id,
                "action_url": n.action_url or (f"/projects/{self.project.id}/annotator/jobs/{n.job_id}" if n.job_id else ""),
                "is_read": n.is_read,
                "is_pinned_pending": n.is_pinned_pending,
                "created_at": n.created_at.isoformat(),
            })

        # 2. Cảnh báo job sắp / quá hạn đang giữ (TB03 + DB06)
        if user.notify_deadline and self.has_cap(Cap.ANNOTATE_JOBS):
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
                        f"Quá hạn {hours} giờ — ưu tiên xử lý ngay (DB06)."
                        if overdue
                        else f"Còn {hours} giờ — ưu tiên làm trước (DB06)."
                    ),
                    "job_id": j.id,
                    "action_url": f"/projects/{self.project.id}/annotator/jobs/{j.id}",
                    "is_read": False,
                    "is_pinned_pending": True,
                    "created_at": j.updated_at.isoformat(),
                })

        # 3. Thông báo dự án (Announcement) phù hợp vai trò / team
        announcements = Announcement.objects.filter(project=self.project).select_related("sender", "target_team")[:20]
        if not self.has_cap(Cap.SEND_ANNOUNCEMENT):
            my_roles = expand_roles(
                RoleAssignment.objects.filter(user=user, project=self.project).values_list("role", flat=True)
            )
            my_team_ids = set(
                TeamMember.objects.filter(user=user, team__project=self.project).values_list("team_id", flat=True)
            )
            announcements = [
                a for a in announcements
                if (not a.target_roles or set(a.target_roles) & my_roles)
                and (a.target_team_id is None or a.target_team_id in my_team_ids)
            ]
        for a in announcements:
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
                "is_read": a.sender_id == user.id,
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
        qs = UserNotification.objects.filter(recipient=request.user, project=self.project, is_read=False)
        if notif_id is not None:
            qs = qs.filter(pk=notif_id)
        updated = qs.update(is_read=True)
        return Response({"updated": updated})
