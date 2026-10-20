
from rest_framework import serializers
from .models import Case
from .models import CaseActivity

class CaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Case
        fields = [
            "id",
            "owner",
            "patient_name",
            "description",
            "status",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "owner",
            "status",
            "created_at",
        ]

    def validate_patient_name(self, value):
        if not value.strip():
            raise serializers.ValidationError(
                "Patient name cannot be empty."
            )
        return value.strip()

    def validate_description(self, value):
        if not value.strip():
            raise serializers.ValidationError(
                "Description cannot be empty."
            )
        return value.strip()

class CaseActivitySerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(
        source="actor.username",
        read_only=True,
    )

    class Meta:
        model = CaseActivity
        fields = [
            "id",
            "case",
            "actor_name",
            "action",
            "old_status",
            "new_status",
            "timestamp",
        ]