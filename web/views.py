
import logging
from django.db import DatabaseError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.contrib.auth.models import Group
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
import json
import os
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
    IntakeChatMessage,
    ClinicianRegistration,
)
from .serializers import (
    CaseSerializer,
    PatientIntakeSerializer,
    AppointmentSerializer,
    CaseAttachmentSerializer,
    ConsentRecordSerializer,
    AIResultSerializer,
    ClinicianReviewSerializer,
    PatientReviewSerializer,
    PatientAIResultSerializer,
    CaseActivitySerializer,
)
from .permissions import HasValidRole, IsClinician

logger = logging.getLogger(__name__)


def is_clinician(user):
    return user.groups.filter(name="Clinician").exists()


@ensure_csrf_cookie
@require_GET
def current_user(request):
    if not request.user.is_authenticated:
        return JsonResponse({"authenticated": False})
    return JsonResponse({
        "authenticated": True,
        "id": request.user.pk,
        "username": request.user.get_username(),
        "full_name": request.user.get_full_name(),
        "email": request.user.email,
        "role": "pending_clinician" if hasattr(request.user, "clinician_registration") and request.user.clinician_registration.status == "PENDING" else ("admin" if request.user.is_staff else ("clinician" if is_clinician(request.user) else "patient")),
        "approval_status": request.user.clinician_registration.status.lower() if hasattr(request.user, "clinician_registration") else None,
        "is_staff": request.user.is_staff,
    })


@csrf_protect
@require_POST
def patient_registration(request):
    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)
    username = str(data.get("username", "")).strip()
    full_name = str(data.get("full_name", "")).strip()
    email = str(data.get("email", "")).strip()
    password = data.get("password", "")
    confirmation = data.get("password_confirmation", "")
    errors = {}
    User = get_user_model()
    candidate = User(username=username, email=email, first_name=full_name[:150])
    if not username: errors["username"] = ["Username is required."]
    elif User.objects.filter(username__iexact=username).exists(): errors["username"] = ["This username is already in use."]
    else:
        try: User._meta.get_field("username").clean(username, candidate)
        except DjangoValidationError as exc: errors["username"] = list(exc.messages)
    if not full_name: errors["full_name"] = ["Full name is required."]
    if email and User.objects.filter(email__iexact=email).exists(): errors["email"] = ["This email is already in use."]
    elif email:
        try: validate_email(email)
        except DjangoValidationError as exc: errors["email"] = list(exc.messages)
    if password != confirmation: errors["password_confirmation"] = ["Passwords do not match."]
    if password:
        try: validate_password(password, candidate)
        except DjangoValidationError as exc: errors["password"] = list(exc.messages)
    else: errors["password"] = ["Password is required."]
    account_type = data.get("account_type", "patient")
    if account_type not in ("patient", "clinician"):
        errors["account_type"] = ["Choose patient or clinician registration."]
    elif account_type == "clinician" and not email:
        errors["email"] = ["Email is required for clinician registration."]
    if errors: return JsonResponse(errors, status=400)
    user = User.objects.create_user(username=username, email=email, password=password, first_name=full_name[:150])
    if account_type == "clinician":
        ClinicianRegistration.objects.create(user=user)
        login(request, user)
        return JsonResponse({"authenticated": True, "id": user.pk, "username": username, "full_name": user.get_full_name(), "email": email, "role": "pending_clinician", "approval_status": "pending"}, status=201)
    patient_group, _ = Group.objects.get_or_create(name="Patient")
    user.groups.add(patient_group)
    # Public registration never accepts a role or admin privilege from payload.
    login(request, user)
    return JsonResponse({"authenticated": True, "id": user.pk, "username": username, "full_name": user.get_full_name(), "email": email, "role": "patient"}, status=201)


@csrf_protect
@require_POST
def session_login(request):
    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)
    user = authenticate(request, username=data.get("username", ""), password=data.get("password", ""))
    if user is None:
        return JsonResponse({"detail": "Invalid username or password."}, status=400)
    registration = getattr(user, "clinician_registration", None)
    if registration and registration.status == ClinicianRegistration.Status.PENDING:
        login(request, user)
        return JsonResponse({"authenticated": True, "id": user.pk, "username": user.get_username(), "full_name": user.get_full_name(), "email": user.email, "role": "pending_clinician", "approval_status": "pending"})
    if registration and registration.status == ClinicianRegistration.Status.REJECTED:
        return JsonResponse({"detail": "This clinician registration was not approved."}, status=403)
    if not user.is_staff and not user.groups.filter(name__in=["Patient", "Clinician"]).exists():
        return JsonResponse({"detail": "This account has no CareFlow role."}, status=403)
    login(request, user)
    return JsonResponse({
        "authenticated": True,
        "id": user.pk,
        "username": user.get_username(),
        "role": "admin" if user.is_staff else ("clinician" if is_clinician(user) else "patient"),
        "is_staff": user.is_staff,
    })


