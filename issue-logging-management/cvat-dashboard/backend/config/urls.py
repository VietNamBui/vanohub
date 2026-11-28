from __future__ import annotations

from dashboard.views import SpaEntryView
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("dashboard.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.BASE_DIR / "static")
    vite_assets = settings.PROJECT_ROOT / "frontend" / "dist" / "assets"
    if vite_assets.is_dir():
        urlpatterns += static("/assets/", document_root=vite_assets)

urlpatterns += [
    re_path(r"^(?!api/|admin/|static/|assets/).*$", SpaEntryView.as_view(), name="spa-entry"),
]
