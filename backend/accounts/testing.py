"""Hàm tạo dữ liệu dùng chung cho test của các app (không dùng ở code chạy thật)."""

from functools import cached_property
from typing import Any

from rest_framework.test import APIClient

from jobs.models import Job, JobStatus
from projects.models import Batch, Dataset, Project
from quality.models import ErrorCategory

from .models import Role, RoleAssignment, User


def make_user(username: str, *roles: str, project: Project | None = None) -> User:
    user = User.objects.create_user(username, password="pw")
    if roles:
        if project is None:
            raise ValueError("project is required when assigning project roles.")
        for role in roles:
            RoleAssignment.objects.create(user=user, role=role, project=project)
    return user


class ProjectFixture:
    """Một organization nhỏ (model Project): PM, QC2 chuyên trách, 2 annotator, 1 QC1, 1 CVAT project (Dataset), 1 task (Batch)."""

    def __init__(self, name: str = "P") -> None:
        self.project = Project.objects.create(name=name, max_rework_rounds=2, sampling_rate=50)
        p = self.project
        self.pm = make_user(f"{name}_pm", Role.PROJECT_MANAGER, project=p)
        self.qc2 = make_user(f"{name}_qc2", Role.QC2, project=p)
        self.ann1 = make_user(f"{name}_ann1", Role.ANNOTATOR, project=p)
        self.ann2 = make_user(f"{name}_ann2", Role.ANNOTATOR, project=p)
        self.annotator = self.ann1
        self.qc1 = make_user(f"{name}_qc1", Role.QC1, project=p)
        self.dataset = Dataset.objects.create(project=p, name="D1")
        self.batch = Batch.objects.create(project=p, dataset=self.dataset, name="B1")
        self.category = ErrorCategory.objects.create(project=p, name="Sai nhãn")

    @cached_property
    def outsider(self) -> User:
        return make_user(f"{self.project.name}_outsider")

    def job(
        self,
        status: str = JobStatus.PENDING_QC2,
        annotator: User | None = None,
        **extra: Any,
    ) -> Job:
        n = Job.objects.filter(project=self.project).count() + 1
        batch: Batch = extra.setdefault("batch", self.batch)
        extra.setdefault("dataset", batch.dataset)
        extra.setdefault("qc1_reviewer", self.qc1)
        return Job.objects.create(
            project=self.project,
            name=f"J{n}",
            status=status,
            annotator=annotator or (self.ann1 if n % 2 else self.ann2),
            **extra,
        )

    def url(self, path: str) -> str:
        return f"/api/projects/{self.project.id}/{path}"

    @staticmethod
    def client(user: Any) -> Any:
        client = APIClient()
        client.force_authenticate(user)
        return client