@require_GET
def pending_clinicians(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({"detail": "Administrator access required."}, status=403)
    items = ClinicianRegistration.objects.filter(status=ClinicianRegistration.Status.PENDING).select_related("user").order_by("created_at")
    return JsonResponse([{"id": item.id, "user_id": item.user_id, "username": item.user.username, "full_name": item.user.get_full_name(), "email": item.user.email, "created_at": item.created_at} for item in items], safe=False)


@csrf_protect
@require_POST
def review_clinician_registration(request, registration_id):
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({"detail": "Administrator access required."}, status=403)
    try:
        data = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)
    decision = data.get("decision")
    if decision not in ("approve", "reject"):
        return JsonResponse({"decision": ["Choose approve or reject."]}, status=400)
    registration = get_object_or_404(ClinicianRegistration, pk=registration_id, status=ClinicianRegistration.Status.PENDING)
    registration.status = ClinicianRegistration.Status.APPROVED if decision == "approve" else ClinicianRegistration.Status.REJECTED
    registration.reviewed_by = request.user
    registration.reviewed_at = timezone.now()
    registration.save(update_fields=["status", "reviewed_by", "reviewed_at"])
    if decision == "approve":
        clinician_group, _ = Group.objects.get_or_create(name="Clinician")
        registration.user.groups.add(clinician_group)
    return JsonResponse({"id": registration.id, "status": registration.status.lower()})


