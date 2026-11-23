from django.urls import path

from . import views

urlpatterns = [
    path("projects/<int:project_id>/overview/", views.ProjectOverviewView.as_view(), name="project-overview"),
    path("projects/<int:project_id>/team-ranking/", views.TeamRankingView.as_view(), name="team-ranking"),
    path("projects/<int:project_id>/member-performance/", views.MemberPerformanceView.as_view(),
         name="member-performance"),
    path("projects/<int:project_id>/qc2-summary/", views.Qc2SummaryView.as_view(), name="qc2-summary"),
]
