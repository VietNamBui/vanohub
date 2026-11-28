"""DỮ LIỆU GIẢ cho môi trường development — KHÔNG phải dữ liệu thật từ CVAT.

    pipenv run python manage.py seed_demo                 # tạo dữ liệu demo
    pipenv run python manage.py seed_demo --pm admin      # thêm user "admin" làm PM của dữ liệu demo
    pipenv run python manage.py seed_demo --reset         # xoá dữ liệu demo rồi tạo lại

Mọi tài khoản demo dùng mật khẩu: Demo@12345
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Role, RoleAssignment, User
from jobs.models import AnnotatorRequest, DailyOutputRecord, Job, JobStatus, ReworkScope, record_daily_output
from projects.models import ActivityLog, Batch, Dataset, Guideline, Project, UserNotification
from quality.models import ErrorCategory, ReviewError, ReviewStage, Severity
from quality.qc2 import ensure_qc2_sample
from teams.models import Team, TeamMember

PROJECT_NAME = "[DEMO] Robotaxi 3D Cuboid"
PASSWORD = "Demo@12345"
USERS = {
    "pm_demo": [Role.PROJECT_MANAGER],
    "qc2_demo": [Role.QC2],
    "qc1_demo": [Role.QC1, Role.ANNOTATOR],
    "ann1_demo": [Role.ANNOTATOR],
    "ann2_demo": [Role.ANNOTATOR],
    "ann3_demo": [Role.ANNOTATOR],
    "ann4_demo": [Role.ANNOTATOR],
}


class Command(BaseCommand):
    help = "Tao du lieu demo (gia) cho moi truong development."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Xoa organization va user demo truoc khi tao lai")
        parser.add_argument("--pm", help="Username co san se duoc gan lam PM cua organization demo")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Chi chay seed_demo khi DEBUG=True (moi truong dev).")
        if options["reset"]:
            Project.objects.filter(name=PROJECT_NAME).delete()
            User.objects.filter(username__in=USERS).delete()
        project = Project.objects.filter(name=PROJECT_NAME).first()
        if project is None:
            project = self._create()
            self.stdout.write(self.style.SUCCESS(f"Da tao organization demo #{project.id}. Mat khau demo: {PASSWORD}"))
        else:
            self.stdout.write("Organization demo da ton tai (dung --reset de tao lai).")
        if options["pm"]:
            user = User.objects.filter(username=options["pm"]).first()
            if not user:
                raise CommandError(f"Khong co user '{options['pm']}'.")
            RoleAssignment.objects.get_or_create(user=user, role=Role.PROJECT_MANAGER, project=project)
            self.stdout.write(self.style.SUCCESS(f"Da gan {user} lam PM cua organization demo."))

    @transaction.atomic
    def _create(self):
        now = timezone.now()
        users = {}
        for username in USERS:
            user, _ = User.objects.get_or_create(
                username=username, defaults={"first_name": username.split("_")[0].upper()}
            )
            user.set_password(PASSWORD)
            user.save()
            users[username] = user

        project = Project.objects.create(
            name=PROJECT_NAME,
            description="Dữ liệu giả để thử luồng PM / QC2 / QC1 / Annotator — không phải dữ liệu thật.",
            created_by=users["pm_demo"],
            sampling_rate=20,
            max_rework_rounds=2,
            annotator_wip_limit=2,
            kpi_annotation_target=1200,
        )
        for username, roles in USERS.items():
            for role in roles:
                RoleAssignment.objects.get_or_create(user=users[username], role=role, project=project)

        team_a = Team.objects.create(project=project, name="Team A")
        team_b = Team.objects.create(project=project, name="Team B")
        for name in ("qc1_demo", "ann1_demo", "ann2_demo"):
            TeamMember.objects.create(team=team_a, user=users[name])
        for name in ("ann3_demo", "ann4_demo"):
            TeamMember.objects.create(team=team_b, user=users[name], capacity=4)

        for code, primary_cat, name, severity in [
            ("E2", "E2", "Sai nhãn", Severity.MAJOR),
            ("E1", "E1", "Thiếu object", Severity.CRITICAL),
            ("E3", "E3", "Sai kích thước cuboid", Severity.MINOR),
            ("E6", "E6", "Sai tracking ID", Severity.MAJOR),
        ]:
            ErrorCategory.objects.create(
                project=project,
                code=code,
                primary_category=primary_cat,
                name=name,
                severity=severity,
            )

        Guideline.objects.create(
            project=project,
            version=1,
            title="Hướng dẫn gán cuboid v1",
            created_by=users["pm_demo"],
            content="## Phạm vi\nGán cuboid cho xe, người đi bộ, xe máy.\n\n## Quy tắc\n- Cuboid ôm sát vật thể.\n",
        )

        ds_front = Dataset.objects.create(project=project, name="Front camera 11/2026", created_by=users["pm_demo"])
        ds_lidar = Dataset.objects.create(project=project, name="Lidar night 11/2026", created_by=users["pm_demo"])
        # Dataset = "Project" (CVAT project), Batch = "Task" (CVAT task) trên giao diện.
        b01 = Batch.objects.create(
            project=project, dataset=ds_front, name="B01", deadline=now + timedelta(days=2), team=team_a
        )
        b02 = Batch.objects.create(
            project=project, dataset=ds_front, name="B02", deadline=now + timedelta(days=5), team=team_a
        )
        b04 = Batch.objects.create(
            project=project, dataset=ds_front, name="B04-QC1-Ready", deadline=now + timedelta(days=3), team=team_a
        )
        b03 = Batch.objects.create(
            project=project, dataset=ds_lidar, name="N01", deadline=now + timedelta(days=7)
        )
        dataset_of = {b01: ds_front, b02: ds_front, b04: ds_front, b03: ds_lidar}

        annotators = [users[n] for n in ("ann1_demo", "ann2_demo", "ann3_demo", "ann4_demo")]
        qc1 = [users["qc1_demo"]]

        def make(batch, index, status, **extra):
            annotator = extra.pop("annotator", annotators[index % len(annotators)])
            extra.setdefault("total_rework_rounds", extra.get("rework_round", 0))
            return Job.objects.create(
                project=project,
                dataset=dataset_of[batch],
                batch=batch,
                name=f"{batch.name}-{index:03d}",
                status=status,
                annotator=annotator,
                qc1_reviewer=qc1[index % len(qc1)]
                if status not in (JobStatus.PENDING_ANNOTATION, JobStatus.ANNOTATING)
                else None,
                deadline=batch.deadline,
                frame_count=100,
                object_count=40 + index * 3,
                **extra,
            )

        # B01: 12 job đã qua QC1, chờ QC2 → dùng để thử luồng QC2.
        for i in range(1, 13):
            make(b01, i, JobStatus.PENDING_QC2)
        # B04: 4 job đạt QC1 100% → dùng để PM thử "Xác nhận chuyển QC2" theo task.
        for i in range(1, 5):
            make(b04, i, JobStatus.QC1_PASSED)
        # B02: trạng thái trộn lẫn, có job quá hạn và escalated.
        mix = [
            JobStatus.ANNOTATING,
            JobStatus.ANNOTATING,
            JobStatus.PENDING_QC1,
            JobStatus.QC1_REVIEWING,
            JobStatus.REWORK,
            JobStatus.PENDING_QC2,
            JobStatus.APPROVED,
            JobStatus.PENDING_ANNOTATION,
        ]
        for i, st in enumerate(mix, 1):
            make(b02, i, st, rework_round=1 if st == JobStatus.REWORK else 0)
        make(b02, 19, JobStatus.REWORK, annotator=users["ann1_demo"], rework_round=1)
        make(b02, 20, JobStatus.REWORK, annotator=users["ann3_demo"], rework_round=3, is_escalated=True)
        overdue = make(b02, 21, JobStatus.ANNOTATING)
        overdue.deadline = now - timedelta(hours=6)
        overdue.save()
        # N01: chưa giao (dùng để thử "Nhận job mới").
        for i in range(1, 6):
            Job.objects.create(
                project=project,
                dataset=ds_lidar,
                batch=b03,
                name=f"N01-{i:03d}",
                deadline=b03.deadline,
                frame_count=80,
                target_object_count=960,
            )

        for qc2_job in Job.objects.filter(project=project, status=JobStatus.PENDING_QC2):
            ensure_qc2_sample(qc2_job)

        # Dữ liệu mẫu cho ann1_demo: lỗi rework, yêu cầu phản hồi lỗi / dữ liệu bị chặn & thông báo
        ann1_rework = Job.objects.filter(
            project=project,
            annotator=users["ann1_demo"],
            status=JobStatus.REWORK,
            is_escalated=False,
        ).first()
        if ann1_rework:
            ann1_rework.target_object_count = 1210
            ann1_rework.object_count = 1065
            ann1_rework.rework_scope = ReworkScope.PARTIAL
            ann1_rework.deadline = now + timedelta(hours=8)
            ann1_rework.save(update_fields=["target_object_count", "object_count", "rework_scope", "deadline"])
            cats = list(ErrorCategory.objects.filter(project=project))
            if cats:
                err_round = max(0, ann1_rework.rework_round - 1)
                e1 = ReviewError.objects.create(
                    job=ann1_rework,
                    stage=ReviewStage.QC1,
                    rework_round=err_round,
                    category=cats[0],
                    severity=Severity.MAJOR,
                    location="Frame 214 · Object 38",
                    description="Cuboid xe tải lệch đuôi ~0,4m",
                    reported_by=users["qc1_demo"],
                )
                ReviewError.objects.create(
                    job=ann1_rework,
                    stage=ReviewStage.QC1,
                    rework_round=err_round,
                    category=cats[min(1, len(cats) - 1)],
                    severity=Severity.CRITICAL,
                    location="Frame 220 · Chưa có ID object",
                    description="Thiếu người đi bộ sau cột đèn",
                    reported_by=users["qc1_demo"],
                )
                AnnotatorRequest.objects.create(
                    project=project,
                    job=ann1_rework,
                    review_error=e1,
                    request_type=AnnotatorRequest.RequestType.ERROR_DISPUTE,
                    status=AnnotatorRequest.Status.PENDING_PM,
                    title=f"Không đồng ý lỗi '{e1.category.name}' frame 214",
                    reason="Điểm point cloud đuôi xe bị nhiễu mưa.",
                    progress_note="PM đang đối chiếu frame 214.",
                    created_by=users["ann1_demo"],
                    handler=users["pm_demo"],
                    handler_role="PM",
                )
                UserNotification.objects.create(
                    recipient=users["ann1_demo"],
                    project=project,
                    job=ann1_rework,
                    category=UserNotification.Category.REWORK,
                    title=f"{ann1_rework.name} bị trả sửa (vòng {ann1_rework.rework_round})",
                    body="QC1 ghi 2 lỗi theo object-frame. Ưu tiên xử lý trước hạn.",
                    action_url=f"/projects/{project.id}/annotator/jobs/{ann1_rework.id}",
                    is_pinned_pending=True,
                )

        # Cập nhật target_object_count cho các job chưa có
        for job in Job.objects.filter(project=project, target_object_count=0):
            job.target_object_count = max(job.object_count, 1000)
            job.save(update_fields=["target_object_count"])

        # Lịch sử nộp bài vài ngày gần đây để biểu đồ dashboard có dữ liệu
        sample_job = Job.objects.filter(project=project, annotator=users["ann1_demo"]).first()
        if sample_job:
            for days_ago, objs in [(5, 1080), (4, 1150), (3, 1010), (2, 1220), (1, 1190), (0, 980)]:
                when = now - timedelta(days=days_ago)
                ev = ActivityLog.record(
                    project=project,
                    actor=users["ann1_demo"],
                    action="job.status",
                    target=sample_job,
                    job=sample_job,
                    before={"status": JobStatus.ANNOTATING},
                    after={"status": JobStatus.PENDING_QC1, "event": "annotator.submit", "object_count": objs},
                )
                ActivityLog.objects.filter(pk=ev.pk).update(created_at=when)
                record_daily_output(
                    job=sample_job,
                    user=users["ann1_demo"],
                    object_count=objs,
                    is_rework=False,
                    rework_round=0,
                    source=DailyOutputRecord.Source.SUBMIT,
                    at=when,
                )
        return project
