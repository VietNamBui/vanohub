from django.urls import path

from . import views

urlpatterns = [
    path("status/", views.status, name="cvat-status"),
    path("link/", views.link, name="cvat-link"),
    path("sync-organizations/", views.sync_organizations_view, name="cvat-sync-organizations"),
]
