"""QC2 theo frame (chốt 2026-11-25): MỌI job qua QC1 đều được QC2 kiểm, mỗi job kiểm ngẫu nhiên
`project.sampling_rate` % số frame (làm tròn lên, ít nhất 1 frame).

Mỗi lần job vào trạng thái Chờ QC2 (lần đầu hoặc sau rework) → một lượt QC2 (AuditSample) mới,
gom trong Audit đang mở của task (Batch). Frame được chọn cố định theo (job, vòng rework) nên
đồng bộ lại không làm đổi frame.
"""

import math
import random

from django.db.models import Count, Q

from accounts.models import Role, User
from jobs.models import JobStatus

from .models import Audit, AuditSample


def pick_auditor(job):
    """ĐỀ XUẤT (chưa chốt): tự giao lượt QC2 cho người có vai trò QC2 (gán trực tiếp, không tính PM kiêm QC2)
    đang giữ ít lượt chờ kiểm nhất, trừ người đã annotate / QC1 job (luật bốn mắt). Không có ai → để trống, PM phân."""
    blocked = {uid for uid in (job.annotator_id, job.qc1_reviewer_id) if uid}
    candidates = (
        User.objects.filter(role_assignments__project=job.project, role_assignments__role=Role.QC2)
        .exclude(pk__in=blocked)
        .annotate(load=Count("audit_samples", filter=Q(audit_samples__result=AuditSample.Result.PENDING,
                                                       audit_samples__audit__project=job.project)))
        .order_by("load", "id")
    )
    return candidates.first()


def pick_frames(job, rate):
    total = max(job.frame_count, 1)
    count = min(total, max(1, math.ceil(total * rate / 100)))
    rng = random.Random(f"{job.pk}:{job.rework_round}")
    return [job.cvat_start_frame + offset for offset in sorted(rng.sample(range(total), count))]


def ensure_qc2_sample(job):
    """Job đang Chờ QC2 mà chưa có lượt QC2 đang chờ → tạo lượt mới. Trả về lượt QC2 (hoặc None)."""
    if job.status != JobStatus.PENDING_QC2:
        return None
    pending = job.audit_samples.filter(result=AuditSample.Result.PENDING).first()
    if pending:
        return pending
    project = job.project
    audit = Audit.objects.filter(batch=job.batch, status=Audit.Status.IN_PROGRESS).first()
    if audit is None:
        audit = Audit.objects.create(project=project, batch=job.batch, method="random",
                                     sampling_rate=project.sampling_rate, seed=0, eligible_count=0)
    return AuditSample.objects.create(audit=audit, job=job, rework_round=job.rework_round,
                                      frames=pick_frames(job, project.sampling_rate), auditor=pick_auditor(job))
