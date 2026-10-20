
from django.db import models
from django.conf import settings


class Case(models.Model):
    class Status(models.TextChoices):
        NEEDS_REVIEW = "NEEDS_REVIEW", "Needs review"
        PROCESSING = "PROCESSING", "Processing"
        IN_REVIEW = "IN_REVIEW", "In review"
        APPROVED = "APPROVED", "Approved"
        NEEDS_INFORMATION = "NEEDS_INFORMATION", "Needs information"
        ESCALATED = "ESCALATED", "Escalated"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cases",
        null=True,
        blank=True,
    )

    patient_name = models.CharField(max_length=100)
    description = models.TextField()
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.NEEDS_REVIEW,
    )
    created_at = models.DateTimeField(auto_now_add=True)

class CaseActivity(models.Model):
    case = models.ForeignKey(
        Case,
        on_delete=models.CASCADE,
        related_name="activities",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
    )
    action = models.CharField(max_length=50)
    old_status = models.CharField(max_length=30, blank=True)
    new_status = models.CharField(max_length=30, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.case_id} - {self.action}"