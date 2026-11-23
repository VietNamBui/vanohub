from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

P = r"projects/(?P<project_id>\d+)"

router = SimpleRouter()
router.register(f"{P}/error-categories", views.ErrorCategoryViewSet, basename="error-category")
router.register(f"{P}/audits", views.AuditViewSet, basename="audit")
router.register(f"{P}/audit-samples", views.AuditSampleViewSet, basename="audit-sample")

urlpatterns = [
    path("projects/<int:project_id>/audit-strategy/", views.AuditStrategyView.as_view(), name="audit-strategy"),
] + router.urls
