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

    def test_member_without_role_defaults_to_annotator(self):
        newcomer = make_user("newcomer")
        response = self.pm.post(self.f.url(f"teams/{self.team_a.id}/add-member/"), {"user": newcomer.id}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(newcomer.get_project_roles(self.f.project), {Role.ANNOTATOR})
        # Người đã có vai trò thì giữ nguyên, không bị gán thêm Annotator
        self.pm.post(self.f.url(f"teams/{self.team_b.id}/add-member/"), {"user": self.f.qc1.id}, format="json")
        self.assertEqual(self.f.qc1.get_project_roles(self.f.project), {Role.QC1})

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


class TeamRolesInPayloadTests(TestCase):
    def test_team_members_include_project_roles(self):
        f = ProjectFixture()
        team = Team.objects.create(project=f.project, name="R")
        TeamMember.objects.create(team=team, user=f.ann1)
        TeamMember.objects.create(team=team, user=f.qc1)
        data = f.client(f.pm).get(f.url(f"teams/{team.id}/")).data
        roles = {m["user"]["username"]: m["roles"] for m in data["members"]}
        self.assertEqual(roles, {f.ann1.username: [Role.ANNOTATOR], f.qc1.username: [Role.QC1]})
