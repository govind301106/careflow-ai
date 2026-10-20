
from rest_framework import serializers

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
}


def validate_medical_report(upload):
    if upload.size > MAX_UPLOAD_SIZE:
        raise serializers.ValidationError(
            "File size must not exceed 10 MB."
        )

    if upload.content_type not in ALLOWED_CONTENT_TYPES:
        raise serializers.ValidationError(
            "Only PDF, JPEG, and PNG files are allowed."
        )

    return upload
