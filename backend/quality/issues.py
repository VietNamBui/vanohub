"""JobIssue lifecycle, CVAT issue ingestion, tamper defenses, Two-Gate checks, and PM adjudication."""

from __future__ import annotations

import hashlib
import inspect
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from accounts.models import Role, RoleAssignment, User, expand_roles
from cvat_integration.assignee import _close_quietly, _release_advisory_lock, _try_advisory_lock
from cvat_integration.client import CvatClient, CvatError, _validate_model
from cvat_integration.models import CvatAccount
from cvat_integration.schemas import CvatCommentPayload, CvatIssuePayload
from jobs.models import ACTIVE_ANNOTATOR_STATUSES, AnnotatorRequest, Job, JobStatus
from projects.models import ActivityLog, DataStatus, EscalationPolicy, Project, UserNotification
from teams.models import TeamMember

from .issue_envelope import (
    DISPUTE_WORD_RE,
    SEV_RANK,
    decode_3d_position,
    parse_envelope,
    should_skip_preqc,
)
from .models import AuditSample, ErrorVerdict, JobIssue, ReviewError, ReviewStage
from .qc2 import get_stage_history

logger = logging.getLogger(__name__)

_ISSUE_IMPORT_LOCK_NS = 0x56484A49  # "VHJI"
_BLOCKING_SEVERITIES = ("critical", "major")


@dataclass(frozen=True)
class CvatIssueSnapshot:
    fetched_at: datetime
    issues: list[CvatIssuePayload]
    comments: list[CvatCommentPayload]


def _lock_job(project: Project, job_id: int) -> Job:
    job = (
        Job.objects.select_for_update(of=("self",))
        .select_related("batch", "dataset", "batch__team", "project", "annotator", "qc1_reviewer")
        .filter(pk=job_id, project=project)
        .first()
    )
    if job is None:
        raise NotFound("Không tìm thấy job trong organization.")
    return job


def _ensure_editable(job: Job) -> None:
    if job.is_locked:
        raise ValidationError(f"Job {job} đang bị khoá.")
    if job.batch.status != DataStatus.ACTIVE:
        raise ValidationError(f"Task của job {job} đã khoá hoặc đã bàn giao.")
    if job.dataset.status != DataStatus.ACTIVE:
        raise ValidationError(f"Project của job {job} đã khoá.")
    if job.status == JobStatus.DELIVERED:
        raise ValidationError(f"Job {job} đã bàn giao.")


def _ensure_not_escalated(job: Job) -> None:
    if job.is_escalated and job.project.escalation_policy == EscalationPolicy.BLOCK:
        raise ValidationError("Job đang ở trạng thái Escalated, chờ PM xử lý.")


def _ensure_not_delivered(job: Job) -> None:
    if (
        job.status == JobStatus.DELIVERED
        or job.batch.status == DataStatus.DELIVERED
        or job.dataset.status == DataStatus.DELIVERED
    ):
        raise ValidationError("Không thể thao tác khi job hoặc task đã bàn giao (BG03).")


def _project_pms(project: Project) -> list[User]:
    assignments = (
        RoleAssignment.objects.filter(project=project, role=Role.PROJECT_MANAGER, user__is_active=True)
        .select_related("user")
        .order_by("user_id")
    )
    seen: set[int] = set()
    out: list[User] = []
    for a in assignments:
        if a.user_id not in seen:
            seen.add(a.user_id)
            out.append(a.user)
    return out


def _user_roles(project: Project, user: User) -> set[Role]:
    roles = set(user.get_project_roles(project))
    if getattr(user, "is_superuser", False):
        roles |= expand_roles([Role.PROJECT_MANAGER])
    return roles


def _issue_action_url(project_id: int, issue_id: int) -> str:
    return f"/projects/{project_id}/jobs?issue={issue_id}"


def _request_action_url(project_id: int) -> str:
    return f"/projects/{project_id}/annotator/requests"


def _pin_pm_issue_notification(project: Project, job: Job, issue: JobIssue, *, title: str, body: str) -> None:
    action_url = _issue_action_url(project.pk, issue.pk)
    for pm in _project_pms(project):
        already = UserNotification.objects.filter(
            recipient=pm,
            project=project,
            job=job,
            category=UserNotification.Category.DISPUTE,
            action_url=action_url,
            is_pinned_pending=True,
        ).exists()
        if not already:
            UserNotification.objects.create(
                recipient=pm,
                project=project,
                job=job,
                category=UserNotification.Category.DISPUTE,
                title=title[:200],
                body=body,
                action_url=action_url,
                is_pinned_pending=True,
            )


def _unpin_issue_notifications(project: Project, job: Job, issue: JobIssue) -> None:
    UserNotification.objects.filter(
        project=project,
        job=job,
        category=UserNotification.Category.DISPUTE,
        action_url=_issue_action_url(project.pk, issue.pk),
        is_pinned_pending=True,
    ).update(is_pinned_pending=False)


def _unpin_request_notifications(project: Project, job: Job, created_by_ids: set[int]) -> None:
    pm_ids = {pm.pk for pm in _project_pms(project)}
    unpin_recipients = pm_ids | created_by_ids
    if not unpin_recipients:
        return
    UserNotification.objects.filter(
        recipient_id__in=unpin_recipients,
        project=project,
        job=job,
        category=UserNotification.Category.DISPUTE,
        action_url=_request_action_url(project.pk),
        is_pinned_pending=True,
    ).update(is_pinned_pending=False)


def _notify_ruling_parties(
    project: Project,
    job: Job,
    issue: JobIssue,
    *,
    actor: User,
    title: str,
    body: str,
) -> None:
    action_url = _issue_action_url(project.pk, issue.pk)
    if (
        job.annotator is not None
        and job.annotator.is_active
        and job.annotator_id != actor.pk
        and job.annotator.notify_request_updates
    ):
        UserNotification.objects.create(
            recipient=job.annotator,
            project=project,
            job=job,
            category=UserNotification.Category.DISPUTE,
            title=title[:200],
            body=body,
            action_url=action_url,
        )
    if (
        job.qc1_reviewer is not None
        and job.qc1_reviewer.is_active
        and job.qc1_reviewer_id != actor.pk
        and job.qc1_reviewer_id != job.annotator_id
    ):
        UserNotification.objects.create(
            recipient=job.qc1_reviewer,
            project=project,
            job=job,
            category=UserNotification.Category.DISPUTE,
            title=title[:200],
            body=body,
            action_url=action_url,
        )


def _call_issue_fetcher(
    fn: Any,
    cvat_job_id: int,
    *,
    timeout: float | None,
    max_duration_seconds: float | None,
) -> Any:
    kwargs: dict[str, Any] = {}
    if timeout is not None or max_duration_seconds is not None:
        try:
            sig = inspect.signature(fn)
            has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            if timeout is not None and (has_var_kw or "timeout" in sig.parameters):
                kwargs["timeout"] = timeout
            if max_duration_seconds is not None and (has_var_kw or "max_duration_seconds" in sig.parameters):
                kwargs["max_duration_seconds"] = max_duration_seconds
        except (TypeError, ValueError):
            pass
    return fn(cvat_job_id, **kwargs)


