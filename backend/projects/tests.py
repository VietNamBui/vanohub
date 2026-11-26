from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Role, RoleAssignment, User
from accounts.testing import ProjectFixture
from cvat_integration import sync
from jobs.models import Job, JobStatus

from .models import Project


class ProjectApiTests(TestCase):
    """Kiểm tra phân quyền theo phạm vi dự án của /api/projects/."""

    def setUp(self):
        self.client = APIClient()
        self.project_a = Project.objects.create(name="Project A")
        self.project_b = Project.objects.create(name="Project B")

        self.pm = self._user("pm", Role.PROJECT_MANAGER, self.project_a)
        self.qc2_only = self._user("qc2", Role.QC2, self.project_a)
        self.annotator = self._user("ann", Role.ANNOTATOR, self.project_b)
        self.outsider = User.objects.create_user("outsider", password="pw")

    def _user(self, username, role, project):
        user = User.objects.create_user(username, password="pw")
        RoleAssignment.objects.create(user=user, role=role, project=project)
        return user

    def _list(self, user):
        self.client.force_authenticate(user)
        return self.client.get(reverse("project-list"))

    def _detail(self, user, project):
        self.client.force_authenticate(user)
        return self.client.get(reverse("project-detail", args=[project.pk]))

    def test_requires_authentication(self):
        self.assertEqual(self.client.get(reverse("project-list")).status_code, 401)

    def test_pm_sees_only_own_project_and_is_also_qc2(self):
        response = self._list(self.pm)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([p["name"] for p in response.data], ["Project A"])
        self.assertEqual(response.data[0]["my_roles"], [Role.PROJECT_MANAGER, Role.QC2])

    def test_qc2_only_is_not_project_manager(self):
        response = self._list(self.qc2_only)
        self.assertEqual(response.data[0]["my_roles"], [Role.QC2])

    def test_user_without_roles_sees_nothing(self):
        self.assertEqual(self._list(self.outsider).data, [])

    def test_project_outside_scope_returns_404(self):
        self.assertEqual(self._detail(self.pm, self.project_b).status_code, 404)

    def test_detail_member_counts_include_implied_roles(self):
        response = self._detail(self.pm, self.project_a)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["member_total"], 2)
        # PM được tính vào QC2 → 2 người có quyền QC2 (pm + qc2_only), 1 PM.
        self.assertEqual(response.data["member_counts"], {Role.PROJECT_MANAGER: 1, Role.QC2: 2})

    def test_user_with_two_roles_is_counted_once(self):
        RoleAssignment.objects.create(user=self.pm, role=Role.QC1, project=self.project_a)
        response = self._detail(self.pm, self.project_a)
        self.assertEqual(response.data["member_total"], 2)
        self.assertEqual(
            response.data["my_roles"],
            sorted([Role.PROJECT_MANAGER, Role.QC2, Role.QC1]),
        )





