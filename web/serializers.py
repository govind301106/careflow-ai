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
        read_only_fields = ["id", "patient", "status", "created_at"]


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
            "id", "case", "processing_status", "schema_version",
            "model_name", "structured_output", "evidence",
            "uncertainty_flags", "rule_triggers", "error_code",
            "created_at",
        ]
        read_only_fields = fields


class ClinicianReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClinicianReview
        fields = [
            "id", "case", "reviewer", "ai_result", "decision",
            "edited_note", "reviewer_comments", "approved_at",
            "created_at",
        ]
        read_only_fields = ["id", "reviewer", "approved_at", "created_at"]


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