def fetch_cvat_issue_snapshot(
    cvat_job_id: int,
    client: Any,
    *,
    timeout: float | None = None,
    max_duration_seconds: float | None = None,
) -> CvatIssueSnapshot:
    """Fetch and strictly validate CVAT issues + comments outside any DB transaction."""
    fetched_at = timezone.now()
    raw_issues = _call_issue_fetcher(
        client.list_job_issues,
        cvat_job_id,
        timeout=timeout,
        max_duration_seconds=max_duration_seconds,
    )
    if not isinstance(raw_issues, list):
        raise CvatError(f"CVAT trả danh sách issue không hợp lệ cho job {cvat_job_id}.")

    deduped_issues: dict[int, CvatIssuePayload] = {}
    for raw in raw_issues:
        parsed = _validate_model(CvatIssuePayload, raw, f"issues(job={cvat_job_id})")
        if parsed.job != cvat_job_id:
            raise CvatError(f"CVAT trả issue #{parsed.id} thuộc job {parsed.job}, không khớp job {cvat_job_id}.")
        deduped_issues[parsed.id] = parsed
    issues = [deduped_issues[k] for k in sorted(deduped_issues)]

    comments: list[CvatCommentPayload] = []
    if issues:
        raw_comments = _call_issue_fetcher(
            client.list_job_comments,
            cvat_job_id,
            timeout=timeout,
            max_duration_seconds=max_duration_seconds,
        )
        if not isinstance(raw_comments, list):
            raise CvatError(f"CVAT trả danh sách comment không hợp lệ cho job {cvat_job_id}.")
        deduped_comments: dict[int, CvatCommentPayload] = {}
        for raw in raw_comments:
            parsed_comment = _validate_model(CvatCommentPayload, raw, f"comments(job={cvat_job_id})")
            deduped_comments[parsed_comment.id] = parsed_comment
        comments = [deduped_comments[k] for k in sorted(deduped_comments)]

    return CvatIssueSnapshot(fetched_at=fetched_at, issues=issues, comments=comments)


def is_authorized_qc_actor(
    job: Job,
    project: Project,
    user: User | None,
    stage_history: tuple[set[int], set[int], set[int]] | None = None,
) -> bool:
    if user is None or not user.is_active:
        return False
    ann_ids, qc1_ids, qc2_ids = stage_history if stage_history is not None else get_stage_history(job)
    roles = _user_roles(project, user)
    if Role.QC2 in roles and user.pk not in (ann_ids | qc1_ids):
        return True
    return bool(Role.QC1 in roles and user.pk not in (ann_ids | qc2_ids))


def _evaluate_issue_authority(
    job: Job,
    project: Project,
    owner_cvat_id: int | None,
    *,
    is_clarification: bool,
    cvat_user_map: dict[int, User],
    stage_history: tuple[set[int], set[int], set[int]],
) -> tuple[User | None, str, str]:
    if owner_cvat_id is None or owner_cvat_id not in cvat_user_map:
        return None, JobIssue.AuthorStage.NONE, JobIssue.AuthorityStatus.REJECTED_AUTHOR
    user = cvat_user_map[owner_cvat_id]
    if not user.is_active:
        return user, JobIssue.AuthorStage.NONE, JobIssue.AuthorityStatus.REJECTED_AUTHOR

    ann_ids, qc1_ids, qc2_ids = stage_history
    roles = _user_roles(project, user)
    if is_clarification and (user.pk in ann_ids or user.pk == job.annotator_id):
        return user, JobIssue.AuthorStage.ANNOTATOR, JobIssue.AuthorityStatus.VALID
    if (
        Role.QC2 in roles
        and user.pk not in (ann_ids | qc1_ids)
        and (job.status in (JobStatus.PENDING_QC2, JobStatus.APPROVED, JobStatus.DELIVERED) or Role.QC1 not in roles)
    ):
        return user, JobIssue.AuthorStage.QC2, JobIssue.AuthorityStatus.VALID
    if Role.QC1 in roles and user.pk not in (ann_ids | qc2_ids) and job.qc1_reviewer_id in (None, user.pk):
        return user, JobIssue.AuthorStage.QC1, JobIssue.AuthorityStatus.VALID
    return user, JobIssue.AuthorStage.NONE, JobIssue.AuthorityStatus.REJECTED_AUTHOR


def _create_or_link_dispute_request(
    *,
    project: Project,
    job: Job,
    issue: JobIssue,
    actor: User,
    reason: str,
    source: str,
    idempotent: bool,
) -> AnnotatorRequest:
    """Create or link an AnnotatorRequest(error_dispute) for a JobIssue in canonical lock order."""
    clean_reason = reason.strip()
    errs = list(
        ReviewError.objects.select_for_update(of=("self",))
        .filter(job=job, job_issue=issue, is_voided=False)
        .order_by("id")
    )
    latest_err = errs[-1] if errs else None
    pending_reqs = list(
        AnnotatorRequest.objects.select_for_update(of=("self",))
        .filter(
            project=project,
            job=job,
            job_issue=issue,
            request_type=AnnotatorRequest.RequestType.ERROR_DISPUTE,
            status=AnnotatorRequest.Status.PENDING_PM,
        )
        .order_by("id")
    )
    if pending_reqs:
        if idempotent:
            issue.is_disputed = True
            issue.dispute_reason = clean_reason
            if issue.status in (JobIssue.Status.OPEN, JobIssue.Status.REOPENED, JobIssue.Status.ADDRESSED):
                issue.status = JobIssue.Status.UNCLEAR
            return pending_reqs[0]
        raise ValidationError("Đã có yêu cầu phản hồi đang chờ PM xử lý cho issue này.")

    issue.is_disputed = True
    issue.dispute_reason = clean_reason
    if issue.status in (JobIssue.Status.OPEN, JobIssue.Status.REOPENED, JobIssue.Status.ADDRESSED):
        issue.status = JobIssue.Status.UNCLEAR

    pms = _project_pms(project)
    handler = pms[0] if pms else None
    title = f"Phản hồi issue #{issue.cvat_issue_id} · {job.name}"[:255]
    req = AnnotatorRequest.objects.create(
        project=project,
        job=job,
        review_error=latest_err,
        job_issue=issue,
        request_type=AnnotatorRequest.RequestType.ERROR_DISPUTE,
        status=AnnotatorRequest.Status.PENDING_PM,
        title=title,
        reason=clean_reason,
        progress_note="PM đang đối chiếu issue được phản hồi.",
        created_by=actor,
        handler=handler,
        handler_role="PM",
    )
    ActivityLog.record(
        project=project,
        actor=actor,
        action="issue.dispute",
        target=job,
        job=job,
        after={
            "job_issue_id": issue.pk,
            "cvat_issue_id": issue.cvat_issue_id,
            "request_id": req.pk,
            "source": source,
        },
        note=clean_reason,
    )
    if actor.notify_request_updates:
        handler_name = handler.get_full_name() or handler.username if handler else "PM"
        UserNotification.objects.create(
            recipient=actor,
            project=project,
            job=job,
            category=UserNotification.Category.DISPUTE,
            title=f"PM đã nhận phản hồi lỗi #{issue.cvat_issue_id}",
            body=f"{handler_name} đang xem yêu cầu '{req.title}' trên {job.name}.",
            action_url=_request_action_url(project.pk),
            is_pinned_pending=True,
        )
    for pm in pms:
        if pm.pk != actor.pk and pm.notify_request_updates:
            UserNotification.objects.create(
                recipient=pm,
                project=project,
                job=job,
                category=UserNotification.Category.DISPUTE,
                title=f"Phản hồi issue #{issue.cvat_issue_id} · {job.name}",
                body=clean_reason,
                action_url=_request_action_url(project.pk),
                is_pinned_pending=True,
            )
    return req


