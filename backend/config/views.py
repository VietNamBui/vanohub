from django.db import DatabaseError, connection
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def health(request: HttpRequest) -> JsonResponse:
    """Unauthenticated readiness probe verifying PostgreSQL connectivity only."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        response = JsonResponse({"status": "error", "database": "unavailable"}, status=503)
    else:
        response = JsonResponse({"status": "ok", "database": "ok"}, status=200)
    response["Cache-Control"] = "no-store"
    return response
