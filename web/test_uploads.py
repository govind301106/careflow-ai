
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from unittest.mock import patch
from django.utils import timezone
from .models import CaseAttachment
from django.core.files.storage import FileSystemStorage
from tempfile import TemporaryDirectory
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Case, ConsentRecord

User = get_user_model()


class MedicalReportSecurityTests(APITestCase):
    def setUp(self):
        patient_group, _ = Group.objects.get_or_create(name="Patient")

        self.patient = User.objects.create_user(
            username="upload_patient",
            password="test-password-123",
        )
        self.patient.groups.add(patient_group)

        self.other_patient = User.objects.create_user(
            username="other_patient",
            password="test-password-123",
        )
        self.other_patient.groups.add(patient_group)

        self.case = Case.objects.create(
            owner=self.patient,
            patient_name="Test Patient",
            description="Test case",
        )

    @patch("web.downloads.private_storage")
    def test_other_patient_cannot_download_attachment(self, mock_storage):
        from .models import CaseAttachment

        attachment = CaseAttachment.objects.create(
            case=self.case,
            uploaded_by=self.patient,
            original_filename="report.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key="medical_reports/private-test",
            sha256="a" * 64,
        )

        self.client.force_authenticate(user=self.other_patient)

        response = self.client.get(
            f"/api/attachments/{attachment.id}/download/"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        mock_storage.open.assert_not_called()

    @patch("web.downloads.private_storage")
    def test_assigned_clinician_can_download_attachment(self, mock_storage):
        clinician_group, _ = Group.objects.get_or_create(name="Clinician")
        clinician = User.objects.create_user(
            username="assigned_clinician",
            password="test-password-123",
        )
        clinician.groups.add(clinician_group)

        self.case.assigned_clinician = clinician
        self.case.save(update_fields=["assigned_clinician"])

        from .models import CaseAttachment
        attachment = CaseAttachment.objects.create(
            case=self.case,
            uploaded_by=self.patient,
            original_filename="report.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_key="medical_reports/private-test",
            sha256="a" * 64,
        )

        mock_storage.exists.return_value = True
        mock_storage.open.return_value = __import__("io").BytesIO(b"test report")

        self.client.force_authenticate(user=clinician)
        response = self.client.get(
            f"/api/attachments/{attachment.id}/download/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_storage.open.assert_called_once_with(
            attachment.storage_key, "rb"
        )

    def grant_consent(self):
        ConsentRecord.objects.create(
            case=self.case,
            user=self.patient,
            purpose="CareFlow report upload",
            notice_version="1.0",
            granted=True,
            granted_at=timezone.now(),
        )
    def test_upload_without_consent_is_rejected(self):
        self.client.force_authenticate(user=self.patient)

        upload = SimpleUploadedFile(
            "report.pdf",
            b"%PDF-1.4 test content",
            content_type="application/pdf",
        )

        response = self.client.post(
            f"/api/cases/{self.case.id}/attachments/",
            {"file": upload},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


    def test_other_patient_cannot_access_case_attachments(self):
        self.client.force_authenticate(user=self.other_patient)

        # The case-specific endpoint is POST-only for uploads.
        response = self.client.post(
            f"/api/cases/{self.case.id}/attachments/",
            {},
            format="multipart",
        )

        # It must not allow another patient to upload to this case.
        self.assertIn(
            response.status_code,
            [
                status.HTTP_403_FORBIDDEN,
                status.HTTP_404_NOT_FOUND,
                status.HTTP_405_METHOD_NOT_ALLOWED,
            ],
        )



    @patch("web.views.store_medical_report")
    def test_valid_pdf_upload_succeeds(self, mock_store):
        self.client.force_authenticate(user=self.patient)
        self.grant_consent()

        mock_store.return_value = {
            "storage_key": "medical_reports/test-report",
            "sha256": "a" * 64,
            "size_bytes": 21,
        }

        upload = SimpleUploadedFile(
            "report.pdf",
            b"%PDF-1.4 test content",
            content_type="application/pdf",
        )

        response = self.client.post(
            f"/api/cases/{self.case.id}/attachments/",
            {"file": upload},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            CaseAttachment.objects.filter(
                case=self.case,
                uploaded_by=self.patient,
            ).exists()
        )
        mock_store.assert_called_once()

    @patch("web.views.store_medical_report")
    def test_fake_pdf_is_rejected(self, mock_store):
        self.client.force_authenticate(user=self.patient)
        self.grant_consent()

        upload = SimpleUploadedFile(
            "fake.pdf",
            b"this is not a PDF",
            content_type="application/pdf",
        )

        response = self.client.post(
            f"/api/cases/{self.case.id}/attachments/",
            {"file": upload},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_store.assert_not_called()

    def test_private_file_upload_and_authorized_download_round_trip(self):
        from web.storage import private_storage

        self.client.force_authenticate(user=self.patient)
        self.grant_consent()
        content = b"%PDF-1.4 private test report"

        with TemporaryDirectory() as upload_root:
            with patch.object(private_storage, "_location", upload_root):
                upload = SimpleUploadedFile(
                    "private-report.pdf", content, content_type="application/pdf"
                )
                uploaded = self.client.post(
                    f"/api/cases/{self.case.pk}/attachments/",
                    {"file": upload},
                    format="multipart",
                )
                self.assertEqual(uploaded.status_code, status.HTTP_201_CREATED)

                downloaded = self.client.get(
                    f"/api/attachments/{uploaded.data['id']}/download/"
                )
                self.assertEqual(downloaded.status_code, status.HTTP_200_OK)
                self.assertEqual(b"".join(downloaded.streaming_content), content)

                self.client.force_authenticate(user=self.other_patient)
                denied = self.client.get(
                    f"/api/attachments/{uploaded.data['id']}/download/"
                )
                self.assertEqual(denied.status_code, status.HTTP_404_NOT_FOUND)