def upsert_job_issues(
    job_id: int,
    project: Project,
    snapshot: CvatIssueSnapshot,
    *,
    locked_job: Job | None = None,
) -> dict[str, Any]:
    """Upsert CVAT issue snapshot for one job under canonical locks (Job -> JobIssue -> children)."""
    job = locked_job if locked_job is not None else _lock_job(project, job_id)
    existing_issues = list(
        JobIssue.objects.select_for_update(of=("self",))
        .filter(job=job)
        .order_by("id")
    )
    by_cvat_id: dict[int, JobIssue] = {ji.cvat_issue_id: ji for ji in existing_issues}

    comments_by_issue: dict[int, list[CvatCommentPayload]] = defaultdict(list)
    for comment in snapshot.comments:
        comments_by_issue[comment.issue].append(comment)

    cvat_user_map: dict[int, User] = {
        acc.cvat_user_id: acc.user for acc in CvatAccount.objects.select_related("user")
    }
    ann_ids, qc1_ids, qc2_ids = get_stage_history(job)
    stage_history = (ann_ids, qc1_ids, qc2_ids)

    seen_cvat_ids: set[int] = set()
    created_count = 0
    updated_count = 0

    for ci in snapshot.issues:
        c_list = comments_by_issue.get(ci.id, [])
        first_c = c_list[0] if c_list else None
        first_msg = first_c.message if first_c else ""
        env = parse_envelope(first_msg)
        fp = hashlib.sha256("|".join(f"{c.id}:{c.message}" for c in c_list).encode("utf-8")).hexdigest()[:32]

        existing = by_cvat_id.get(ci.id)
        is_new = existing is None
        if existing is None:
            if should_skip_preqc(env):
                continue
            pos, tid, sid = decode_3d_position(ci.position)
            is_clar = env["eff_code"] in ("CLS-UNK", "CLS-UNCL")
            owner_cvat_id = ci.owner.id if ci.owner else None
            author_user, author_stage, auth_status = _evaluate_issue_authority(
                job,
                project,
                owner_cvat_id,
                is_clarification=is_clar,
                cvat_user_map=cvat_user_map,
                stage_history=stage_history,
            )
            init_status = (
                JobIssue.Status.UNCLEAR
                if (is_clar and auth_status == JobIssue.AuthorityStatus.VALID)
                else JobIssue.Status.OPEN
            )
            frames_span = env["frames_span"]
            existing = JobIssue.objects.create(
                project=project,
                job=job,
                cvat_issue_id=ci.id,
                first_comment_id=first_c.id if first_c else None,
                defect_code=env["eff_code"],
                primary_category=env["primary_category"],
                severity=env["severity"],
                source=JobIssue.Source.CLARIFICATION if is_clar else JobIssue.Source.MANUAL,
                is_clarification=is_clar,
                frame_number=ci.frame,
                frame_start=frames_span[0] if frames_span else None,
                frame_end=frames_span[1] if frames_span else None,
                track_id=tid,
                shape_id=sid,
                position=pos,
                message=env["clean_message"],
                author=author_user,
                author_cvat_id=owner_cvat_id,
                author_stage=author_stage,
                authority_status=auth_status,
                status=init_status,
                cvat_resolved=ci.resolved,
                cvat_last_comment_id=c_list[-1].id if c_list else 0,
                cvat_comments_fingerprint=fp,
                cvat_synced_at=snapshot.fetched_at,
            )
            by_cvat_id[ci.id] = existing
            existing_issues.append(existing)
            created_count += 1
            if auth_status == JobIssue.AuthorityStatus.VALID and author_user is not None:
                if author_stage == JobIssue.AuthorStage.QC1:
                    qc1_ids.add(author_user.pk)
                elif author_stage == JobIssue.AuthorStage.QC2:
                    qc2_ids.add(author_user.pk)
            if init_status == JobIssue.Status.UNCLEAR:
                _pin_pm_issue_notification(
                    project,
                    job,
                    existing,
                    title=f"Yêu cầu làm rõ nhãn ({env['eff_code']}) · {job.name}",
                    body=env["clean_message"] or f"Issue #{ci.id} tại frame {ci.frame} cần PM phán quyết.",
                )
        else:
            if existing.cvat_synced_at is not None and existing.cvat_synced_at > snapshot.fetched_at:
                seen_cvat_ids.add(ci.id)
                continue
            if existing.first_comment_id is None and first_c is not None:
                # One-time initial envelope lock when issue was first imported before its opening comment existed.
                existing.first_comment_id = first_c.id
                if should_skip_preqc(env):
                    existing.authority_status = JobIssue.AuthorityStatus.REJECTED_AUTHOR
                else:
                    is_clar_new = env["eff_code"] in ("CLS-UNK", "CLS-UNCL")
                    frames_span = env["frames_span"]
                    existing.defect_code = env["eff_code"]
                    existing.primary_category = env["primary_category"]
                    existing.severity = env["severity"]
                    existing.message = env["clean_message"]
                    existing.frame_start = frames_span[0] if frames_span else None
                    existing.frame_end = frames_span[1] if frames_span else None
                    if is_clar_new and not existing.is_clarification:
                        owner_cvat_id = ci.owner.id if ci.owner else existing.author_cvat_id
                        author_user, author_stage, auth_status = _evaluate_issue_authority(
                            job,
                            project,
                            owner_cvat_id,
                            is_clarification=True,
                            cvat_user_map=cvat_user_map,
                            stage_history=stage_history,
                        )
                        existing.is_clarification = True
                        existing.source = JobIssue.Source.CLARIFICATION
                        existing.author = author_user
                        existing.author_stage = author_stage
                        existing.authority_status = auth_status
                        if auth_status == JobIssue.AuthorityStatus.VALID and existing.status == JobIssue.Status.OPEN:
                            existing.status = JobIssue.Status.UNCLEAR
                            _pin_pm_issue_notification(
                                project,
                                job,
                                existing,
                                title=f"Yêu cầu làm rõ nhãn ({env['eff_code']}) · {job.name}",
                                body=env["clean_message"] or f"Issue #{ci.id} tại frame {ci.frame} cần PM phán quyết.",
                            )
            elif existing.authority_status == JobIssue.AuthorityStatus.VALID:
                if existing.first_comment_id is not None and (first_c is None or first_c.id != existing.first_comment_id):
                    existing.tampered = True
                    existing.tamper_reason = "first_comment_deleted"
                elif should_skip_preqc(env):
                    existing.tampered = True
                    existing.tamper_reason = "preqc_ref_injected"
                elif SEV_RANK[env["severity"]] < SEV_RANK[existing.severity] or (
                    existing.defect_code and env["eff_code"] != existing.defect_code
                ):
                    existing.tampered = True
                    existing.tamper_reason = "envelope_downgraded"
                try:
                    _, new_tid, new_sid = decode_3d_position(ci.position)
                    if (existing.track_id is not None or existing.shape_id is not None) and (
                        new_tid is None and new_sid is None
                    ):
                        existing.tampered = True
                        existing.tamper_reason = "position_3d_wiped"
                    elif (existing.track_id is not None and new_tid != existing.track_id) or (
                        existing.shape_id is not None and new_sid != existing.shape_id
                    ):
                        existing.tampered = True
                        existing.tamper_reason = "position_3d_swapped"
                except ValueError:
                    existing.tampered = True
                    existing.tamper_reason = "invalid_position"
            existing.source_missing = False
            existing.cvat_resolved = ci.resolved
            existing.cvat_comments_fingerprint = fp
            existing.cvat_synced_at = snapshot.fetched_at
            updated_count += 1

        seen_cvat_ids.add(ci.id)

        if existing.authority_status == JobIssue.AuthorityStatus.VALID:
            floor_id = max(existing.last_applied_lifecycle_comment_id, existing.reopened_after_comment_id)
            lifecycle_dirty = False
            for comment in c_list:
                if existing.first_comment_id is not None and comment.id == existing.first_comment_id:
                    continue
                if comment.id <= floor_id:
                    continue
                msg = comment.message.lstrip()
                c_user = cvat_user_map.get(comment.owner.id) if comment.owner is not None else None
                c_uid = c_user.pk if (c_user is not None and c_user.is_active) else None

                if (
                    msg.startswith("[ADDRESSED]")
                    and c_user is not None
                    and c_uid is not None
                    and (c_uid == job.annotator_id or c_uid in ann_ids)
                    and not (existing.is_clarification and existing.ruled_at is None)
                ):
                    rest = msg[len("[ADDRESSED]") :].strip()
                    has_dispute = bool(DISPUTE_WORD_RE.search(rest))
                    if existing.status in (JobIssue.Status.OPEN, JobIssue.Status.REOPENED):
                        prev_st = existing.status
                        existing.status = JobIssue.Status.ADDRESSED
                        existing.last_applied_lifecycle_comment_id = comment.id
                        lifecycle_dirty = True
                        ActivityLog.record(
                            project=project,
                            actor=c_user,
                            action="issue.address",
                            target=job,
                            job=job,
                            before={"status": prev_st},
                            after={
                                "job_issue_id": existing.pk,
                                "cvat_issue_id": existing.cvat_issue_id,
                                "status": existing.status,
                                "comment_id": comment.id,
                                "source": "cvat_comment",
                            },
                        )
                        if has_dispute:
                            _create_or_link_dispute_request(
                                project=project,
                                job=job,
                                issue=existing,
                                actor=c_user,
                                reason=rest or "Phản hồi từ CVAT",
                                source="cvat_comment",
                                idempotent=True,
                            )
                    elif existing.status == JobIssue.Status.ADDRESSED and has_dispute:
                        existing.last_applied_lifecycle_comment_id = comment.id
                        lifecycle_dirty = True
                        _create_or_link_dispute_request(
                            project=project,
                            job=job,
                            issue=existing,
                            actor=c_user,
                            reason=rest or "Phản hồi từ CVAT",
                            source="cvat_comment",
                            idempotent=True,
                        )
                elif (
                    msg.startswith("[UNCLEAR]")
                    and c_user is not None
                    and c_uid is not None
                    and (
                        c_uid == job.annotator_id
                        or _can_actor_apply_qc_comment(
                            job, project, c_user, issue=existing, stage_history=stage_history, is_resolve=False
                        )
                    )
                    and existing.status not in (JobIssue.Status.NOT_AN_ISSUE, JobIssue.Status.RESOLVED)
                ):
                    existing.status = JobIssue.Status.UNCLEAR
                    existing.last_applied_lifecycle_comment_id = comment.id
                    lifecycle_dirty = True
                    _pin_pm_issue_notification(
                        project,
                        job,
                        existing,
                        title=f"Issue #{existing.cvat_issue_id} cần làm rõ · {job.name}",
                        body=msg[len("[UNCLEAR]") :].strip() or existing.message,
                    )
                elif (
                    msg.startswith("[REOPENED]")
                    and c_user is not None
                    and not (existing.is_clarification and existing.ruled_at is None)
                    and _can_actor_apply_qc_comment(
                        job, project, c_user, issue=existing, stage_history=stage_history, is_resolve=False
                    )
                ):
                    if existing.status == JobIssue.Status.NOT_AN_ISSUE:
                        existing.cvat_reopen_drift = True
                    else:
                        existing.status = JobIssue.Status.REOPENED
                        existing.reopened_after_comment_id = max(existing.reopened_after_comment_id, comment.id)
                    existing.last_applied_lifecycle_comment_id = comment.id
                    lifecycle_dirty = True
                elif (
                    msg.startswith(("[RESOLVED]", "[QC-FIXED]"))
                    and c_user is not None
                    and _can_actor_apply_qc_comment(
                        job, project, c_user, issue=existing, stage_history=stage_history, is_resolve=True
                    )
                    and existing.status != JobIssue.Status.NOT_AN_ISSUE
                ):
                    prev_st = existing.status
                    existing.status = JobIssue.Status.RESOLVED
                    existing.last_applied_lifecycle_comment_id = comment.id
                    lifecycle_dirty = True
                    _unpin_issue_notifications(project, job, existing)
                    ActivityLog.record(
                        project=project,
                        actor=c_user,
                        action="issue.resolve",
                        target=job,
                        job=job,
                        before={"status": prev_st},
                        after={
                            "job_issue_id": existing.pk,
                            "cvat_issue_id": existing.cvat_issue_id,
                            "status": existing.status,
                            "comment_id": comment.id,
                            "source": "cvat_comment",
                        },
                    )

            if c_list and c_list[-1].id > existing.cvat_last_comment_id:
                existing.cvat_last_comment_id = c_list[-1].id
                lifecycle_dirty = True
        else:
            lifecycle_dirty = False

        if not is_new or lifecycle_dirty:
            existing.save()

    for ji in existing_issues:
        if (
            ji.cvat_issue_id not in seen_cvat_ids
            and ji.created_at < snapshot.fetched_at
            and (ji.cvat_synced_at is None or ji.cvat_synced_at < snapshot.fetched_at)
            and not ji.source_missing
        ):
            ji.source_missing = True
            ji.save(update_fields=["source_missing", "updated_at"])
            _unpin_issue_notifications(project, job, ji)

    issues = list(
        JobIssue.objects.filter(job=job)
        .select_related("job", "author", "ruled_by")
        .order_by("-created_at", "-id")
    )
    return {
        "job": job.pk,
        "created": created_count,
        "updated": updated_count,
        "total": len(issues),
        "issues": issues,
    }


