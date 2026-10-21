
from django.db import models
from django.conf import settings


class ClinicianRegistration(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending approval"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="clinician_registration")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="clinician_requests_reviewed")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Case(models.Model):
    class Status(models.TextChoices):
        NEEDS_REVIEW = "NEEDS_REVIEW", "Needs review"
        PROCESSING = "PROCESSING", "Processing"
        IN_REVIEW = "IN_REVIEW", "In review"
        APPROVED = "APPROVED", "Completed / Reviewed"
        NEEDS_INFORMATION = "NEEDS_INFORMATION", "Needs information"
        ESCALATED = "ESCALATED", "Escalated"

    class Priority(models.TextChoices):
        UNASSESSED = "UNASSESSED", "Unassessed"
        RED = "RED", "Immediate review"
        YELLOW = "YELLOW", "Prompt review"
        GREEN = "GREEN", "No configured warning trigger detected"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cases",
        null=True,
        blank=True,
    )
    assigned_clinician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_cases",
        null=True,
        blank=True,
    )

    patient_name = models.CharField(max_length=100)
    description = models.TextField()
    preferred_language = models.CharField(max_length=50, default="en")
    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.UNASSESSED,
    )
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.NEEDS_REVIEW,
    )
    processing_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Case {self.pk} - {self.patient_name}"


class PatientIntake(models.Model):
    case = models.OneToOneField(
        Case, on_delete=models.CASCADE, related_name="intake"
    )
    symptoms = models.JSONField(default=list, blank=True)
    symptom_onset = models.CharField(max_length=200, blank=True)
    duration = models.CharField(max_length=200, blank=True)
    severity_description = models.TextField(blank=True)
    progression = models.TextField(blank=True)
    medical_history = models.TextField(blank=True)
    current_medications = models.TextField(blank=True)
    allergies = models.TextField(blank=True)
    additional_information = models.TextField(blank=True)
    original_answers = models.JSONField(default=dict, blank=True)
    completeness_flags = models.JSONField(default=list, blank=True)
    contradiction_flags = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class IntakeChatMessage(models.Model):
    """Verbatim patient source messages and labelled deterministic prompts."""
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="chat_messages")
    role = models.CharField(max_length=12, choices=(("patient", "Patient"), ("assistant", "Assistant")))
    content = models.TextField()
    assistant_mode = models.CharField(max_length=30, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Appointment(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        CONFIRMED = "CONFIRMED", "Confirmed"
        CANCELLED = "CANCELLED", "Cancelled"
        COMPLETED = "COMPLETED", "Completed"

    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="patient_appointments",
    )
    clinician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="clinician_appointments",
        null=True,
        blank=True,
    )
    case = models.ForeignKey(
        Case,
        on_delete=models.SET_NULL,
        related_name="appointments",
        null=True,
        blank=True,
    )
    scheduled_at = models.DateTimeField()
    reason = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.REQUESTED,
    )
    created_at = models.DateTimeField(auto_now_add=True)


class CaseAttachment(models.Model):
    class ProcessingStatus(models.TextChoices):
        UPLOADED = "UPLOADED", "Uploaded"
        PROCESSING = "PROCESSING", "Processing"
        PROCESSED = "PROCESSED", "Processed"
        FAILED = "FAILED", "Failed"

    case = models.ForeignKey(
        Case, on_delete=models.CASCADE, related_name="attachments"
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT
    )
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size_bytes = models.PositiveBigIntegerField()
    storage_key = models.CharField(max_length=500, unique=True)
    sha256 = models.CharField(max_length=64, blank=True)
    processing_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.UPLOADED,
    )
    created_at = models.DateTimeField(auto_now_add=True)


class ConsentRecord(models.Model):
    case = models.ForeignKey(
        Case, on_delete=models.PROTECT, related_name="consent_records"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT
    )
    purpose = models.CharField(max_length=100)
    notice_version = models.CharField(max_length=50)
    granted = models.BooleanField(default=False)
    granted_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AIResult(models.Model):
    class ProcessingStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    case = models.ForeignKey(
        Case, on_delete=models.CASCADE, related_name="ai_results"
    )
    status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
    )
    schema_version = models.CharField(max_length=30, blank=True)
    model_name = models.CharField(max_length=100, blank=True)
    structured_output = models.JSONField(default=dict, blank=True)
    evidence = models.JSONField(default=list, blank=True)
    uncertainty_flags = models.JSONField(default=list, blank=True)
    rule_triggers = models.JSONField(default=list, blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    # True only after the saved payload passed the agreed pipeline schema and
    # patient-safety validation. Existing rows remain unavailable by default.
    is_validated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class ClinicianReview(models.Model):
    class Decision(models.TextChoices):
        IN_REVIEW = "IN_REVIEW", "In review"
        NEEDS_INFORMATION = "NEEDS_INFORMATION", "Needs information"
        ESCALATED = "ESCALATED", "Escalated"
        APPROVED = "APPROVED", "Completed / Reviewed"

    case = models.ForeignKey(
        Case, on_delete=models.PROTECT, related_name="reviews"
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="case_reviews",
    )
    ai_result = models.ForeignKey(
        AIResult,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviews",
    )
    decision = models.CharField(max_length=30, choices=Decision.choices)
    edited_note = models.TextField(blank=True)
    reviewer_comments = models.TextField(blank=True)
    patient_comments = models.TextField(blank=True)
    follow_up_instructions = models.TextField(blank=True)
    referral_details = models.TextField(blank=True)
    patient_request = models.TextField(blank=True)
    escalation_reason = models.TextField(blank=True)
    is_finalized = models.BooleanField(default=False)
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class CaseActivity(models.Model):
    case = models.ForeignKey(
        Case, on_delete=models.CASCADE, related_name="activities"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT
    )
    action = models.CharField(max_length=50)
    old_status = models.CharField(max_length=30, blank=True)
    new_status = models.CharField(max_length=30, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.case_id} - {self.action}"
