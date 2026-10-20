
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from pathlib import Path
from .storage import store_medical_report
from .serializers import MedicalReportUploadSerializer
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (
    Case,
    PatientIntake,
    Appointment,
    CaseAttachment,
    ConsentRecord,
    AIResult,
    ClinicianReview,
    CaseActivity,
)
from .serializers import (
    CaseSerializer,
    PatientIntakeSerializer,
    AppointmentSerializer,
    CaseAttachmentSerializer,
    ConsentRecordSerializer,
    AIResultSerializer,
    ClinicianReviewSerializer,
    CaseActivitySerializer,
)
from .permissions import HasValidRole, IsClinician


def is_clinician(user):
    return user.groups.filter(name="Clinician").exists()


class CaseViewSet(viewsets.ModelViewSet):
    serializer_class = CaseSerializer
    permission_classes = [IsAuthenticated, HasValidRole]

    def get_serializer_class(self):
        if getattr(self, "action", None) == "intake":
            return PatientIntakeSerializer
        return super().get_serializer_class()
  
    def get_queryset(self):
        queryset = Case.objects.select_related(
            "owner", "assigned_clinician"
        )
        if is_clinician(self.request.user):
            return queryset
        return queryset.filter(owner=self.request.user)


    
    @action(detail=True, methods=["post"], url_path="attachments")
    def upload_attachment(self, request, pk=None):
        case = self.get_object()

        if is_clinician(request.user):
            raise PermissionDenied("Only patients can upload reports.")

        if not case.owner_id or case.owner_id != request.user.id:
            raise PermissionDenied("You can only upload reports to your own case.")

        # Require active consent before storing medical information.
        has_consent = ConsentRecord.objects.filter(
            case=case,
            user=request.user,
            granted=True,
            withdrawn_at__isnull=True,
        ).exists()

        if not has_consent:
            raise PermissionDenied("Active consent is required before uploading reports.")

        serializer = MedicalReportUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        upload = serializer.validated_data["file"]

        # Validate file signatures, not only the client-supplied MIME type.
        header = upload.read(8)
        upload.seek(0)

        is_pdf = header.startswith(b"%PDF-")
        is_jpeg = header.startswith(b"\xff\xd8\xff")
        is_png = header.startswith(b"\x89PNG\r\n\x1a\n")

        if not (is_pdf or is_jpeg or is_png):
            raise ValidationError({"file": "File contents do not match an allowed format."})

        stored = store_medical_report(upload)

        attachment = CaseAttachment.objects.create(
            case=case,
            uploaded_by=request.user,
            original_filename=Path(upload.name).name,
            content_type=upload.content_type,
            size_bytes=stored["size_bytes"],
            storage_key=stored["storage_key"],
            sha256=stored["sha256"],
        )

        CaseActivity.objects.create(
            case=case,
            actor=request.user,
            action="ATTACHMENT_UPLOADED",
        )

        return Response(
            CaseAttachmentSerializer(attachment).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        if not is_clinician(request.user):
            raise PermissionDenied("Patients cannot edit cases.")
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if not is_clinician(request.user):
            raise PermissionDenied("Patients cannot edit cases.")
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not is_clinician(request.user):
            raise PermissionDenied("Patients cannot delete cases.")
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer):
        if is_clinician(self.request.user):
            raise PermissionDenied("Clinicians cannot create patient cases here.")
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=["patch"], permission_classes=[IsAuthenticated, HasValidRole])
    def update_status(self, request, pk=None):
        case = self.get_object()

        if not is_clinician(request.user):
            raise PermissionDenied("Only clinicians can change case status.")

        new_status = request.data.get("status")
        if new_status not in Case.Status.values:
            raise ValidationError({"status": "Invalid status."})

        transitions = {
            "NEEDS_REVIEW": ["IN_REVIEW", "NEEDS_INFORMATION", "ESCALATED"],
            "PROCESSING": ["NEEDS_REVIEW", "NEEDS_INFORMATION", "ESCALATED"],
            "IN_REVIEW": ["APPROVED", "NEEDS_INFORMATION", "ESCALATED"],
            "NEEDS_INFORMATION": ["IN_REVIEW", "ESCALATED"],
            "ESCALATED": ["IN_REVIEW"],
            "APPROVED": [],
        }

        if new_status not in transitions.get(case.status, []):
            raise ValidationError({
                "status": f"Transition from {case.status} to {new_status} is not allowed."
            })

        old_status = case.status
        with transaction.atomic():
            case.status = new_status
            case.save(update_fields=["status", "updated_at"])
            CaseActivity.objects.create(
                case=case,
                actor=request.user,
                action="STATUS_CHANGED",
                old_status=old_status,
                new_status=new_status,
            )

        return Response(self.get_serializer(case).data)

    @action(detail=True, methods=["get", "put", "patch"])
    def intake(self, request, pk=None):
        case = self.get_object()

        if request.method == "GET":
            intake = PatientIntake.objects.filter(case=case).first()

            if not intake:
                return Response(
                    {"detail": "No intake submitted yet."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            return Response(PatientIntakeSerializer(intake).data)

        if is_clinician(request.user):
            raise PermissionDenied("Patients must submit intake details.")

        intake, _ = PatientIntake.objects.get_or_create(case=case)
        serializer = PatientIntakeSerializer(
            intake,
            data=request.data,
            partial=request.method == "PATCH",
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(PatientIntakeSerializer(intake).data)
    
    @action(detail=True, methods=["get"], permission_classes=[IsAuthenticated, IsClinician])
    def activities(self, request, pk=None):
        case = self.get_object()
        activities = case.activities.select_related("actor").order_by("-timestamp")
        return Response(CaseActivitySerializer(activities, many=True).data)

    @action(detail=True, methods=["get"], permission_classes=[IsAuthenticated, IsClinician])
    def ai_results(self, request, pk=None):
        case = self.get_object()
        results = case.ai_results.order_by("-created_at")
        return Response(AIResultSerializer(results, many=True).data)

    @action(detail=True, methods=["get", "post"])
    def consent(self, request, pk=None):
        case = self.get_object()

        if request.method == "GET":
            records = case.consentrecord_set.filter(user=request.user).order_by("-created_at")
            return Response(ConsentRecordSerializer(records, many=True).data)

        if is_clinician(request.user):
            raise PermissionDenied("Consent must be recorded by the patient.")

        if request.data.get("granted") is not True:
            raise ValidationError({"granted": "Explicit consent must be true."})

        record = ConsentRecord.objects.create(
            case=case,
            user=request.user,
            purpose=request.data.get("purpose", "CareFlow case processing"),
            notice_version=request.data.get("notice_version", "1.0"),
            granted=True,
            granted_at=timezone.now(),
        )
        return Response(
            ConsentRecordSerializer(record).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], permission_classes=[IsAuthenticated, IsClinician])
    def reviews(self, request, pk=None):
        case = self.get_object()
        reviews = case.clinicianreview_set.select_related("reviewer").order_by("-created_at")
        return Response(ClinicianReviewSerializer(reviews, many=True).data)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsClinician])
    def add_review(self, request, pk=None):
        case = self.get_object()
        serializer = ClinicianReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        decision = serializer.validated_data["decision"]
        if decision not in [
            Case.Status.IN_REVIEW,
            Case.Status.NEEDS_INFORMATION,
            Case.Status.ESCALATED,
            Case.Status.APPROVED,
        ]:
            raise ValidationError({"decision": "Invalid review decision."})

        with transaction.atomic():
            review = serializer.save(
                case=case,
                reviewer=request.user,
                approved_at=timezone.now() if decision == Case.Status.APPROVED else None,
            )
            old_status = case.status
            case.status = decision
            case.save(update_fields=["status", "updated_at"])
            CaseActivity.objects.create(
                case=case,
                actor=request.user,
                action="CLINICIAN_REVIEW",
                old_status=old_status,
                new_status=decision,
            )

        return Response(
            ClinicianReviewSerializer(review).data,
            status=status.HTTP_201_CREATED,
        )


