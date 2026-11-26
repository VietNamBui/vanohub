from django.conf import settings
from django.db import models


class Team(models.Model):
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="teams")
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["project", "name"], name="unique_team_name_per_project")]

    def __str__(self):
        return self.name


class TeamMember(models.Model):
    """Một người thuộc một team.

    ĐỀ XUẤT (chưa chốt): trong một dự án, mỗi người chỉ thuộc một team → điều chuyển
    là chuyển dòng này sang team khác. Ràng buộc được kiểm tra trong serializer/view
    vì team nằm ở bảng khác (DB không tự ràng buộc "unique theo project" qua FK được).
    """

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="team_memberships")
    capacity = models.PositiveSmallIntegerField(default=5, help_text="Số job tối đa đang giữ cùng lúc")
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["user__username"]
        constraints = [models.UniqueConstraint(fields=["team", "user"], name="unique_team_member")]

    def __str__(self):
        return f"{self.user} @ {self.team}"
