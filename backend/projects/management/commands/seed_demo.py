"""DỮ LIỆU GIẢ cho môi trường development — KHÔNG phải dữ liệu thật từ CVAT.

    pipenv run python manage.py seed_demo                 # tạo dự án demo
    pipenv run python manage.py seed_demo --pm admin      # thêm user "admin" làm PM của dự án demo
    pipenv run python manage.py seed_demo --reset         # xoá dữ liệu demo rồi tạo lại

Mọi tài khoản demo dùng mật khẩu: Demo@12345
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Role, RoleAssignment, User
from jobs.models import Job, JobStatus
from projects.models import Batch, Dataset, Guideline, Project
from quality.models import ErrorCategory, Severity
from teams.models import Team, TeamMember

PROJECT_NAME = "[DEMO] Robotaxi 3D Cuboid"
PASSWORD = "Demo@12345"
USERS = {
    "director_demo": [Role.DIRECTOR],
    "pm_demo": [Role.PROJECT_MANAGER],
    "qc2_demo": [Role.QC2],
    "tl_demo": [Role.TEAM_LEADER],
    "qc1_demo": [Role.QC1, Role.ANNOTATOR],
    "ann1_demo": [Role.ANNOTATOR],
    "ann2_demo": [Role.ANNOTATOR],
    "ann3_demo": [Role.ANNOTATOR],
    "ann4_demo": [Role.ANNOTATOR],
}


class Command(BaseCommand):
    help = "Tao du lieu demo (gia) cho moi truong development."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Xoa du an va user demo truoc khi tao lai")
        parser.add_argument("--pm", help="Username co san se duoc gan lam PM cua du an demo")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Chi chay seed_demo khi DEBUG=True (moi truong dev).")
        if options["reset"]:
            Project.objects.filter(name=PROJECT_NAME).delete()
            User.objects.filter(username__in=USERS).delete()
        project = Project.objects.filter(name=PROJECT_NAME).first()
        if project is None:
            project = self._create()
            self.stdout.write(self.style.SUCCESS(f"Da tao du an demo #{project.id}. Mat khau demo: {PASSWORD}"))
        else:
            self.stdout.write("Du an demo da ton tai (dung --reset de tao lai).")
        if options["pm"]:
            user = User.objects.filter(username=options["pm"]).first()
            if not user:
                raise CommandError(f"Khong co user '{options['pm']}'.")
            RoleAssignment.objects.get_or_create(user=user, role=Role.PROJECT_MANAGER, project=project)
            self.stdout.write(self.style.SUCCESS(f"Da gan {user} lam PM cua du an demo."))

    @transaction.atomic
    def _create(self):
        now = timezone.now()
        users = {}
        for username, roles in USERS.items():
            user, _ = User.objects.get_or_create(username=username, defaults={"first_name": username.split("_")[0].upper()})
            user.set_password(PASSWORD)
            user.save()
            users[username] = user

        project = Project.objects.create(
            name=PROJECT_NAME, description="Dữ liệu giả để thử luồng PM / QC2 — không phải dữ liệu thật.",
            created_by=users["director_demo"], sampling_rate=30, max_rework_rounds=2,
        )
        for username, roles in USERS.items():
            for role in roles:
                RoleAssignment.objects.get_or_create(
                    user=users[username], role=role, project=None if role == Role.DIRECTOR else project
                )

        team_a = Team.objects.create(project=project, name="Team A", leader=users["tl_demo"])
        team_b = Team.objects.create(project=project, name="Team B")
        for name in ("tl_demo", "qc1_demo", "ann1_demo", "ann2_demo"):
            TeamMember.objects.create(team=team_a, user=users[name])
        for name in ("ann3_demo", "ann4_demo"):
            TeamMember.objects.create(team=team_b, user=users[name], capacity=4)

        for name, severity in [("Sai nhãn", Severity.MAJOR), ("Thiếu object", Severity.CRITICAL),
                               ("Sai kích thước cuboid", Severity.MINOR), ("Sai tracking ID", Severity.MAJOR)]:
            ErrorCategory.objects.create(project=project, name=name, severity=severity)

        Guideline.objects.create(
            project=project, version=1, title="Hướng dẫn gán cuboid v1", created_by=users["pm_demo"],
            content="## Phạm vi\nGán cuboid cho xe, người đi bộ, xe máy.\n\n## Quy tắc\n- Cuboid ôm sát vật thể.\n",
        )

        ds_front = Dataset.objects.create(project=project, name="Front camera 11/2026", created_by=users["pm_demo"])
        ds_lidar = Dataset.objects.create(project=project, name="Lidar night 11/2026", created_by=users["pm_demo"])
        # B01, B02 giao cho Team A (tl_demo là leader) → TL thấy "Job của team".
        b01 = Batch.objects.create(dataset=ds_front, name="B01", deadline=now + timedelta(days=2), team=team_a)
        b02 = Batch.objects.create(dataset=ds_front, name="B02", deadline=now + timedelta(days=5), team=team_a)
        b03 = Batch.objects.create(dataset=ds_lidar, name="N01", deadline=now + timedelta(days=7))

        annotators = [users[n] for n in ("ann1_demo", "ann2_demo", "ann3_demo", "ann4_demo")]
        qc1 = [users["qc1_demo"], users["tl_demo"]]

        def make(batch, index, status, **extra):
            annotator = annotators[index % len(annotators)]
            return Job.objects.create(
                project=project, batch=batch, name=f"{batch.name}-{index:03d}", status=status,
                annotator=annotator, qc1_reviewer=qc1[index % 2] if status not in (
                    JobStatus.PENDING_ANNOTATION, JobStatus.ANNOTATING) else None,
                deadline=batch.deadline, frame_count=100, object_count=40 + index * 3, **extra,
            )

        # B01: 12 job đã qua QC1, chờ QC2 → dùng để thử tạo audit.
        for i in range(1, 13):
            make(b01, i, JobStatus.PENDING_QC2)
        # B02: trạng thái trộn lẫn, có job quá hạn và escalated.
        mix = [JobStatus.ANNOTATING, JobStatus.ANNOTATING, JobStatus.PENDING_QC1, JobStatus.QC1_REVIEWING,
               JobStatus.REWORK, JobStatus.PENDING_QC2, JobStatus.APPROVED, JobStatus.PENDING_ANNOTATION]
        for i, status in enumerate(mix, 1):
            make(b02, i, status, rework_round=1 if status == JobStatus.REWORK else 0)
        make(b02, 20, JobStatus.REWORK, rework_round=3, is_escalated=True)
        overdue = make(b02, 21, JobStatus.ANNOTATING)
        overdue.deadline = now - timedelta(hours=6)
        overdue.save()
        # N01: chưa giao.
        for i in range(1, 6):
            Job.objects.create(project=project, batch=b03, name=f"N01-{i:03d}", deadline=b03.deadline, frame_count=80)
        return project
