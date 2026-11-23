from django.urls import path
from rest_framework.routers import SimpleRouter

from . import leader_views, views

P = r"projects/(?P<project_id>\d+)"

router = SimpleRouter()
router.register(f"{P}/teams", views.TeamViewSet, basename="team")
router.register(f"{P}/leader/jobs", leader_views.LeaderJobViewSet, basename="leader-job")

urlpatterns = [
    path("projects/<int:project_id>/leader/teams/", leader_views.LeaderTeamsView.as_view(), name="leader-teams"),
    path("projects/<int:project_id>/leader/dashboard/", leader_views.LeaderDashboardView.as_view(), name="leader-dashboard"),
    path("projects/<int:project_id>/leader/teams/<int:team_id>/members/<int:user_id>/qc1/",
         leader_views.LeaderMemberQc1View.as_view(), name="leader-member-qc1"),
] + router.urls