def import_job_issues(
    job_id: int,
    *,
    project: Project,
    client: Any = None,
    prefetched: CvatIssueSnapshot | None = None,
    timeout: float | None = None,
    max_duration_seconds: float | None = None,
    fail_on_lock_busy: bool = True,
) -> dict[str, Any]:
    """Fetch CVAT issues outside DB transaction under per-job advisory lock, then upsert atomically."""
    if prefetched is not None:
        with transaction.atomic():
            return upsert_job_issues(job_id, project, prefetched)

    job_meta = (
        Job.objects.filter(pk=job_id, project=project)
        .values("id", "cvat_job_id")
        .first()
    )
    if job_meta is None:
        raise NotFound("Không tìm thấy job trong organization.")
    cvat_job_id = job_meta["cvat_job_id"]
    if cvat_job_id is None:
        raise ValidationError("Job này chưa liên kết với CVAT.")

    if not _try_advisory_lock(_ISSUE_IMPORT_LOCK_NS, job_id):
        if fail_on_lock_busy:
            raise ValidationError({"detail": "Đang đồng bộ issue từ CVAT cho job này, vui lòng thử lại."})
        raise CvatError("Issue import advisory lock busy.")

    owned_client: Any = None
    try:
        if client is None:
            owned_client = CvatClient(organization=project.cvat_org_slug or None)
            active_client = owned_client
        else:
            active_client = client
        snapshot = fetch_cvat_issue_snapshot(
            cvat_job_id,
            active_client,
            timeout=timeout,
            max_duration_seconds=max_duration_seconds,
        )
        with transaction.atomic():
            return upsert_job_issues(job_id, project, snapshot)
    finally:
        if owned_client is not None:
            _close_quietly(owned_client)
        _release_advisory_lock(_ISSUE_IMPORT_LOCK_NS, job_id)


def submit_blocking_issues(job: Job) -> list[JobIssue]:
    """Submit Gate: blocks open/reopened major/critical/ruled issues; allows unclear holds."""
    if not job.project.issue_gate_enabled:
        return []
    return list(
        JobIssue.objects.filter(
            job=job,
            authority_status=JobIssue.AuthorityStatus.VALID,
            source_missing=False,
            status__in=[JobIssue.Status.OPEN, JobIssue.Status.REOPENED],
        )
        .filter(Q(severity__in=_BLOCKING_SEVERITIES) | Q(ruled_at__isnull=False))
        .order_by("id")
    )


