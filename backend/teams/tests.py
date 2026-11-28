from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError, connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts.models import Role, User
from accounts.testing import ProjectFixture, make_user
from jobs.models import JobStatus
from projects.models import ActivityLog, Announcement

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
        moved = self.pm.post(
            self.f.url("teams/transfer/"), {"user": self.f.ann1.id, "to_team": self.team_b.id}, format="json"
        )
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

    def test_set_capacity_updates_member_and_records_activity_log(self):
        TeamMember.objects.create(team=self.team_a, user=self.f.ann1, capacity=5)
        res = self.pm.post(
            self.f.url(f"teams/{self.team_a.id}/set-capacity/"),
            {"user": self.f.ann1.id, "capacity": 12},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(TeamMember.objects.get(team=self.team_a, user=self.f.ann1).capacity, 12)
        log = ActivityLog.objects.filter(project=self.f.project, action="team.set_capacity").first()
        self.assertIsNotNone(log)
        assert log is not None
        self.assertEqual(log.before, {"user": self.f.ann1.username, "capacity": 5})
        self.assertEqual(log.after, {"user": self.f.ann1.username, "capacity": 12})

    def test_qc2_only_cannot_manage_teams(self):
        self.assertEqual(self.f.client(self.f.qc2).get(self.f.url("teams/")).status_code, 403)

    def test_add_member_and_transfer_block_cross_org_user_and_superuser(self):
        other = ProjectFixture("OtherOrg")
        superuser = User.objects.create_superuser("platform_admin", "admin@example.com", "pw")
        url = self.f.url(f"teams/{self.team_a.id}/add-member/")

        missing = self.pm.post(url, {"user": 999999}, format="json")
        self.assertEqual(missing.status_code, 400)

        for forbidden_user in (other.ann1, other.pm, superuser):
            res = self.pm.post(url, {"user": forbidden_user.id}, format="json")
            self.assertEqual(res.status_code, 400, res.data)
            self.assertEqual(res.data["user"], missing.data["user"])
            self.assertEqual(forbidden_user.get_project_roles(self.f.project), set())
            self.assertFalse(TeamMember.objects.filter(team=self.team_a, user=forbidden_user).exists())

        transfer_missing = self.pm.post(
            self.f.url("teams/transfer/"), {"user": 999999, "to_team": self.team_b.id}, format="json"
        )
        transfer_other = self.pm.post(
            self.f.url("teams/transfer/"), {"user": other.ann1.id, "to_team": self.team_b.id}, format="json"
        )
        self.assertEqual(transfer_other.status_code, 400)
        self.assertEqual(transfer_other.data["user"], transfer_missing.data["user"])

    def test_remove_member_and_workload_reject_bad_int_with_400(self):
        TeamMember.objects.create(team=self.team_a, user=self.f.ann1)
        remove_url = self.f.url(f"teams/{self.team_a.id}/remove-member/")
        for bad in ("abc", None, True, 0, -1, 9_999_999_999_999):
            res = self.pm.post(remove_url, {"user": bad}, format="json")
            self.assertEqual(res.status_code, 400, f"remove_member expected 400 for {bad!r}")

        ok = self.pm.post(remove_url, {"user": self.f.ann1.id}, format="json")
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertFalse(TeamMember.objects.filter(team=self.team_a, user=self.f.ann1).exists())

        for bad_team in ("abc", "0", "-5", "999999999999999"):
            res = self.pm.get(self.f.url(f"teams/workload/?team={bad_team}"))
            self.assertEqual(res.status_code, 400, f"workload expected 400 for team={bad_team!r}")

    def test_workload_counts_only_active_stage_jobs_and_separates_overdue_from_due_soon(self):
        now = timezone.now()
        TeamMember.objects.create(team=self.team_a, user=self.f.ann1, capacity=5)
        TeamMember.objects.create(team=self.team_a, user=self.f.qc1, capacity=4)
        # Active annotator jobs
        self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, deadline=now - timedelta(hours=2))
        self.f.job(
            status=JobStatus.REWORK,
            annotator=self.f.ann1,
            deadline=now + timedelta(hours=6),
            is_escalated=True,
        )
        # Jobs waiting in QC1 / QC1_PASSED / QC2 must NOT count against annotator active workload;
        # qc1_holding chỉ đếm PENDING_QC1 / QC1_REVIEWING (không đếm QC1_PASSED hay PENDING_QC2).
        self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann1, deadline=now - timedelta(hours=1))
        self.f.job(status=JobStatus.QC1_PASSED, annotator=self.f.ann1, deadline=now + timedelta(hours=2))
        self.f.job(status=JobStatus.PENDING_QC2, annotator=self.f.ann1, deadline=now - timedelta(hours=3))

        res = self.pm.get(self.f.url(f"teams/workload/?team={self.team_a.id}"))
        self.assertEqual(res.status_code, 200, res.data)
        by_user = {row["user"]["id"]: row for row in res.data}
        self.assertEqual(by_user[self.f.ann1.id]["holding"], 2)
        self.assertEqual(by_user[self.f.ann1.id]["overdue"], 1)
        self.assertEqual(by_user[self.f.ann1.id]["due_soon"], 1)
        self.assertEqual(by_user[self.f.ann1.id]["escalated"], 1)
        self.assertEqual(by_user[self.f.qc1.id]["holding"], 0)
        self.assertEqual(by_user[self.f.qc1.id]["qc1_holding"], 1)
        self.assertEqual(by_user[self.f.qc1.id]["overdue"], 0)


