from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register(r"projects/(?P<project_id>\d+)/jobs", views.JobViewSet, basename="job")

urlpatterns = [
    path("projects/<int:project_id>/job-queue/", views.JobQueueView.as_view(), name="job-queue"),
] + router.urls
