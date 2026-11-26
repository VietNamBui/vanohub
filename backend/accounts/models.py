from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    """Bốn vai trò nghiệp vụ. Giá trị (vế trái) được lưu trong DB, nhãn (vế phải) để hiển thị."""

    PROJECT_MANAGER = "project_manager", "Project Manager"
    QC2 = "qc2", "QC2 Auditor"
    QC1 = "qc1", "QC1 Reviewer"
    ANNOTATOR = "annotator", "Annotator"


# Vai trò "kéo theo" đã được xác nhận: PM luôn kiêm QC2.
# Chiều ngược lại KHÔNG đúng: có QC2 không có nghĩa là PM.
IMPLIED_ROLES = {
    Role.PROJECT_MANAGER: {Role.QC2},
}


def expand_roles(roles):
    """Từ các vai trò được gán trực tiếp, trả về toàn bộ vai trò có hiệu lực.

    Chuỗi đọc từ DB (vd. "project_manager") phải đổi về Role(...) trước khi tra từ điển:
    Enum tính hash theo TÊN member, nên "project_manager" và Role.PROJECT_MANAGER
    tuy bằng nhau (==) nhưng không khớp khi làm khoá dict/set.
    """
    effective = {Role(role) for role in roles}
    for role in list(effective):
        effective |= IMPLIED_ROLES.get(role, set())
    return effective


class User(AbstractUser):
    avatar_url = models.TextField(blank=True, default="")
    cvat_username = models.CharField(max_length=150, blank=True, default="")
    timezone_name = models.CharField(max_length=64, default="Asia/Ho_Chi_Minh")
    notify_rework = models.BooleanField(default=True)
    notify_deadline = models.BooleanField(default=True)
    notify_request_updates = models.BooleanField(default=True)
    notify_qc_pass = models.BooleanField(default=True)

    def is_pm(self):
        return self.is_superuser or self.role_assignments.filter(role=Role.PROJECT_MANAGER).exists()

    def get_project_roles(self, project):
        """Vai trò có hiệu lực của user trong một dự án (đã tính vai trò kéo theo)."""
        direct = self.role_assignments.filter(project=project).values_list("role", flat=True)
        return expand_roles(direct)


class RoleAssignment(models.Model):
    """Gán một vai trò cho một user trong một dự án.

    Một user có nhiều vai trò thì có nhiều dòng RoleAssignment.
    Chỉ lưu vai trò gán trực tiếp; vai trò kéo theo (PM → QC2) được tính trong code,
    nên không cần tạo thêm dòng QC2 cho PM.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="role_assignments",
    )
    role = models.CharField(max_length=32, choices=Role.choices)
    project = models.ForeignKey(
        "projects.Project",  # Tham chiếu bằng chuỗi để tránh import vòng giữa các app.
        on_delete=models.CASCADE,
        related_name="role_assignments",
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # Không gán trùng cùng một vai trò trong cùng một dự án.
            models.UniqueConstraint(
                fields=["user", "role", "project"],
                name="unique_role_per_scope",
            ),
        ]

    def __str__(self):
        return f"{self.user} · {self.get_role_display()} · {self.project}"
