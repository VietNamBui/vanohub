from django.test import TestCase

from accounts.models import Role
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

    def test_leader_must_be_team_leader(self):
        response = self.pm.patch(self.f.url(f"teams/{self.team_a.id}/"), {"leader": self.f.ann1.id}, format="json")
        self.assertEqual(response.status_code, 400)
        tl = make_user("tl", Role.TEAM_LEADER, project=self.f.project)
        response = self.pm.patch(self.f.url(f"teams/{self.team_a.id}/"), {"leader": tl.id}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_user_outside_project_cannot_join(self):
        outsider = make_user("outsider")
        response = self.pm.post(self.f.url(f"teams/{self.team_a.id}/add-member/"), {"user": outsider.id}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_qc2_only_cannot_manage_teams(self):
        self.assertEqual(self.f.client(self.f.qc2).get(self.f.url("teams/")).status_code, 403)


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


class LeaderApiTests(TestCase):
    """Team Leader chỉ thấy / thao tác trong team mình phụ trách."""

    def setUp(self):
        self.f = ProjectFixture()
        p = self.f.project
        self.tl = make_user("tl", Role.TEAM_LEADER, project=p)
        self.team = Team.objects.create(project=p, name="Team A", leader=self.tl)
        self.other_team = Team.objects.create(project=p, name="Team B")
        for user in (self.tl, self.f.ann1, self.f.qc1):
            TeamMember.objects.create(team=self.team, user=user)
        TeamMember.objects.create(team=self.other_team, user=self.f.ann2)
        self.mine = self.f.job(status="annotating", annotator=self.f.ann1)
        self.theirs = self.f.job(status="annotating", annotator=self.f.ann2)
        self.theirs.qc1_reviewer = None
        self.theirs.save()
        self.client_tl = self.f.client(self.tl)

    def test_pm_and_annotator_cannot_use_leader_api(self):
        self.assertEqual(self.f.client(self.f.pm).get(self.f.url("leader/teams/")).status_code, 403)
        self.assertEqual(self.f.client(self.f.ann1).get(self.f.url("leader/jobs/")).status_code, 403)

    def test_leader_sees_only_team_jobs_and_members(self):
        ids = [j["id"] for j in self.client_tl.get(self.f.url("leader/jobs/")).data["results"]]
        self.assertIn(self.mine.id, ids)
        self.assertNotIn(self.theirs.id, ids)
        teams = self.client_tl.get(self.f.url("leader/teams/")).data
        self.assertEqual([t["name"] for t in teams], ["Team A"])
        self.assertEqual(self.client_tl.get(self.f.url(f"leader/dashboard/?team={self.other_team.id}")).status_code, 404)

    def test_batch_assigned_to_team_counts_as_team_job(self):
        self.f.batch.team = self.team
        self.f.batch.save()
        ids = [j["id"] for j in self.client_tl.get(self.f.url("leader/jobs/")).data["results"]]
        self.assertIn(self.theirs.id, ids)

    def test_reassign_only_to_team_members(self):
        url = self.f.url(f"leader/jobs/{self.mine.id}/assign/")
        self.assertEqual(self.client_tl.post(url, {"annotator": self.f.ann2.id}, format="json").status_code, 400)
        self.assertEqual(self.client_tl.post(url, {"annotator": self.f.ann1.id}, format="json").status_code, 200)
        self.assertEqual(self.client_tl.post(self.f.url(f"leader/jobs/{self.theirs.id}/assign/"),
                                             {"annotator": self.f.ann1.id}, format="json").status_code, 404)

    def test_bulk_deadline_only_touches_team_jobs(self):
        response = self.client_tl.post(self.f.url("leader/jobs/bulk-deadline/"),
                                       {"ids": [self.mine.id, self.theirs.id], "deadline": None}, format="json")
        self.assertEqual(response.data["updated"], 1)

    def test_grant_and_revoke_qc1(self):
        url = self.f.url(f"leader/teams/{self.team.id}/members/{self.f.ann1.id}/qc1/")
        self.assertEqual(self.client_tl.post(url).status_code, 201)
        self.assertIn(Role.QC1, self.f.ann1.get_project_roles(self.f.project))
        self.assertEqual(self.client_tl.post(url).status_code, 400)  # đã có
        self.assertEqual(self.client_tl.delete(url).status_code, 200)
        self.assertNotIn(Role.QC1, self.f.ann1.get_project_roles(self.f.project))

    def test_cannot_revoke_implied_qc1_or_qc1_with_open_jobs(self):
        self.assertEqual(self.client_tl.delete(self.f.url(f"leader/teams/{self.team.id}/members/{self.tl.id}/qc1/")).status_code, 400)
        self.f.job(status="pending_qc1", annotator=self.f.ann1)  # qc1_reviewer mặc định = self.f.qc1
        self.assertEqual(self.client_tl.delete(self.f.url(f"leader/teams/{self.team.id}/members/{self.f.qc1.id}/qc1/")).status_code, 400)

    def test_cannot_grant_qc1_outside_own_team(self):
        url = self.f.url(f"leader/teams/{self.other_team.id}/members/{self.f.ann2.id}/qc1/")
        self.assertEqual(self.client_tl.post(url).status_code, 404)

    def test_dashboard_shape(self):
        data = self.client_tl.get(self.f.url("leader/dashboard/?period=week")).data
        self.assertEqual(data["member_count"], 3)
        self.assertEqual(data["kpi_quota"]["status"], "pending_definition")
        self.assertEqual({r["user"]["username"] for r in data["ranking"]}, {"tl", self.f.ann1.username, self.f.qc1.username})