def _acceptance_blocking_q() -> Q:
    return Q(status=JobIssue.Status.UNCLEAR) | (
        Q(status__in=[JobIssue.Status.OPEN, JobIssue.Status.REOPENED, JobIssue.Status.ADDRESSED])
        & (Q(severity__in=_BLOCKING_SEVERITIES) | Q(ruled_at__isnull=False))
    )


def acceptance_blocking_issues(job: Job) -> list[JobIssue]:
    """Acceptance Gate: blocks unclear holds and unverified open/reopened/addressed blockers."""
    if not job.project.issue_gate_enabled:
        return []
    return list(
        JobIssue.objects.filter(
            job=job,
            authority_status=JobIssue.AuthorityStatus.VALID,
            source_missing=False,
        )
        .filter(_acceptance_blocking_q())
        .order_by("id")
    )


def acceptance_blocking_issues_for_jobs(project: Project, jobs: list[Job]) -> list[JobIssue]:
    if not project.issue_gate_enabled or not jobs:
        return []
    return list(
        JobIssue.objects.filter(
            project=project,
            job_id__in=[j.pk for j in jobs],
            authority_status=JobIssue.AuthorityStatus.VALID,
            source_missing=False,
        )
        .filter(_acceptance_blocking_q())
        .order_by("id")
    )


def acceptance_blocking_batch_ids(project: Project) -> set[int]:
    if not project.issue_gate_enabled:
        return set()
    return set(
        JobIssue.objects.filter(
            project=project,
            authority_status=JobIssue.AuthorityStatus.VALID,
            source_missing=False,
        )
        .filter(_acceptance_blocking_q())
        .values_list("job__batch_id", flat=True)
        .distinct()
    )


def _lock_job_and_issue(project: Project, issue_id: int) -> tuple[Job, JobIssue]:
    job_id = JobIssue.objects.filter(pk=issue_id, project=project).values_list("job_id", flat=True).first()
    if job_id is None:
        raise NotFound("Không tìm thấy issue trong organization.")
    job = _lock_job(project, job_id)
    issue = (
        JobIssue.objects.select_for_update(of=("self",))
        .select_related("author", "ruled_by")
        .filter(pk=issue_id, project=project, job=job)
        .first()
    )
    if issue is None:
        raise NotFound("Không tìm thấy issue trong organization.")
    return job, issue


def _check_qc_issue_action_access(
    job: Job,
    project: Project,
    actor: User,
    *,
    issue: JobIssue,
    can_manage_jobs: bool,
    can_audit: bool,
    stage_history: tuple[set[int], set[int], set[int]] | None = None,
) -> None:
    history = stage_history if stage_history is not None else get_stage_history(job)
    ann_ids, qc1_ids, qc2_ids = history
    if not is_authorized_qc_actor(job, project, actor, history):
        raise PermissionDenied("Luật bốn mắt / phân quyền: bạn không được xử lý issue trên job này.")
    if can_manage_jobs:
        return

    roles = _user_roles(project, actor)
    can_act_qc2 = can_audit and actor.pk not in (ann_ids | qc1_ids)
    if can_act_qc2:
        has_assigned_qc2 = AuditSample.objects.filter(
            job=job,
            auditor=actor,
            result=AuditSample.Result.PENDING,
        ).exists()
        if has_assigned_qc2 or issue.author_id == actor.pk:
            return
        if not (Role.QC1 in roles and actor.pk not in (ann_ids | qc2_ids)):
            raise PermissionDenied("Bạn không được phân công QC2 cho job này hoặc không phải người tạo issue.")

    # QC1-only actor (or dual QC1+QC2 acting in QC1 capacity)
    if job.status in (JobStatus.PENDING_QC2, JobStatus.APPROVED):
        raise PermissionDenied("Job đang ở giai đoạn QC2/Đã duyệt — QC1 không thể thay đổi issue.")
    if job.qc1_reviewer_id and job.qc1_reviewer_id != actor.pk:
        raise PermissionDenied("Job này đã được giao cho người QC1 khác.")
    if not job.qc1_reviewer_id and job.batch.team_id:
        t_ids = list(TeamMember.objects.filter(user=actor, team__project=project).values_list("team_id", flat=True))
        if job.batch.team_id not in t_ids:
            raise PermissionDenied("Job thuộc batch của team khác — bạn không thể thao tác.")


def _can_actor_apply_qc_comment(
    job: Job,
    project: Project,
    actor: User | None,
    *,
    issue: JobIssue,
    stage_history: tuple[set[int], set[int], set[int]],
    is_resolve: bool,
) -> bool:
    if actor is None or not actor.is_active:
        return False
    roles = _user_roles(project, actor)
    can_manage_jobs = Role.PROJECT_MANAGER in roles
    can_audit = Role.QC2 in roles
    if is_resolve and issue.is_clarification and issue.ruled_at is None and not can_manage_jobs:
        return False
    if not can_manage_jobs and job.is_escalated and project.escalation_policy == EscalationPolicy.BLOCK:
        return False
    try:
        _check_qc_issue_action_access(
            job,
            project,
            actor,
            issue=issue,
            can_manage_jobs=can_manage_jobs,
            can_audit=can_audit,
            stage_history=stage_history,
        )
    except PermissionDenied:
        return False
    return True


def address_job_issue(project: Project, issue_id: int, *, actor: User, note: str = "") -> JobIssue:
    with transaction.atomic():
        job, issue = _lock_job_and_issue(project, issue_id)
        if job.annotator_id != actor.pk:
            raise PermissionDenied("Bạn chỉ có thể đánh dấu đã sửa issue trên job được giao cho mình.")
        _ensure_editable(job)
        _ensure_not_escalated(job)
        if job.status not in ACTIVE_ANNOTATOR_STATUSES:
            raise ValidationError("Chỉ đánh dấu đã sửa khi job đang ở giai đoạn Annotator.")
        if issue.authority_status != JobIssue.AuthorityStatus.VALID:
            raise ValidationError("Issue này không hợp lệ.")
        if issue.is_clarification and issue.ruled_at is None:
            raise ValidationError("Không thể tự xác nhận sửa issue làm rõ (CLS-UNK/CLS-UNCL) trước khi PM phán quyết.")
        if issue.status not in (JobIssue.Status.OPEN, JobIssue.Status.REOPENED):
            raise ValidationError(f"Không thể đánh dấu đã sửa issue đang ở trạng thái {issue.get_status_display()}.")

        prev_status = issue.status
        issue.status = JobIssue.Status.ADDRESSED
        issue.save(update_fields=["status", "updated_at"])
        ActivityLog.record(
            project=project,
            actor=actor,
            action="issue.address",
            target=job,
            job=job,
            before={"status": prev_status},
            after={
                "job_issue_id": issue.pk,
                "cvat_issue_id": issue.cvat_issue_id,
                "status": issue.status,
            },
            note=note,
        )
        return issue


