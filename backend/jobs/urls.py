from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register(r"projects/(?P<project_id>\d+)/jobs", views.JobViewSet, basename="job")
router.register(r"projects/(?P<project_id>\d+)/annotator/jobs", views.AnnotatorJobViewSet, basename="annotator-job")
router.register(
    r"projects/(?P<project_id>\d+)/annotator/requests",
    views.AnnotatorRequestViewSet,
    basename="annotator-request",
)

urlpatterns = [
    path("projects/<int:project_id>/job-queue/", views.JobQueueView.as_view(), name="job-queue"),
    path("projects/<int:project_id>/annotator/search/", views.AnnotatorQuickSearchView.as_view(), name="annotator-search"),
] + router.urls