class AppointmentViewSet(viewsets.ModelViewSet):
    serializer_class = AppointmentSerializer
    permission_classes = [IsAuthenticated, HasValidRole]

    def get_queryset(self):
        user = self.request.user
        queryset = Appointment.objects.select_related("patient", "clinician", "case")
        if is_clinician(user):
            return queryset
        return queryset.filter(patient=user)

    def perform_create(self, serializer):
        if is_clinician(self.request.user):
            raise PermissionDenied("Patients create appointment requests.")
        serializer.save(patient=self.request.user, status="REQUESTED")


class CaseAttachmentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CaseAttachmentSerializer
    permission_classes = [IsAuthenticated, HasValidRole]

    def get_queryset(self):
        user = self.request.user
        queryset = CaseAttachment.objects.select_related(
            "case", "uploaded_by"
        )

        if is_clinician(user):
            return queryset.filter(case__assigned_clinician=user)

        return queryset.filter(case__owner=user)


class ConsentRecordViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ConsentRecordSerializer
    permission_classes = [IsAuthenticated, HasValidRole]

    def get_queryset(self):
        queryset = ConsentRecord.objects.select_related("case", "user")
        if is_clinician(self.request.user):
            return queryset
        return queryset.filter(user=self.request.user)

    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        record = self.get_object()

        if record.user_id != request.user.id:
            raise PermissionDenied("Only the consenting user can withdraw consent.")

        if record.withdrawn_at is None:
            record.withdrawn_at = timezone.now()
            record.save(update_fields=["withdrawn_at"])

        return Response(ConsentRecordSerializer(record).data)


class ClinicianReviewViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ClinicianReviewSerializer
    permission_classes = [IsAuthenticated, IsClinician]

    def get_queryset(self):
        return ClinicianReview.objects.select_related("case", "reviewer", "ai_result")


class AIResultViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AIResultSerializer
    permission_classes = [IsAuthenticated, IsClinician]

    def get_queryset(self):
        return AIResult.objects.select_related("case").order_by("-created_at")
