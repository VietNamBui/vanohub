from django.contrib import admin
from django.urls import include, path

from . import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/health/', views.health, name='health'),
    # Toàn bộ REST API đặt dưới tiền tố /api/. Mỗi app tự khai báo URL của mình.
    path('api/auth/', include('accounts.urls')),
    path('api/', include('projects.urls')),
    path('api/', include('teams.urls')),
    path('api/', include('jobs.urls')),
    path('api/', include('quality.urls')),
    path('api/', include('analytics.urls')),
    path('api/cvat/', include('cvat_integration.urls')),
]