class DataManagementTests(TestCase):
    def setUp(self):
        self.f = ProjectFixture()
        self.pm = self.f.client(self.f.pm)

    def test_pm_creates_dataset_and_batch(self):
        ds = self.pm.post(self.f.url("datasets/"), {"name": "New DS"}, format="json")
        self.assertEqual(ds.status_code, 201, ds.data)
        batch = self.pm.post(self.f.url("batches/"), {"dataset": ds.data["id"], "name": "B9"}, format="json")
        self.assertEqual(batch.status_code, 201, batch.data)

    def test_batch_cannot_use_dataset_of_other_project(self):
        other = ProjectFixture("Q")
        response = self.pm.post(self.f.url("batches/"), {"dataset": other.dataset.id, "name": "X"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_qc2_only_cannot_manage_data(self):
        qc2 = self.f.client(self.f.qc2)
        self.assertEqual(qc2.get(self.f.url("datasets/")).status_code, 403)
        self.assertEqual(qc2.post(self.f.url("datasets/"), {"name": "X"}, format="json").status_code, 403)

    def test_settings_readable_by_qc2_but_only_pm_can_change(self):
        qc2 = self.f.client(self.f.qc2)
        self.assertEqual(qc2.get(self.f.url("settings/")).status_code, 200)
        self.assertEqual(qc2.patch(self.f.url("settings/"), {"sampling_rate": 20}, format="json").status_code, 403)
        self.assertEqual(self.pm.patch(self.f.url("settings/"), {"sampling_rate": 20}, format="json").status_code, 200)

    def test_delivery_requires_all_jobs_approved_and_recipient_output_path(self):
        job = self.f.job(status=JobStatus.PENDING_QC2)
        payload = {"batch": self.f.batch.id, "recipient": "Client A", "output_path": "s3://bucket/batch-1"}
        refused = self.pm.post(self.f.url("deliveries/"), payload, format="json")
        self.assertEqual(refused.status_code, 400)
        Job.objects.filter(pk=job.pk).update(status=JobStatus.APPROVED)
        # Thiếu người nhận / đường dẫn đầu ra → 400
        missing = self.pm.post(self.f.url("deliveries/"), {"batch": self.f.batch.id}, format="json")
        self.assertEqual(missing.status_code, 400)
        ok = self.pm.post(self.f.url("deliveries/"), payload, format="json")
        self.assertEqual(ok.status_code, 201, ok.data)
        self.assertEqual(ok.data["recipient"], "Client A")
        self.assertEqual(ok.data["output_path"], "s3://bucket/batch-1")
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.DELIVERED)

    def test_overview_marks_undefined_kpis(self):
        self.f.job(status=JobStatus.APPROVED)
        data = self.pm.get(self.f.url("overview/")).data
        self.assertEqual(data["counts"]["jobs"], 1)
        self.assertEqual(data["metrics"]["quality_cl"]["status"], "pending_definition")
        self.assertIsNone(data["metrics"]["quality_cl"]["value"])
        self.assertEqual(self.f.client(self.f.qc2).get(self.f.url("overview/")).status_code, 403)

    def test_guideline_versions_increment(self):
        for _ in range(2):
            self.pm.post(self.f.url("guidelines/"), {"title": "G", "content": "x"}, format="json")
        versions = [g["version"] for g in self.f.client(self.f.ann1).get(self.f.url("guidelines/")).data]
        self.assertEqual(versions, [2, 1])


class FakeCvat:
    def __init__(self, jobs):
        self.jobs = jobs

    def get_task(self, task_id):
        return {"id": task_id, "name": "task"}

    def list_task_jobs(self, task_id):
        return self.jobs

    def count_job_objects(self, job_id):
        return 7


class CvatSyncTests(TestCase):
    def setUp(self):
        self.f = ProjectFixture()

    def test_import_creates_jobs_and_maps_assignee_and_status(self):
        client = FakeCvat([
            {"id": 101, "stage": "annotation", "state": "in progress", "start_frame": 0, "stop_frame": 9,
             "assignee": {"username": self.f.ann1.username}},
            {"id": 102, "stage": "validation", "state": "completed", "start_frame": 10, "stop_frame": 19,
             "assignee": None},
        ])
        result = sync.import_task_jobs(self.f.batch, 5, self.f.pm, client=client)
        self.assertEqual(result["created"], 2)
        j101 = Job.objects.get(cvat_job_id=101)
        self.assertEqual((j101.status, j101.annotator, j101.frame_count), (JobStatus.ANNOTATING, self.f.ann1, 10))
        self.assertEqual(Job.objects.get(cvat_job_id=102).status, JobStatus.QC1_PASSED)
        self.f.batch.refresh_from_db()
        self.assertEqual(self.f.batch.last_sync_status, "ok")

    def test_import_prefers_cvat_username_mapping(self):
        self.f.ann2.cvat_username = "cvat_special_ann"
        self.f.ann2.save(update_fields=["cvat_username"])
        client = FakeCvat([
            {"id": 150, "stage": "annotation", "state": "new", "start_frame": 0, "stop_frame": 4,
             "assignee": {"username": "cvat_special_ann"}},
        ])
        sync.import_task_jobs(self.f.batch, 9, self.f.pm, client=client)
        self.assertEqual(Job.objects.get(cvat_job_id=150).annotator, self.f.ann2)

    def test_sync_never_overrides_jobs_already_in_qc2(self):
        job = self.f.job(status=JobStatus.APPROVED, cvat_job_id=201)
        self.f.batch.cvat_task_id = 5
        self.f.batch.save()
        client = FakeCvat([{"id": 201, "stage": "annotation", "state": "new"}])
        sync.sync_batch(self.f.batch, self.f.pm, client=client, count_objects=True)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.APPROVED)
        self.assertEqual(job.object_count, 7)

    def test_cvat_rejection_increments_rework_round(self):
        job = self.f.job(status=JobStatus.QC1_REVIEWING, cvat_job_id=301)
        self.f.batch.cvat_task_id = 5
        self.f.batch.save()
        sync.sync_batch(self.f.batch, self.f.pm, client=FakeCvat([{"id": 301, "stage": "validation", "state": "rejected"}]))
        job.refresh_from_db()
        self.assertEqual((job.status, job.rework_round), (JobStatus.REWORK, 1))