@csrf_protect
@require_POST
def session_logout(request):
    logout(request)
    return JsonResponse({"authenticated": False})


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
            return queryset.filter(Q(assigned_clinician=self.request.user) | Q(assigned_clinician__isnull=True))
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
        if self.get_object().assigned_clinician_id != request.user.id:
            raise PermissionDenied("Assign the case to yourself before editing it.")
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if not is_clinician(request.user):
            raise PermissionDenied("Patients cannot edit cases.")
        if self.get_object().assigned_clinician_id != request.user.id:
            raise PermissionDenied("Assign the case to yourself before editing it.")
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not is_clinician(request.user):
            raise PermissionDenied("Patients cannot delete cases.")
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer):
        if is_clinician(self.request.user):
            raise PermissionDenied("Clinicians cannot create patient cases here.")
        case = serializer.save(owner=self.request.user)
        CaseActivity.objects.create(case=case, actor=self.request.user, action="CASE_SUBMITTED")

    @action(detail=True, methods=["patch"], permission_classes=[IsAuthenticated, IsClinician])
    def assign(self, request, pk=None):
        case = self.get_object()
        clinician_id = request.data.get("clinician_id", request.user.pk)
        from django.contrib.auth import get_user_model
        clinician = get_object_or_404(get_user_model(), pk=clinician_id)
        if not clinician.groups.filter(name="Clinician").exists():
            raise ValidationError({"clinician_id": "The selected user is not a clinician."})
        case.assigned_clinician = clinician
        case.save(update_fields=["assigned_clinician", "updated_at"])
        CaseActivity.objects.create(case=case, actor=request.user, action="CLINICIAN_ASSIGNED")
        return Response(self.get_serializer(case).data)

    @action(detail=True, methods=["patch"], permission_classes=[IsAuthenticated, HasValidRole])
    def update_status(self, request, pk=None):
        case = self.get_object()

        if not is_clinician(request.user):
            raise PermissionDenied("Only clinicians can change case status.")
        if case.assigned_clinician_id != request.user.id:
            raise PermissionDenied("Assign the case to yourself before changing its status.")

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
            if is_clinician(request.user) and case.assigned_clinician_id != request.user.id:
                raise PermissionDenied("Only the assigned clinician can view intake details.")
            intake = PatientIntake.objects.filter(case=case).first()

            if not intake:
                return Response(
                    {"detail": "No intake submitted yet."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            return Response(PatientIntakeSerializer(intake).data)

        if is_clinician(request.user):
            raise PermissionDenied("Patients must submit intake details.")
        if case.owner_id != request.user.id:
            raise PermissionDenied("You can only submit intake for your own case.")

        intake, _ = PatientIntake.objects.get_or_create(case=case)
        serializer = PatientIntakeSerializer(
            intake,
            data=request.data,
            partial=request.method == "PATCH",
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(PatientIntakeSerializer(intake).data)

    @action(detail=True, methods=["get", "post"], url_path="chat")
    def chat(self, request, pk=None):
        case = self.get_object()
        if is_clinician(request.user) or case.owner_id != request.user.id:
            raise PermissionDenied("Only the patient who owns this case can use intake chat.")
        if request.method == "GET":
            return Response([{"role": m.role, "content": m.content, "mode": m.assistant_mode, "created_at": m.created_at} for m in case.chat_messages.order_by("created_at")])
        if request.data.get("confirm") is True:
            consent_active = case.consent_records.filter(user=request.user, granted=True, withdrawn_at__isnull=True).exists()
            if not consent_active:
                raise PermissionDenied("Active consent is required to confirm intake.")
            intake_data = request.data.get("intake", {})
            intake, _ = PatientIntake.objects.get_or_create(case=case)
            serializer = PatientIntakeSerializer(intake, data=intake_data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save(original_answers={**intake.original_answers, "chat_messages": list(case.chat_messages.filter(role="patient").values_list("content", flat=True))})
            CaseActivity.objects.create(case=case, actor=request.user, action="INTAKE_CONFIRMED")
            return Response({"confirmed": True, "intake": PatientIntakeSerializer(intake).data})
        message = str(request.data.get("message", "")).strip()
        if not message or len(message) > 4000:
            raise ValidationError({"message": "Enter a message of up to 4000 characters."})
        intake, _ = PatientIntake.objects.get_or_create(case=case)
        required = [("symptom_onset", "When did the symptoms start?"), ("duration", "How long have you had them?"), ("severity_description", "How severe do they feel?"), ("progression", "Have they improved, worsened, or stayed the same?"), ("medical_history", "Is there relevant medical history?"), ("current_medications", "What medications are you currently taking?"), ("allergies", "Do you have any known allergies?")]
        missing = [prompt for field, prompt in required if not getattr(intake, field, "").strip()]
        if missing:
            next_field = next(field for field, prompt in required if prompt == missing[0])
            if message.casefold().strip(" .!?\t\r\n") in {"hello", "hi", "hey", "good morning", "good afternoon", "good evening", "thanks", "thank you"}:
                question = missing[0]
                IntakeChatMessage.objects.create(case=case, role="assistant", content=question, assistant_mode="deterministic")
                return Response({"mode": "deterministic", "message": question, "safety": "This intake assistant does not diagnose or replace professional care."})
            IntakeChatMessage.objects.create(case=case, role="patient", content=message)
            setattr(intake, next_field, message)
            intake.save(update_fields=[next_field, "updated_at"])
            missing = [prompt for field, prompt in required if not getattr(intake, field, "").strip()]
        else:
            IntakeChatMessage.objects.create(case=case, role="patient", content=message)
        question = missing[0] if missing else "Thanks. Review your structured intake and confirm it when you are ready."
        IntakeChatMessage.objects.create(case=case, role="assistant", content=question, assistant_mode="deterministic")
        return Response({"mode": "deterministic", "message": question, "safety": "This intake assistant does not diagnose or replace professional care. If you may be experiencing a medical emergency, contact local emergency services now."})
    
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
            records = case.consent_records.filter(user=request.user).order_by("-created_at")
            return Response(ConsentRecordSerializer(records, many=True).data)

        if is_clinician(request.user):
            raise PermissionDenied("Consent must be recorded by the patient.")
        if case.owner_id != request.user.id:
            raise PermissionDenied("You can only manage consent for your own case.")

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
        CaseActivity.objects.create(case=case, actor=request.user, action="CONSENT_GRANTED")
        return Response(
            ConsentRecordSerializer(record).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], permission_classes=[IsAuthenticated, IsClinician])
    def reviews(self, request, pk=None):
        case = self.get_object()
        reviews = case.reviews.select_related("reviewer").order_by("-created_at")
        return Response(ClinicianReviewSerializer(reviews, many=True).data)

    @action(detail=True, methods=["get"], permission_classes=[IsAuthenticated, HasValidRole], url_path="patient-review")
    def patient_review(self, request, pk=None):
        case = self.get_object()
        if is_clinician(request.user) or case.owner_id != request.user.id:
            raise PermissionDenied("Only the patient who owns this case can view its review.")
        try:
            latest_review = case.reviews.order_by("-created_at").first()
        except DatabaseError:
            logger.exception("Unable to load patient-visible review for case_id=%s user_id=%s", case.pk, request.user.pk)
            return Response(
                {"status": "error", "detail": "Review information is temporarily unavailable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if not latest_review:
            return Response({"status": "pending", "review": None})
        if not latest_review.is_finalized:
            return Response({"status": "in_review", "review": None})
        return Response({"status": "completed", "review": PatientReviewSerializer(latest_review).data})

    @action(detail=True, methods=["get"], permission_classes=[IsAuthenticated, HasValidRole], url_path="patient-ai-suggestions")
    def patient_ai_suggestions(self, request, pk=None):
        case = self.get_object()
        if is_clinician(request.user) or case.owner_id != request.user.id:
            raise PermissionDenied("Only the patient who owns this case can view its AI suggestions.")
        try:
            result = case.ai_results.order_by("-created_at").first()
        except DatabaseError:
            logger.exception("Unable to load patient AI suggestions for case_id=%s user_id=%s", case.pk, request.user.pk)
            return Response({"status": "error", "detail": "AI suggestions are temporarily unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if result is None:
            state = "not_configured" if not os.getenv("AI_PIPELINE_URL", "").strip() else "not_started"
            return Response({"status": state, "result": None})
        if result.status == AIResult.ProcessingStatus.PENDING:
            return Response({"status": "in_progress", "result": None})
        if result.status == AIResult.ProcessingStatus.FAILED:
            return Response({"status": "failed", "result": None})
        if result.status != AIResult.ProcessingStatus.COMPLETED or not result.is_validated:
            return Response({"status": "unavailable", "result": None})
        return Response({"status": "completed", "result": PatientAIResultSerializer(result).data})

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsClinician])
    def add_review(self, request, pk=None):
        case = self.get_object()
        if case.assigned_clinician_id != request.user.id:
            raise PermissionDenied("Assign the case to yourself before reviewing it.")
        serializer = ClinicianReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        decision = serializer.validated_data["decision"]
        is_finalized = decision != Case.Status.IN_REVIEW
        if is_finalized and not serializer.validated_data.get("patient_comments", "").strip():
            raise ValidationError({"patient_comments": "Patient-facing comments are required to finalize a review."})
        ai_result = serializer.validated_data.get("ai_result")
        if ai_result and ai_result.case_id != case.pk:
            raise ValidationError({"ai_result": "The AI result must belong to this case."})
        if decision not in [
            Case.Status.IN_REVIEW,
            Case.Status.NEEDS_INFORMATION,
            Case.Status.ESCALATED,
            Case.Status.APPROVED,
        ]:
            raise ValidationError({"decision": "Invalid review decision."})

        allowed = {
            "NEEDS_REVIEW": {"IN_REVIEW", "NEEDS_INFORMATION", "ESCALATED"},
            "PROCESSING": {"NEEDS_REVIEW", "NEEDS_INFORMATION", "ESCALATED"},
            "IN_REVIEW": {"APPROVED", "NEEDS_INFORMATION", "ESCALATED"},
            "NEEDS_INFORMATION": {"IN_REVIEW", "ESCALATED"},
            "ESCALATED": {"IN_REVIEW"}, "APPROVED": set(),
        }
        if decision not in allowed.get(case.status, set()):
            raise ValidationError({"decision": f"Transition from {case.status} to {decision} is not allowed."})

        with transaction.atomic():
            review = serializer.save(
                case=case,
                reviewer=request.user,
                is_finalized=is_finalized,
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
            return queryset.filter(Q(clinician=user) | Q(clinician__isnull=True))
        return queryset.filter(patient=user)

    def perform_create(self, serializer):
        if is_clinician(self.request.user):
            raise PermissionDenied("Patients create appointment requests.")
        case = serializer.validated_data.get("case")
        if case and case.owner_id != self.request.user.id:
            raise PermissionDenied("You can only request appointments for your own case.")
        serializer.save(patient=self.request.user, clinician=None, status="REQUESTED")

    def update(self, request, *args, **kwargs):
        if not is_clinician(request.user):
            raise PermissionDenied("Only clinicians can update appointment requests.")
        appointment = self.get_object()
        if appointment.clinician_id not in (None, request.user.id):
            raise PermissionDenied("This appointment belongs to another clinician.")
        if request.data.get("clinician") not in (None, str(request.user.pk), request.user.pk):
            raise ValidationError({"clinician": "An appointment can only be assigned to you."})
        response = super().update(request, *args, **kwargs)
        if appointment.clinician_id is None:
            appointment.clinician = request.user
            appointment.save(update_fields=["clinician"])
            response.data["clinician"] = request.user.pk
        return response

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)


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
            return queryset.filter(case__assigned_clinician=self.request.user)
        return queryset.filter(user=self.request.user)

    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        record = self.get_object()

        if record.user_id != request.user.id:
            raise PermissionDenied("Only the consenting user can withdraw consent.")

        if record.withdrawn_at is None:
            record.withdrawn_at = timezone.now()
            record.save(update_fields=["withdrawn_at"])
            CaseActivity.objects.create(case=record.case, actor=request.user, action="CONSENT_WITHDRAWN")

        return Response(ConsentRecordSerializer(record).data)


class ClinicianReviewViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ClinicianReviewSerializer
    permission_classes = [IsAuthenticated, IsClinician]

    def get_queryset(self):
        return ClinicianReview.objects.select_related("case", "reviewer", "ai_result").filter(case__assigned_clinician=self.request.user)


class AIResultViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AIResultSerializer
    permission_classes = [IsAuthenticated, IsClinician]

    def get_queryset(self):
        return AIResult.objects.select_related("case").filter(case__assigned_clinician=self.request.user).order_by("-created_at")
