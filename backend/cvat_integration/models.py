from typing import TYPE_CHECKING

from django.conf import settings
from django.db import models


class CvatAccount(models.Model):
    """Liên kết một tài khoản VanoHub với một tài khoản CVAT (mỗi người tự liên kết).

    Chỉ lưu ID và username bên CVAT. Access token người dùng dán vào chỉ dùng một lần
    để xác minh rồi bỏ đi — VanoHub giao việc trên CVAT bằng tài khoản hệ thống (backend/.env).
    """

    if TYPE_CHECKING:
        id: int
        user_id: int

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cvat_account")
    # unique: một tài khoản CVAT không được gắn cho hai người VanoHub.
    cvat_user_id = models.PositiveIntegerField(unique=True)
    cvat_username = models.CharField(max_length=150)
    linked_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} ⇄ CVAT {self.cvat_username} (#{self.cvat_user_id})"
