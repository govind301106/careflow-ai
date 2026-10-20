
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CaseViewSet,
    AppointmentViewSet,
    CaseAttachmentViewSet,
    ConsentRecordViewSet,
    ClinicianReviewViewSet,
    AIResultViewSet,
)
from .downloads import AttachmentDownloadView

router = DefaultRouter()
router.register("cases", CaseViewSet, basename="case")
router.register("appointments", AppointmentViewSet, basename="appointment")
router.register("attachments", CaseAttachmentViewSet, basename="attachment")
router.register("consents", ConsentRecordViewSet, basename="consent")
router.register("reviews", ClinicianReviewViewSet, basename="review")
router.register("ai-results", AIResultViewSet, basename="ai-result")

urlpatterns = [
    path(
        "attachments/<int:attachment_id>/download/",
        AttachmentDownloadView.as_view(),
        name="attachment-download",
    ),
    path("", include(router.urls)),
]
