from rest_framework.routers import SimpleRouter

from . import views

P = r"projects/(?P<project_id>\d+)"

router = SimpleRouter()
router.register(f"{P}/teams", views.TeamViewSet, basename="team")

urlpatterns = router.urls
