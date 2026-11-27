"""QC2 theo frame (chốt 2026-11-25): MỌI job qua QC1 đều được QC2 kiểm, mỗi job kiểm ngẫu nhiên
`project.sampling_rate` % số frame (làm tròn lên, ít nhất 1 frame).

Mỗi lần job vào trạng thái Chờ QC2 (lần đầu hoặc sau rework) → một lượt QC2 (AuditSample) mới,
gom trong Audit đang mở của task (Batch). Frame được chọn cố định theo (job, vòng rework) nên
đồng bộ lại không làm đổi frame.
"""

import math
import random

from django.db import IntegrityError, transaction
from django.db.models import Count, Q

from accounts.models import Role, User
from jobs.models import DailyOutputRecord, Job, JobStatus
from projects.models import ActivityLog, Batch, SamplingMethod

from .models import Audit, AuditSample, ReviewError, ReviewStage

ANNOTATOR_EVENTS = (
    "annotator.claim",
    "annotator.start",
    "annotator.start_rework",
    "annotator.submit",
    "annotator.resubmit",
)
QC1_EVENTS = ("qc1.start", "qc1.pass", "qc1.reject")


def get_stage_history(job: Job) -> tuple[set[int], set[int], set[int]]:
    """Trả về (annotator_ids, qc1_ids, qc2_ids) gồm cả người hiện tại và lịch sử đa giai đoạn của job."""
    annotator_ids: set[int] = {job.annotator_id} if job.annotator_id else set()
    qc1_ids: set[int] = {job.qc1_reviewer_id} if job.qc1_reviewer_id else set()
    qc2_ids: set[int] = set()

    log_rows = (
        ActivityLog.objects.filter(job=job, actor_id__isnull=False)
        .filter(
            Q(action__in=ANNOTATOR_EVENTS + QC1_EVENTS)
            | Q(action__in=("job.status", "job.assign"), after__event__in=ANNOTATOR_EVENTS)
            | Q(action="job.status", after__event__in=QC1_EVENTS)
            | Q(action="job.status", after__status__in=[JobStatus.ANNOTATING, JobStatus.PENDING_QC1])
        )
        .values_list("action", "after", "actor_id")
    )
    for action, after, actor_id in log_rows:
        if actor_id is None:
            continue
        event_name = after.get("event") if isinstance(after, dict) else None
        if action in QC1_EVENTS or event_name in QC1_EVENTS:
            qc1_ids.add(actor_id)
        elif action in ANNOTATOR_EVENTS or (
            isinstance(after, dict)
            and (
                event_name in ANNOTATOR_EVENTS
                or (action == "job.status" and after.get("status") in (JobStatus.ANNOTATING, JobStatus.PENDING_QC1))
            )
        ):
            annotator_ids.add(actor_id)

    for before, after in ActivityLog.objects.filter(
        job=job, action__in=("job.assign", "job.import")
    ).values_list("before", "after"):
        for payload in (before, after):
            if not isinstance(payload, dict):
                continue
            ann_id = payload.get("annotator")
            if isinstance(ann_id, int) and not isinstance(ann_id, bool):
                annotator_ids.add(ann_id)
            qc1_id = payload.get("qc1_reviewer")
            if isinstance(qc1_id, int) and not isinstance(qc1_id, bool):
                qc1_ids.add(qc1_id)

    for user_id in DailyOutputRecord.objects.filter(job=job).values_list("user_id", flat=True):
        if user_id is not None:
            annotator_ids.add(user_id)

    for stage, reported_by_id in ReviewError.objects.filter(
        job=job, reported_by_id__isnull=False
    ).values_list("stage", "reported_by_id"):
        if reported_by_id is None:
            continue
        if stage == ReviewStage.QC1:
            qc1_ids.add(reported_by_id)
        elif stage == ReviewStage.QC2:
            qc2_ids.add(reported_by_id)

    for auditor_id, reviewed_by_id in AuditSample.objects.filter(job=job).values_list("auditor_id", "reviewed_by_id"):
        if auditor_id:
            qc2_ids.add(auditor_id)
        if reviewed_by_id:
            qc2_ids.add(reviewed_by_id)

    return annotator_ids, qc1_ids, qc2_ids


def four_eyes_conflicts(job: Job) -> set[int]:
    """Luật bốn mắt cho QC2: chặn mọi người đã từng annotate hoặc QC1 job này (kể cả lịch sử)."""
    annotator_ids, qc1_ids, _ = get_stage_history(job)
    return annotator_ids | qc1_ids


def pick_auditor(job: Job) -> User | None:
    """Tự giao lượt QC2 cho người có vai trò QC2 (gán trực tiếp, không tính PM kiêm QC2)
    đang giữ ít lượt chờ kiểm nhất, trừ người đã annotate / QC1 job (luật bốn mắt).
    Không có ai phù hợp → để trống cho PM phân.
    """
    blocked = four_eyes_conflicts(job)
    candidates = (
        User.objects.filter(
            is_active=True,
            role_assignments__project=job.project,
            role_assignments__role=Role.QC2,
        )
        .exclude(pk__in=blocked)
        .annotate(
            load=Count(
                "audit_samples",
                filter=Q(
                    audit_samples__result=AuditSample.Result.PENDING,
                    audit_samples__audit__project=job.project,
                ),
            )
        )
        .order_by("load", "id")
    )
    return candidates.first()


def pick_frames(job: Job, rate: int) -> list[int]:
    """Chọn cố định sampling_rate % frame của job theo (job.pk, max(total_rework_rounds, rework_round))."""
    total = max(job.frame_count, 1)
    count = min(total, max(1, math.ceil(total * rate / 100)))
    # Non-cryptographic deterministic sampling per (job, cumulative rework round)
    rng = random.Random(f"{job.pk}:{max(job.total_rework_rounds, job.rework_round)}")
    return [job.cvat_start_frame + offset for offset in sorted(rng.sample(range(total), count))]


def ensure_qc2_sample(job: Job) -> AuditSample | None:
    """Job đang Chờ QC2 mà chưa có lượt QC2 đang chờ → tạo lượt mới. Trả về lượt QC2 (hoặc None)."""
    if job.status != JobStatus.PENDING_QC2:
        return None
    with transaction.atomic():
        batch = Batch.objects.select_for_update(of=("self",)).get(pk=job.batch_id)
        locked_job = Job.objects.select_for_update(of=("self",)).select_related("project", "batch").get(pk=job.pk)
        if locked_job.status != JobStatus.PENDING_QC2:
            return None
        pending = AuditSample.objects.filter(job=locked_job, result=AuditSample.Result.PENDING).first()
        if pending is not None:
            return pending
        project = locked_job.project
        audit = Audit.objects.filter(batch=batch, status=Audit.Status.IN_PROGRESS).first()
        if audit is None:
            try:
                with transaction.atomic():
                    audit = Audit.objects.create(
                        project=project,
                        batch=batch,
                        method=SamplingMethod.RANDOM,
                        sampling_rate=project.sampling_rate,
                        seed=0,
                        eligible_count=0,
                    )
            except IntegrityError:
                audit = Audit.objects.get(batch=batch, status=Audit.Status.IN_PROGRESS)
        try:
            with transaction.atomic():
                return AuditSample.objects.create(
                    audit=audit,
                    job=locked_job,
                    rework_round=max(locked_job.total_rework_rounds, locked_job.rework_round),
                    frames=pick_frames(locked_job, project.sampling_rate),
                    auditor=pick_auditor(locked_job),
                )
        except IntegrityError:
            return AuditSample.objects.get(job=locked_job, result=AuditSample.Result.PENDING)
