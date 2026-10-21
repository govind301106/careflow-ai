from .validators import validate_medical_report
from rest_framework import serializers
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


class CaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Case
        fields = [
            "id", "owner", "assigned_clinician",
            "patient_name", "description",
            "preferred_language", "priority", "status",
            "processing_error", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "owner", "assigned_clinician", "priority",
            "status", "processing_error", "created_at", "updated_at",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if request and not request.user.groups.filter(name="Clinician").exists():
            data.pop("owner", None)
            data.pop("assigned_clinician", None)
            data.pop("processing_error", None)
        return data

    def validate_patient_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Patient name cannot be empty.")
        return value.strip()

    def validate_description(self, value):
        if not value.strip():
            raise serializers.ValidationError("Description cannot be empty.")
        return value.strip()


class PatientIntakeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientIntake
        exclude = ["id", "case", "created_at", "updated_at"]


class AppointmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Appointment
        fields = [
            "id", "patient", "clinician", "case",
            "scheduled_at", "reason", "status", "created_at",
        ]
        read_only_fields = ["id", "patient", "created_at"]

    def validate(self, attrs):
        request = self.context.get("request")
        if request and not request.user.groups.filter(name="Clinician").exists():
            attrs.pop("status", None)
            attrs.pop("clinician", None)
        return attrs


class CaseAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = CaseAttachment
        fields = [
            "id", "case", "uploaded_by", "original_filename",
            "content_type", "size_bytes", "sha256",
            "processing_status", "created_at",
        ]
        read_only_fields = fields


class ConsentRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConsentRecord
        fields = [
            "id", "case", "user", "purpose", "notice_version",
            "granted", "granted_at", "withdrawn_at", "created_at",
        ]
        read_only_fields = fields


class AIResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIResult
        fields = [
            "id", "case", "status", "schema_version",
            "model_name", "structured_output", "evidence",
            "uncertainty_flags", "rule_triggers", "error_code", "is_validated",
            "created_at",
        ]
        read_only_fields = fields


class ClinicianReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClinicianReview
        fields = [
            "id", "case", "reviewer", "ai_result", "decision",
            "edited_note", "reviewer_comments", "approved_at",
            "patient_comments", "follow_up_instructions", "referral_details",
            "patient_request", "escalation_reason",
            "is_finalized", "created_at",
        ]
        read_only_fields = ["id", "case", "reviewer", "approved_at", "created_at"]


class PatientReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClinicianReview
        fields = ["decision", "patient_comments", "follow_up_instructions", "referral_details", "created_at", "approved_at"]
        read_only_fields = fields


class PatientAIResultSerializer(serializers.ModelSerializer):
    """Allowlisted AI fields for the owning patient; no error/admin metadata."""
    patient_output_fields = (
        "patient_summary", "missing_information", "unclear_information",
        "contradictions", "urgent_alerts", "suggested_follow_up_questions",
        "suggested_priority", "priority_explanation", "source_references",
    )

    class Meta:
        model = AIResult
        fields = [
            "schema_version", "model_name", "created_at",
        ]
        read_only_fields = fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        output = instance.structured_output if isinstance(instance.structured_output, dict) else {}
        data["suggestions"] = {
            key: output[key] for key in self.patient_output_fields if key in output
        }
        return data


class CaseActivitySerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.username", read_only=True)

    class Meta:
        model = CaseActivity
        fields = [
            "id", "case", "actor_name", "action",
            "old_status", "new_status", "timestamp",
        ]
        read_only_fields = fields


class MedicalReportUploadSerializer(serializers.Serializer):
    file = serializers.FileField()

    def validate_file(self, value):
        return validate_medical_report(value)
