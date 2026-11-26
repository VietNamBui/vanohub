from django.test import TestCase

from accounts.testing import ProjectFixture, make_user

from .models import Team, TeamMember


class TeamTests(TestCase):
    def setUp(self):
        self.f = ProjectFixture()
        self.pm = self.f.client(self.f.pm)
        self.team_a = Team.objects.create(project=self.f.project, name="A")
        self.team_b = Team.objects.create(project=self.f.project, name="B")

    def test_add_member_then_transfer(self):
        url = self.f.url(f"teams/{self.team_a.id}/add-member/")
        self.assertEqual(self.pm.post(url, {"user": self.f.ann1.id}, format="json").status_code, 201)
        again = self.pm.post(self.f.url(f"teams/{self.team_b.id}/add-member/"), {"user": self.f.ann1.id}, format="json")
        self.assertEqual(again.status_code, 400)  # đã thuộc team A → phải dùng điều chuyển
        moved = self.pm.post(self.f.url("teams/transfer/"), {"user": self.f.ann1.id, "to_team": self.team_b.id}, format="json")
        self.assertEqual(moved.status_code, 200, moved.data)
        self.assertEqual(TeamMember.objects.get(user=self.f.ann1).team, self.team_b)

    def test_user_outside_project_cannot_join(self):
        outsider = make_user("outsider")
        response = self.pm.post(self.f.url(f"teams/{self.team_a.id}/add-member/"), {"user": outsider.id}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_qc2_only_cannot_manage_teams(self):
        self.assertEqual(self.f.client(self.f.qc2).get(self.f.url("teams/")).status_code, 403)

    def test_workload_counts_only_active_stage_jobs_and_separates_overdue_from_due_soon(self):
        from datetime import timedelta

        from django.utils import timezone

        from jobs.models import JobStatus

        TeamMember.objects.create(team=self.team_a, user=self.f.ann1, capacity=5)
        TeamMember.objects.create(team=self.team_a, user=self.f.qc1, capacity=5)
        now = timezone.now()
        # 1 annotating overdue, 1 rework due_soon, 1 already in pending_qc1 (must NOT count in ann1.holding)
        self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, deadline=now - timedelta(hours=3))
        self.f.job(status=JobStatus.REWORK, annotator=self.f.ann1, deadline=now + timedelta(hours=6))
        self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann1, deadline=now + timedelta(hours=2))
        self.f.job(status=JobStatus.PENDING_QC2, annotator=self.f.ann1, deadline=now + timedelta(hours=2))

        rows = {r["user"]["id"]: r for r in self.pm.get(self.f.url("teams/workload/")).data}
        self.assertEqual(rows[self.f.ann1.id]["holding"], 2)
        self.assertEqual(rows[self.f.ann1.id]["overdue"], 1)
        self.assertEqual(rows[self.f.ann1.id]["due_soon"], 1)
        # qc1_holding chỉ đếm PENDING_QC1 / QC1_REVIEWING (1 job), không đếm ANNOTATING hay PENDING_QC2
        self.assertEqual(rows[self.f.qc1.id]["qc1_holding"], 1)


class TeamDeleteTests(TestCase):
    def setUp(self):
        from accounts.testing import ProjectFixture
        from projects.models import Announcement

        self.f = ProjectFixture()
        self.team = Team.objects.create(project=self.f.project, name="T-del")
        TeamMember.objects.create(team=self.team, user=self.f.ann1)
        Announcement.objects.create(project=self.f.project, target_team=self.team, content="chi cho team")

    def test_pm_deletes_team_members_become_unassigned(self):
        from projects.models import Announcement

        response = self.f.client(self.f.pm).delete(self.f.url(f"teams/{self.team.id}/"))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Team.objects.filter(pk=self.team.pk).exists())
        self.assertFalse(TeamMember.objects.filter(user=self.f.ann1).exists())
        self.assertIn("annotator", self.f.ann1.get_project_roles(self.f.project))
        self.assertFalse(Announcement.objects.exists())  # không để thông báo riêng lộ ra cả dự án

    def test_qc2_only_cannot_delete(self):
        response = self.f.client(self.f.qc2).delete(self.f.url(f"teams/{self.team.id}/"))
        self.assertIn(response.status_code, (403, 404))