class MemberRolesTests(TestCase):
    def setUp(self):
        from accounts.testing import ProjectFixture

        self.f = ProjectFixture()
        self.pm = self.f.client(self.f.pm)

    def _add(self, client, user, role):
        return client.post(self.f.url(f"members/{user.id}/roles/"), {"role": role}, format="json")

    def test_pm_can_add_role(self):
        response = self._add(self.pm, self.f.ann1, "qc1")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn("qc1", response.data["roles"])
        self.assertIn("qc1", self.f.ann1.get_project_roles(self.f.project))

    def test_cannot_add_pm_or_existing_or_implied_role(self):
        self.assertEqual(self._add(self.pm, self.f.ann1, "project_manager").status_code, 400)
        self.assertEqual(self._add(self.pm, self.f.ann1, "annotator").status_code, 400)
        self.assertEqual(self._add(self.pm, self.f.pm, "qc2").status_code, 400)  # PM đã ngầm có QC2

    def test_qc2_only_cannot_add_role(self):
        self.assertEqual(self._add(self.f.client(self.f.qc2), self.f.ann1, "qc1").status_code, 403)

    def test_user_outside_project_is_404(self):
        from accounts.testing import make_user

        other = Project.objects.create(name="Other")
        outsider = make_user("outsider", "annotator", project=other)
        self.assertEqual(self._add(self.pm, outsider, "qc1").status_code, 404)


class BatchTeamTests(TestCase):
    def setUp(self):
        from teams.models import Team

        self.f = ProjectFixture()
        self.team = Team.objects.create(project=self.f.project, name="Team A")
        other = Project.objects.create(name="Other")
        self.foreign_team = Team.objects.create(project=other, name="Team X")
        self.pm = self.f.client(self.f.pm)

    def test_pm_assigns_team_to_batch(self):
        response = self.pm.patch(self.f.url(f"batches/{self.f.batch.id}/"), {"team": self.team.id}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["team_name"], "Team A")
        response = self.pm.patch(self.f.url(f"batches/{self.f.batch.id}/"), {"team": None}, format="json")
        self.assertIsNone(response.data["team"])

    def test_team_from_other_project_is_rejected(self):
        response = self.pm.patch(self.f.url(f"batches/{self.f.batch.id}/"), {"team": self.foreign_team.id}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_deleting_team_unassigns_batch(self):
        self.f.batch.team = self.team
        self.f.batch.save()
        self.team.delete()
        self.f.batch.refresh_from_db()
        self.assertIsNone(self.f.batch.team)


class ProjectCreateAndBatchConfirmQc2Tests(TestCase):
    def setUp(self):
        from teams.models import Team

        self.f = ProjectFixture()
        self.team = Team.objects.create(project=self.f.project, name="Team Alpha")
        self.f.batch.team = self.team
        self.f.batch.save()
        self.pm_client = self.f.client(self.f.pm)
        self.qc1_client = self.f.client(self.f.qc1)
        self.ann_client = self.f.client(self.f.ann1)

    def test_pm_creates_project_and_assigns_pms_while_non_pm_forbidden(self):
        created = self.pm_client.post(
            reverse("project-list"),
            {
                "name": "Project C",
                "description": "Created by PM",
                "pm_ids": [self.f.pm.id],
                "escalation_policy": "warn_only",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual([u["id"] for u in created.data["project_managers"]], [self.f.pm.id])
        self.assertEqual(created.data["escalation_policy"], "warn_only")

        # Non-PM không được tạo project
        self.assertEqual(
            self.ann_client.post(reverse("project-list"), {"name": "Illegal"}, format="json").status_code, 403
        )
        self.assertEqual(
            self.qc1_client.post(reverse("project-list"), {"name": "Illegal"}, format="json").status_code, 403
        )
        # Non-PM trong dự án không được chỉnh sửa project
        self.assertEqual(
            self.ann_client.patch(
                reverse("project-detail", args=[self.f.project.id]), {"name": "Nope"}, format="json"
            ).status_code,
            403,
        )

    def test_pm_confirms_batch_to_qc2_only_when_100_percent_passed(self):
        from .models import UserNotification

        j1 = self.f.job(status=JobStatus.QC1_PASSED, annotator=self.f.ann1)
        j2 = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann2)
        # QC1 không có quyền confirm_qc2
        self.assertEqual(
            self.qc1_client.post(self.f.url(f"batches/{self.f.batch.id}/confirm-qc2/"), {}, format="json").status_code,
            403,
        )
        # Còn j2 chưa đạt QC1 → từ chối
        early = self.pm_client.post(self.f.url(f"batches/{self.f.batch.id}/confirm-qc2/"), {}, format="json")
        self.assertEqual(early.status_code, 400)

        Job.objects.filter(pk=j2.pk).update(status=JobStatus.QC1_PASSED)
        ok = self.pm_client.post(self.f.url(f"batches/{self.f.batch.id}/confirm-qc2/"), {"note": "xong"}, format="json")
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertEqual(set(Job.objects.filter(pk__in=[j1.pk, j2.pk]).values_list("status", flat=True)), {JobStatus.PENDING_QC2})
        self.assertTrue(
            UserNotification.objects.filter(
                recipient=self.f.qc2, category=UserNotification.Category.REVIEW_NEEDED
            ).exists()
        )