class TeamDeleteTests(TestCase):
    def setUp(self):
        self.f = ProjectFixture()
        self.team = Team.objects.create(project=self.f.project, name="T-del")
        TeamMember.objects.create(team=self.team, user=self.f.ann1)
        Announcement.objects.create(project=self.f.project, target_team=self.team, content="chi cho team")

    def test_pm_deletes_team_members_become_unassigned(self):
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


class TeamConcurrencyAndIntegrityTests(TestCase):
    def setUp(self):
        self.f = ProjectFixture()
        self.pm = self.f.client(self.f.pm)
        self.team_a = Team.objects.create(project=self.f.project, name="Team A")
        self.team_b = Team.objects.create(project=self.f.project, name="Team B")

    def test_duplicate_team_integrity_error_returns_400(self):
        with patch.object(Team, "save", side_effect=IntegrityError("unique_team_name_per_project")):
            res = self.pm.post(self.f.url("teams/"), {"name": "Team Race"}, format="json")
            self.assertEqual(res.status_code, 400)

        with patch.object(Team, "save", side_effect=IntegrityError("unique_team_name_per_project")):
            upd = self.pm.patch(self.f.url(f"teams/{self.team_a.id}/"), {"name": "Team Race"}, format="json")
            self.assertEqual(upd.status_code, 400)

    def test_add_member_and_transfer_lock_team_before_user(self):
        with CaptureQueriesContext(connection) as q_add:
            res = self.pm.post(
                self.f.url(f"teams/{self.team_a.id}/add-member/"),
                {"user": self.f.ann1.id},
                format="json",
            )
        self.assertEqual(res.status_code, 201, res.data)
        locks = [q["sql"] for q in q_add if "FOR UPDATE" in q["sql"]]
        self.assertGreaterEqual(len(locks), 2)
        self.assertIn("teams_team", locks[0])
        self.assertIn("accounts_user", locks[1])

        with CaptureQueriesContext(connection) as q_tr:
            tr = self.pm.post(
                self.f.url("teams/transfer/"),
                {"user": self.f.ann1.id, "to_team": self.team_b.id},
                format="json",
            )
        self.assertEqual(tr.status_code, 200, tr.data)
        tr_locks = [q["sql"] for q in q_tr if "FOR UPDATE" in q["sql"]]
        self.assertGreaterEqual(len(tr_locks), 2)
        self.assertIn("teams_team", tr_locks[0])
        self.assertIn("accounts_user", tr_locks[1])

    def test_transfer_to_team_id_oracle_uniform_for_foreign_and_missing_ids(self):
        other = ProjectFixture(name="team_oracle")
        other_team = Team.objects.create(project=other.project, name="Other Team")
        foreign_team_id = other_team.id
        missing_team_id = foreign_team_id + 99999

        r_foreign = self.pm.post(
            self.f.url("teams/transfer/"),
            {"user": self.f.ann1.id, "to_team": foreign_team_id},
            format="json",
        )
        r_missing = self.pm.post(
            self.f.url("teams/transfer/"),
            {"user": self.f.ann1.id, "to_team": missing_team_id},
            format="json",
        )
        self.assertEqual(r_foreign.status_code, 400)
        self.assertEqual(r_missing.status_code, 400)
        self.assertEqual(r_foreign.data, r_missing.data)
