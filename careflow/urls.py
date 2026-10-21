
from django.contrib import admin
from django.urls import include, path
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import JsonResponse
from web.views import current_user, patient_registration, session_login, session_logout, pending_clinicians, review_clinician_registration


@ensure_csrf_cookie
def csrf(request):
    return JsonResponse({"detail": "CSRF cookie set"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/csrf/", csrf, name="csrf"),
    path("api/auth/me/", current_user, name="current-user"),
    path("api/auth/register/", patient_registration, name="patient-registration"),
    path("api/auth/login/", session_login, name="session-login"),
    path("api/auth/logout/", session_logout, name="session-logout"),
    path("api/admin/clinician-requests/", pending_clinicians, name="pending-clinicians"),
    path("api/admin/clinician-requests/<int:registration_id>/review/", review_clinician_registration, name="review-clinician-registration"),
    path("api/", include("web.urls")),
    path("api-auth/", include("rest_framework.urls")),
]