def dispute_job_issue(
    project: Project,
    issue_id: int,
    *,
    actor: User,
    reason: str,
) -> tuple[JobIssue, AnnotatorRequest]:
    with transaction.atomic():
        job, issue = _lock_job_and_issue(project, issue_id)
        if job.annotator_id != actor.pk:
            raise PermissionDenied("Bạn chỉ có thể phản hồi issue trên job được giao cho mình.")
        if job.status in (JobStatus.APPROVED, JobStatus.DELIVERED):
            raise ValidationError("Không thể gửi phản hồi trên job đã duyệt hoặc đã bàn giao.")
        if job.is_locked or job.batch.status != DataStatus.ACTIVE or job.dataset.status != DataStatus.ACTIVE:
            raise ValidationError("Job, Task hoặc Project đang bị khoá.")
        if issue.authority_status != JobIssue.AuthorityStatus.VALID:
            raise ValidationError("Issue này không hợp lệ.")
        if issue.status not in (JobIssue.Status.OPEN, JobIssue.Status.REOPENED, JobIssue.Status.ADDRESSED):
            raise ValidationError(f"Không thể phản hồi issue đang ở trạng thái {issue.get_status_display()}.")

        req = _create_or_link_dispute_request(
            project=project,
            job=job,
            issue=issue,
            actor=actor,
            reason=reason,
            source="api",
            idempotent=False,
        )
        issue.save(update_fields=["is_disputed", "dispute_reason", "status", "updated_at"])
        return issue, req


def resolve_job_issue(
    project: Project,
    issue_id: int,
    *,
    actor: User,
    note: str = "",
    can_manage_jobs: bool = False,
    can_audit: bool = False,
) -> JobIssue:
    with transaction.atomic():
        job, issue = _lock_job_and_issue(project, issue_id)
        _ensure_editable(job)
        if not can_manage_jobs:
            _ensure_not_escalated(job)
        _check_qc_issue_action_access(
            job,
            project,
            actor,
            issue=issue,
            can_manage_jobs=can_manage_jobs,
            can_audit=can_audit,
        )
        if issue.authority_status != JobIssue.AuthorityStatus.VALID:
            raise ValidationError("Issue này không hợp lệ.")
        if issue.status == JobIssue.Status.NOT_AN_ISSUE:
            raise ValidationError("Issue đã được PM chốt không phải lỗi (not_an_issue).")
        if issue.is_clarification and issue.ruled_at is None and not can_manage_jobs:
            raise ValidationError("Issue làm rõ (CLS-UNK/CLS-UNCL) cần PM phán quyết trước khi đóng.")

        prev_status = issue.status
        issue.status = JobIssue.Status.RESOLVED
        issue.save(update_fields=["status", "updated_at"])
        _unpin_issue_notifications(project, job, issue)
        ActivityLog.record(
            project=project,
            actor=actor,
            action="issue.resolve",
            target=job,
            job=job,
            before={"status": prev_status},
            after={
                "job_issue_id": issue.pk,
                "cvat_issue_id": issue.cvat_issue_id,
                "status": issue.status,
            },
            note=note,
        )
        return issue


def reopen_job_issue(
    project: Project,
    issue_id: int,
    *,
    actor: User,
    note: str = "",
    can_manage_jobs: bool = False,
    can_audit: bool = False,
) -> JobIssue:
    with transaction.atomic():
        job, issue = _lock_job_and_issue(project, issue_id)
        _ensure_editable(job)
        if not can_manage_jobs:
            _ensure_not_escalated(job)
        _check_qc_issue_action_access(
            job,
            project,
            actor,
            issue=issue,
            can_manage_jobs=can_manage_jobs,
            can_audit=can_audit,
        )
        if issue.authority_status != JobIssue.AuthorityStatus.VALID:
            raise ValidationError("Issue này không hợp lệ.")
        if issue.status == JobIssue.Status.NOT_AN_ISSUE:
            raise ValidationError("Issue đã được PM chốt không phải lỗi (not_an_issue).")
        if issue.is_clarification and issue.ruled_at is None:
            raise ValidationError("Issue làm rõ (CLS-UNK/CLS-UNCL) đang chờ PM phán quyết, không thể mở lại.")

        prev_status = issue.status
        issue.status = JobIssue.Status.REOPENED
        issue.reopened_after_comment_id = max(issue.reopened_after_comment_id, issue.cvat_last_comment_id)
        issue.save(update_fields=["status", "reopened_after_comment_id", "updated_at"])
        ActivityLog.record(
            project=project,
            actor=actor,
            action="issue.reopen",
            target=job,
            job=job,
            before={"status": prev_status},
            after={
                "job_issue_id": issue.pk,
                "cvat_issue_id": issue.cvat_issue_id,
                "status": issue.status,
                "reopened_after_comment_id": issue.reopened_after_comment_id,
            },
            note=note,
        )
        return issue


def _finalize_linked_requests(
    *,
    project: Project,
    job: Job,
    pending_reqs: list[AnnotatorRequest],
    actor: User,
    new_status: str,
    progress_note: str,
    resolution_note: str,
    voided_error_ids: list[int],
    now: datetime,
) -> None:
    if not pending_reqs:
        return
    for req in pending_reqs:
        before_status = req.status
        req.status = new_status
        if progress_note:
            req.progress_note = progress_note
        if resolution_note:
            req.resolution_note = resolution_note
        req.handler = actor
        req.handler_role = "PM"
        req.resolved_at = now
        req.save(
            update_fields=[
                "status",
                "progress_note",
                "resolution_note",
                "handler",
                "handler_role",
                "resolved_at",
                "updated_at",
            ]
        )
        if req.created_by.notify_request_updates:
            UserNotification.objects.create(
                recipient=req.created_by,
                project=project,
                job=job,
                category=UserNotification.Category.DISPUTE,
                title=f"{req.get_status_display()} · {job.name}",
                body=req.resolution_note or req.title,
                action_url=_request_action_url(project.pk),
            )
        ActivityLog.record(
            project=project,
            actor=actor,
            action="annotator.request_resolve",
            target=job,
            job=job,
            before={"request_id": req.pk, "status": before_status},
            after={
                "request_id": req.pk,
                "status": new_status,
                "voided_error_id": voided_error_ids[0] if voided_error_ids else None,
                "voided_error_ids": voided_error_ids,
            },
            note=req.resolution_note or req.progress_note,
        )
    _unpin_request_notifications(project, job, {req.created_by_id for req in pending_reqs})


