
from pathlib import Path

from django.http import FileResponse
from django.utils.http import content_disposition_header
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from .models import CaseAttachment
from .storage import private_storage
from .views import is_clinician


class AttachmentDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, attachment_id):
        attachment = (
            CaseAttachment.objects
            .select_related("case")
            .filter(pk=attachment_id)
            .first()
        )

        if attachment is None:
            raise NotFound("Attachment not found.")

        if is_clinician(request.user):
            if attachment.case.assigned_clinician_id != request.user.id:
                raise NotFound("Attachment not found.")
        elif attachment.case.owner_id != request.user.id:
            raise NotFound("Attachment not found.")

        if not private_storage.exists(attachment.storage_key):
            raise NotFound("Stored file not found.")

        file_handle = private_storage.open(attachment.storage_key, "rb")
        response = FileResponse(
            file_handle,
            content_type="application/octet-stream",
        )
        filename = Path(attachment.original_filename).name
        response["Content-Disposition"] = content_disposition_header(True, filename)
        response["X-Content-Type-Options"] = "nosniff"
        return response
