from __future__ import annotations

import logging
from typing import Any

import requests
from dashboard.modalities import default_annotation_type_for, normalize_dimension
from dashboard.models import (
    DeliverStatus,
    PipelineStep,
    SyncedJob,
    SyncedTask,
)
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Synchronizes Tasks, Jobs, and Issues from private CVAT instance using service token."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--days", type=int, default=30, help="Days of history to sync")
        parser.add_argument("--task-id", type=int, default=None, help="Specific task ID to sync")

    def handle(self, *args: Any, **options: Any) -> None:
        cvat_url = getattr(settings, "CVAT_BASE_URL", "").rstrip("/")
        token = getattr(settings, "CVAT_SERVICE_TOKEN", "")

        if not cvat_url:
            self.stdout.write(self.style.ERROR("CVAT_BASE_URL is not configured in settings or .env"))
            return

        headers = {}
        if token:
            headers["Authorization"] = f"Token {token}"

        self.stdout.write(f"Connecting to CVAT at {cvat_url}...")

        # 1. Sync Tasks
        tasks_url = f"{cvat_url}/api/tasks?page_size=100"
        task_filter = options.get("task_id")
        if task_filter:
            tasks_url += f"&id={task_filter}"

        try:
            resp = requests.get(tasks_url, headers=headers, timeout=15)
            if resp.status_code != 200:
                self.stdout.write(self.style.ERROR(f"Failed to fetch tasks: HTTP {resp.status_code} - {resp.text[:200]}"))
                return
            tasks_data = resp.json().get("results", [])
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"Connection error to CVAT: {exc}"))
            return

        synced_tasks_count = 0
        for t_info in tasks_data:
            tid = t_info.get("id")
            if not tid:
                continue
            name = t_info.get("name", f"Task #{tid}")
            p_name = (t_info.get("project") or {}).get("name", "") if isinstance(t_info.get("project"), dict) else ""
            size = t_info.get("size", 0)
            dim = normalize_dimension(t_info.get("dimension"), allow_all=False)
            ann_type = str(t_info.get("annotation_type") or default_annotation_type_for(dim))

            SyncedTask.objects.update_or_create(
                cvat_task_id=tid,
                defaults={
                    "name": name,
                    "project_name": p_name,
                    "total_frames": size,
                    "dimension": dim,
                    "annotation_type": ann_type,
                },
            )
            synced_tasks_count += 1

        self.stdout.write(self.style.SUCCESS(f"Synced {synced_tasks_count} tasks."))

        # 2. Sync Jobs
        jobs_url = f"{cvat_url}/api/jobs?page_size=200"
        if task_filter:
            jobs_url += f"&task_id={task_filter}"

        try:
            resp = requests.get(jobs_url, headers=headers, timeout=15)
            if resp.status_code == 200:
                jobs_data = resp.json().get("results", [])
                synced_jobs_count = 0
                for j_info in jobs_data:
                    jid = j_info.get("id")
                    tid = j_info.get("task_id")
                    if not jid or not tid:
                        continue
                    task_obj = SyncedTask.objects.filter(cvat_task_id=tid).first()
                    if not task_obj:
                        continue

                    stage = str(j_info.get("stage") or "annotation").lower()
                    state = str(j_info.get("state") or "new").lower()
                    assignee = (j_info.get("assignee") or {}).get("username", "") if isinstance(j_info.get("assignee"), dict) else ""

                    # Map to pipeline step
                    if stage == "acceptance" or state == "completed":
                        p_step = PipelineStep.COMPLETED
                        d_status = DeliverStatus.READY
                    elif stage == "validation":
                        p_step = PipelineStep.L1_QC
                        d_status = DeliverStatus.NOT_READY
                    elif stage == "annotation":
                        p_step = PipelineStep.ANNOTATOR
                        d_status = DeliverStatus.NOT_READY
                    else:
                        p_step = PipelineStep.PRE_QC
                        d_status = DeliverStatus.NOT_READY

                    SyncedJob.objects.update_or_create(
                        cvat_job_id=jid,
                        defaults={
                            "task": task_obj,
                            "start_frame": j_info.get("start_frame", 0),
                            "stop_frame": j_info.get("stop_frame", 0),
                            "frame_count": max(0, j_info.get("stop_frame", 0) - j_info.get("start_frame", 0) + 1),
                            "pipeline_step": p_step,
                            "work_state": state,
                            "deliver_status": d_status,
                            "annotator_username": assignee if p_step == PipelineStep.ANNOTATOR else "",
                            "step_entered_at": timezone.now(),
                        },
                    )
                    synced_jobs_count += 1

                self.stdout.write(self.style.SUCCESS(f"Synced {synced_jobs_count} jobs."))
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"Error syncing jobs: {exc}"))

        self.stdout.write(self.style.SUCCESS("CVAT sync finished."))