def _apply_pm_issue_ruling_locked(
    *,
    project: Project,
    job: Job,
    issue: JobIssue,
    actor: User,
    decision: str,
    ruling_label: str,
    ruling_attributes: dict[str, Any],
    ruling_note: str,
    dispute_outcome: str | None,
    pending_reqs: list[AnnotatorRequest],
    errors: list[ReviewError],
) -> JobIssue:
    _ensure_not_delivered(job)
    if issue.authority_status != JobIssue.AuthorityStatus.VALID:
        raise ValidationError("Issue này không hợp lệ.")
    if decision == "ruling" and issue.status not in (
        JobIssue.Status.UNCLEAR,
        JobIssue.Status.OPEN,
        JobIssue.Status.REOPENED,
    ):
        raise ValidationError(f"Không thể đặt phán quyết nhãn cho issue ở trạng thái {issue.get_status_display()}.")
    if decision == "resolved" and issue.status == JobIssue.Status.NOT_AN_ISSUE:
        raise ValidationError("Issue đã được phán quyết không phải lỗi (not_an_issue).")
    if decision == "not_an_issue":
        ann_ids, _, _ = get_stage_history(job)
        if actor.pk in ann_ids:
            raise PermissionDenied("Luật bốn mắt: không thể tự hủy (not_an_issue) lỗi trên job do chính mình annotate.")

    now = timezone.now()
    prev_status = issue.status
    issue.ruled_by = actor
    issue.ruled_at = now
    issue.ruling_note = ruling_note

    voided_error_ids: list[int] = []
    if decision == "ruling":
        issue.ruling_label = ruling_label
        issue.ruling_attributes = ruling_attributes
        issue.status = JobIssue.Status.OPEN
        issue.reopened_after_comment_id = max(issue.reopened_after_comment_id, issue.cvat_last_comment_id)
        if dispute_outcome == "rejected" or issue.is_disputed or pending_reqs:
            issue.is_disputed = False
            _finalize_linked_requests(
                project=project,
                job=job,
                pending_reqs=pending_reqs,
                actor=actor,
                new_status=AnnotatorRequest.Status.REJECTED,
                progress_note="",
                resolution_note=ruling_note or "PM đã phán quyết và bác bỏ phản hồi lỗi.",
                voided_error_ids=[],
                now=now,
            )
    elif decision == "not_an_issue":
        issue.status = JobIssue.Status.NOT_AN_ISSUE
        issue.is_disputed = False
        for err in errors:
            if not err.is_voided:
                err.is_voided = True
                err.save(update_fields=["is_voided"])
            voided_error_ids.append(err.pk)
        _finalize_linked_requests(
            project=project,
            job=job,
            pending_reqs=pending_reqs,
            actor=actor,
            new_status=AnnotatorRequest.Status.RESOLVED,
            progress_note="",
            resolution_note=ruling_note or "PM phán quyết issue không phải lỗi (not_an_issue).",
            voided_error_ids=voided_error_ids,
            now=now,
        )
    else:  # decision == "resolved"
        issue.status = JobIssue.Status.RESOLVED
        issue.is_disputed = False
        if pending_reqs:
            _finalize_linked_requests(
                project=project,
                job=job,
                pending_reqs=pending_reqs,
                actor=actor,
                new_status=AnnotatorRequest.Status.REJECTED,
                progress_note="",
                resolution_note=ruling_note or "PM xác nhận issue đã xử lý.",
                voided_error_ids=[],
                now=now,
            )

    issue.save()
    _unpin_issue_notifications(project, job, issue)
    ActivityLog.record(
        project=project,
        actor=actor,
        action="issue.ruling",
        target=job,
        job=job,
        before={"status": prev_status},
        after={
            "job_issue_id": issue.pk,
            "cvat_issue_id": issue.cvat_issue_id,
            "decision": decision,
            "status": issue.status,
            "ruling_label": issue.ruling_label,
            "voided_error_ids": voided_error_ids,
        },
        note=ruling_note,
    )
    if decision == "ruling" or not pending_reqs:
        label_info = f" -> {issue.ruling_label}" if (decision == "ruling" and issue.ruling_label) else ""
        _notify_ruling_parties(
            project,
            job,
            issue,
            actor=actor,
            title=f"PM đã phán quyết issue #{issue.cvat_issue_id}{label_info}",
            body=ruling_note or f"{job.name}: {issue.get_status_display()}",
        )
    return issue


def pm_rule_job_issue(
    project: Project,
    issue_id: int,
    *,
    actor: User,
    decision: str,
    ruling_label: str = "",
    ruling_attributes: dict[str, Any] | None = None,
    ruling_note: str = "",
    dispute_outcome: str | None = None,
) -> JobIssue:
    with transaction.atomic():
        job, issue = _lock_job_and_issue(project, issue_id)
        errors = list(
            ReviewError.objects.select_for_update(of=("self",))
            .filter(job=job, job_issue=issue)
            .order_by("id")
        )
        pending_reqs = list(
            AnnotatorRequest.objects.select_for_update(of=("self",))
            .filter(
                project=project,
                job=job,
                request_type=AnnotatorRequest.RequestType.ERROR_DISPUTE,
                status=AnnotatorRequest.Status.PENDING_PM,
            )
            .filter(Q(job_issue=issue) | Q(review_error__job_issue=issue))
            .order_by("id")
        )
        return _apply_pm_issue_ruling_locked(
            project=project,
            job=job,
            issue=issue,
            actor=actor,
            decision=decision,
            ruling_label=ruling_label,
            ruling_attributes=ruling_attributes or {},
            ruling_note=ruling_note,
            dispute_outcome=dispute_outcome,
            pending_reqs=pending_reqs,
            errors=errors,
        )


def resolve_annotator_request_atomic(
    project: Project,
    req_id: int,
    *,
    actor: User,
    new_status: str,
    progress_note: str = "",
    resolution_note: str = "",
) -> AnnotatorRequest:
    """Resolve an AnnotatorRequest under canonical lock order (Job -> JobIssue -> ReviewError -> AnnotatorRequest)."""
    refs = (
        AnnotatorRequest.objects.filter(pk=req_id, project=project)
        .values("job_id", "job_issue_id", "review_error_id", "review_error__job_issue_id")
        .first()
    )
    if refs is None:
        raise NotFound("Không tìm thấy yêu cầu trong organization.")

    with transaction.atomic():
        job = _lock_job(project, refs["job_id"])
        issue_id = refs["job_issue_id"] or refs["review_error__job_issue_id"]
        issue: JobIssue | None = None
        if issue_id is not None:
            issue = (
                JobIssue.objects.select_for_update(of=("self",))
                .select_related("author", "ruled_by")
                .filter(pk=issue_id, project=project, job=job)
                .first()
            )

        errors: list[ReviewError] = []
        if refs["review_error_id"] is not None or issue is not None:
            error_parts: list[Q] = []
            if refs["review_error_id"] is not None:
                error_parts.append(Q(pk=refs["review_error_id"]))
            if issue is not None:
                error_parts.append(Q(job=job, job_issue=issue))
            combined_error_q = error_parts[0]
            for part in error_parts[1:]:
                combined_error_q = combined_error_q | part
            errors = list(ReviewError.objects.select_for_update(of=("self",)).filter(combined_error_q).order_by("id"))

        req_q = Q(pk=req_id)
        if issue is not None:
            req_q = req_q | (
                Q(
                    project=project,
                    job=job,
                    request_type=AnnotatorRequest.RequestType.ERROR_DISPUTE,
                    status=AnnotatorRequest.Status.PENDING_PM,
                )
                & (Q(job_issue=issue) | Q(review_error__job_issue=issue))
            )
        locked_reqs = list(
            AnnotatorRequest.objects.select_for_update(of=("self",))
            .select_related("created_by")
            .filter(req_q, project=project)
            .order_by("id")
        )
        req = next((r for r in locked_reqs if r.pk == req_id), None)
        if req is None:
            raise NotFound("Không tìm thấy yêu cầu trong organization.")
        if req.status != AnnotatorRequest.Status.PENDING_PM:
            raise ValidationError("Yêu cầu này đã được xử lý, không thể cập nhật lại.")

        if req.request_type == AnnotatorRequest.RequestType.ERROR_DISPUTE:
            _ensure_not_delivered(job)
            if new_status == AnnotatorRequest.Status.RESOLVED:
                ann_ids, _, _ = get_stage_history(job)
                if actor.pk in ann_ids:
                    raise PermissionDenied(
                        "Luật bốn mắt: không thể tự chấp nhận phản hồi để gỡ lỗi trên job do chính mình annotate."
                    )

        if req.request_type == AnnotatorRequest.RequestType.ERROR_DISPUTE and issue is not None:
            pending_reqs = [
                r
                for r in locked_reqs
                if r.request_type == AnnotatorRequest.RequestType.ERROR_DISPUTE
                and r.status == AnnotatorRequest.Status.PENDING_PM
            ]
            if new_status == AnnotatorRequest.Status.RESOLVED:
                _apply_pm_issue_ruling_locked(
                    project=project,
                    job=job,
                    issue=issue,
                    actor=actor,
                    decision="not_an_issue",
                    ruling_label="",
                    ruling_attributes={},
                    ruling_note=resolution_note or progress_note or "Resolved via AnnotatorRequest",
                    dispute_outcome=None,
                    pending_reqs=pending_reqs,
                    errors=errors,
                )
                return req

            now = timezone.now()
            _finalize_linked_requests(
                project=project,
                job=job,
                pending_reqs=[req],
                actor=actor,
                new_status=AnnotatorRequest.Status.REJECTED,
                progress_note=progress_note,
                resolution_note=resolution_note,
                voided_error_ids=[],
                now=now,
            )
            other_pending = any(
                r.pk != req.pk
                and r.request_type == AnnotatorRequest.RequestType.ERROR_DISPUTE
                and r.status == AnnotatorRequest.Status.PENDING_PM
                for r in locked_reqs
            )
            if not other_pending:
                issue.is_disputed = False
                update_fields = ["is_disputed", "updated_at"]
                if issue.status == JobIssue.Status.UNCLEAR:
                    issue.status = JobIssue.Status.REOPENED
                    issue.reopened_after_comment_id = max(
                        issue.reopened_after_comment_id,
                        issue.cvat_last_comment_id,
                    )
                    update_fields.extend(["status", "reopened_after_comment_id"])
                issue.save(update_fields=update_fields)
                _unpin_issue_notifications(project, job, issue)
            return req

        # Legacy request without linked JobIssue (preserves existing behavior with canonical lock order).
        now = timezone.now()
        voided_error_id: int | None = None
        if (
            req.request_type == AnnotatorRequest.RequestType.ERROR_DISPUTE
            and new_status == AnnotatorRequest.Status.RESOLVED
            and req.review_error_id
        ):
            err = next((e for e in errors if e.pk == req.review_error_id), None)
            if err is not None:
                if not err.is_voided:
                    err.is_voided = True
                    err.save(update_fields=["is_voided"])
                voided_error_id = err.pk

        _finalize_linked_requests(
            project=project,
            job=job,
            pending_reqs=[req],
            actor=actor,
            new_status=new_status,
            progress_note=progress_note,
            resolution_note=resolution_note,
            voided_error_ids=[voided_error_id] if voided_error_id is not None else [],
            now=now,
        )
        return req


