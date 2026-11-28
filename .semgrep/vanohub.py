# Semgrep rule unit tests for VanoHub backend rules


def test_roles():
    # ruleid: vanohub.backend.no-removed-roles
    bad_role = Role.DIRECTOR
    # ruleid: vanohub.backend.no-removed-roles
    bad_role_2 = Role.TEAM_LEADER
    # ok: vanohub.backend.no-removed-roles
    good_role = Role.QC2
    return bad_role, bad_role_2, good_role


def test_cvat_redirects(self, requests):
    # ruleid: vanohub.backend.cvat-allow-redirects-true
    self.session.request("GET", "https://cvat/api/jobs", allow_redirects=True)
    # ruleid: vanohub.backend.cvat-request-missing-allow-redirects-false
    self.session.request("GET", "https://cvat/api/jobs", timeout=10)
    # ok: vanohub.backend.cvat-request-missing-allow-redirects-false
    self.session.request("GET", "https://cvat/api/jobs", timeout=10, allow_redirects=False)


def test_select_for_update(Job):
    # ruleid: vanohub.backend.select-for-update-with-select-related-no-of
    Job.objects.select_related("batch").select_for_update()
    # ruleid: vanohub.backend.select-for-update-with-select-related-no-of
    Job.objects.select_for_update().select_related("batch")
    # ruleid: vanohub.backend.select-for-update-with-select-related-no-of
    Job.objects.select_related("batch").filter(id=1).select_for_update()
    # ok: vanohub.backend.select-for-update-with-select-related-no-of
    Job.objects.select_related("batch").select_for_update(of=("self",))
    # ok: vanohub.backend.select-for-update-with-select-related-no-of
    Job.objects.select_for_update(of=("self",)).select_related("batch")


def test_raw_sql(cursor, user_id):
    # ruleid: vanohub.backend.raw-sql-interpolation
    cursor.execute(f"SELECT * FROM jobs WHERE id = {user_id}")
    # ruleid: vanohub.backend.raw-sql-interpolation
    cursor.execute("SELECT * FROM jobs WHERE id = {}".format(user_id))
    # ok: vanohub.backend.raw-sql-interpolation
    cursor.execute("SELECT * FROM jobs WHERE id = %s", [user_id])
