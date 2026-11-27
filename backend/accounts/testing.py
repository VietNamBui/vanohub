"""Hàm tạo dữ liệu dùng chung cho test của các app (không dùng ở code chạy thật)."""

from jobs.models import Job, JobStatus
from projects.models import Batch, Dataset, Project
from quality.models import ErrorCategory
from rest_framework.test import APIClient

from .models import Role, RoleAssignment, User


def make_user(username, *roles, project=None):
    user = User.objects.create_user(username, password="pw")
    for role in roles:
        RoleAssignment.objects.create(user=user, role=role, project=project)
    return user


class ProjectFixture:
    """Một organization nhỏ (model Project): PM, QC2 chuyên trách, 2 annotator, 1 QC1, 1 CVAT project (Dataset), 1 task (Batch)."""

    def __init__(self, name="P"):
        self.project = Project.objects.create(name=name, max_rework_rounds=2, sampling_rate=50)
        p = self.project
        self.pm = make_user(f"{name}_pm", Role.PROJECT_MANAGER, project=p)
        self.qc2 = make_user(f"{name}_qc2", Role.QC2, project=p)
        self.ann1 = make_user(f"{name}_ann1", Role.ANNOTATOR, project=p)
        self.ann2 = make_user(f"{name}_ann2", Role.ANNOTATOR, project=p)
        self.qc1 = make_user(f"{name}_qc1", Role.QC1, project=p)
        self.dataset = Dataset.objects.create(project=p, name="D1")
        self.batch = Batch.objects.create(project=p, dataset=self.dataset, name="B1")
        self.category = ErrorCategory.objects.create(project=p, name="Sai nhãn")

    def job(self, status=JobStatus.PENDING_QC2, annotator=None, **extra):
        n = Job.objects.filter(project=self.project).count() + 1
        extra.setdefault("dataset", self.dataset)
        extra.setdefault("batch", self.batch)
        return Job.objects.create(
            project=self.project, name=f"J{n}", status=status,
            annotator=annotator or (self.ann1 if n % 2 else self.ann2), qc1_reviewer=self.qc1, **extra,
        )

    def url(self, path):
        return f"/api/projects/{self.project.id}/{path}"

    @staticmethod
    def client(user):
        client = APIClient()
        client.force_authenticate(user)
        return client
