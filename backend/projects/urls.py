from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

# Các route lồng trong dự án dùng tiền tố regex có project_id → view nhận kwargs["project_id"].
P = r"projects/(?P<project_id>\d+)"

router = DefaultRouter()
router.register("projects", views.ProjectViewSet, basename="project")
router.register(f"{P}/datasets", views.DatasetViewSet, basename="dataset")
router.register(f"{P}/batches", views.BatchViewSet, basename="batch")
router.register(f"{P}/deliveries", views.DeliveryViewSet, basename="delivery")
router.register(f"{P}/activity", views.ActivityLogViewSet, basename="activity")
router.register(f"{P}/announcements", views.AnnouncementViewSet, basename="announcement")
router.register(f"{P}/guidelines", views.GuidelineViewSet, basename="guideline")

urlpatterns = [
    path("projects/<int:project_id>/settings/", views.ProjectSettingsView.as_view(), name="project-settings"),
    path("projects/<int:project_id>/members/", views.ProjectMembersView.as_view(), name="project-members"),
    path("projects/<int:project_id>/members/<int:user_id>/roles/", views.ProjectMemberRolesView.as_view(),
         name="project-member-roles"),
    path("projects/<int:project_id>/permission-matrix/", views.PermissionMatrixView.as_view(),
         name="project-permission-matrix"),
    path("projects/<int:project_id>/notifications/", views.ProjectNotificationsView.as_view(),
         name="project-notifications"),
    path("projects/<int:project_id>/notifications/mark-read/", views.MarkNotificationsReadView.as_view(),
         name="project-notifications-mark-read"),
] + router.urls