def materialize_reject_errors(
    job: Job,
    *,
    project: Project,
    stage: str,
    actor: User,
    errors: list[dict[str, Any]],
    sample: AuditSample | None = None,
) -> int:
    """Create ReviewError rows on QC1/QC2 reject, validating and reopening any linked JobIssues."""
    round_at_review = max(job.total_rework_rounds, job.rework_round)
    issue_ids = sorted({e["job_issue"] for e in errors if e.get("job_issue") is not None})
    locked_issues: dict[int, JobIssue] = {}
    if issue_ids:
        locked_issues = {
            ji.pk: ji
            for ji in JobIssue.objects.select_for_update(of=("self",))
            .filter(project=project, job=job, pk__in=issue_ids)
            .order_by("id")
        }
        missing = [iid for iid in issue_ids if iid not in locked_issues]
        if missing:
            raise ValidationError({"errors": f"Không tìm thấy JobIssue #{missing[0]} thuộc job này."})

    existing_cvat_ids: set[int] = set()
    if locked_issues:
        target_cvat_ids = sorted({ji.cvat_issue_id for ji in locked_issues.values()})
        existing_cvat_ids = set(
            ReviewError.objects.select_for_update(of=("self",))
            .filter(
                job=job,
                stage=stage,
                rework_round=round_at_review,
                cvat_issue_id__in=target_cvat_ids,
            )
            .order_by("id")
            .values_list("cvat_issue_id", flat=True)
        )

    allowed_frames = set(sample.frames or []) if (stage == ReviewStage.QC2 and sample is not None) else None
    to_create: list[ReviewError] = []
    matched_existing = 0

    for item in errors:
        issue_pk = item.get("job_issue")
        if issue_pk is None:
            to_create.append(
                ReviewError(
                    job=job,
                    stage=stage,
                    rework_round=round_at_review,
                    audit_sample=sample,
                    category=item["category"],
                    severity=item.get("severity") or item["category"].severity,
                    verdict=item.get("verdict") or ErrorVerdict.FAIL,
                    frame_number=item.get("frame_number"),
                    cvat_object_id=item.get("cvat_object_id"),
                    is_missing_object=bool(item.get("is_missing_object", False)),
                    location=item["location"],
                    description=item["description"],
                    reported_by=actor,
                )
            )
            continue

        ji = locked_issues[issue_pk]
        if ji.job_id != job.pk or ji.authority_status != JobIssue.AuthorityStatus.VALID or (
            ji.status == JobIssue.Status.NOT_AN_ISSUE
        ):
            raise ValidationError({"errors": f"JobIssue #{ji.cvat_issue_id} không hợp lệ hoặc đã phán quyết not_an_issue."})
        if ji.is_clarification and ji.ruled_at is None:
            raise ValidationError(
                {"errors": f"Issue làm rõ #{ji.cvat_issue_id} đang chờ PM phán quyết, không thể gắn vào lượt Reject."}
            )
        if stage == ReviewStage.QC2 and ji.author_stage == JobIssue.AuthorStage.QC1:
            raise ValidationError({"errors": f"Không thể dùng issue QC1 (#{ji.cvat_issue_id}) cho lượt reject QC2."})
        if stage == ReviewStage.QC1 and ji.author_stage == JobIssue.AuthorStage.QC2:
            raise ValidationError({"errors": f"Không thể dùng issue QC2 (#{ji.cvat_issue_id}) cho lượt reject QC1."})
        frame_num = item.get("frame_number") if item.get("frame_number") is not None else ji.frame_number
        if allowed_frames is not None and (ji.frame_number not in allowed_frames or frame_num not in allowed_frames):
            raise ValidationError(
                {"errors": f"Frame {frame_num} của issue #{ji.cvat_issue_id} không thuộc AuditSample.frames."}
            )

        ji.status = JobIssue.Status.REOPENED
        ji.reopened_after_comment_id = max(ji.reopened_after_comment_id, ji.cvat_last_comment_id)
        ji.save(update_fields=["status", "reopened_after_comment_id", "updated_at"])

        if ji.cvat_issue_id in existing_cvat_ids:
            matched_existing += 1
            continue
        existing_cvat_ids.add(ji.cvat_issue_id)

        bound_obj_id = ji.track_id if ji.track_id is not None else ji.shape_id
        raw_obj_id = bound_obj_id if bound_obj_id is not None else item.get("cvat_object_id")
        if (ji.defect_code == "EXI-MISS" or bool(item.get("is_missing_object", False))) and bound_obj_id is None:
            is_missing = True
            obj_id = None
            verdict = ErrorVerdict.FAIL
        else:
            is_missing = False
            obj_id = raw_obj_id
            verdict = item.get("verdict") or ErrorVerdict.FAIL

        default_loc = (
            f"Frame {frame_num} · #{obj_id}" if obj_id is not None else f"Frame {frame_num} · Issue #{ji.cvat_issue_id}"
        )
        location = (item.get("location") or default_loc)[:120]
        description = item.get("description") or ji.message

        to_create.append(
            ReviewError(
                job=job,
                stage=stage,
                rework_round=round_at_review,
                audit_sample=sample,
                job_issue=ji,
                cvat_issue_id=ji.cvat_issue_id,
                category=item["category"],
                severity=item.get("severity") or ji.severity,
                verdict=verdict,
                frame_number=frame_num,
                cvat_object_id=obj_id,
                is_missing_object=is_missing,
                location=location,
                description=description,
                reported_by=actor,
            )
        )

    if to_create:
        ReviewError.objects.bulk_create(to_create)
    if not to_create and not matched_existing:
        raise ValidationError({"errors": "Phải ghi ít nhất một lỗi hợp lệ khi Reject."})
    return len(to_create) or matched_existing
