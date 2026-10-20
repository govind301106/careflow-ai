
from django.db import transaction

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Case, CaseActivity
from .serializers import CaseSerializer, CaseActivitySerializer
from .permissions import (
    HasValidRole,
    IsClinicianOrReadOnly,
    IsClinician,
)


class CaseViewSet(viewsets.ModelViewSet):
    serializer_class = CaseSerializer

    permission_classes = [
        IsAuthenticated,
        HasValidRole,
        IsClinicianOrReadOnly,
    ]

    ALLOWED_TRANSITIONS = {
        Case.Status.NEEDS_REVIEW: {
            Case.Status.IN_REVIEW,
            Case.Status.NEEDS_INFORMATION,
            Case.Status.ESCALATED,
        },
        Case.Status.PROCESSING: {
            Case.Status.NEEDS_REVIEW,
            Case.Status.NEEDS_INFORMATION,
            Case.Status.ESCALATED,
        },
        Case.Status.IN_REVIEW: {
            Case.Status.APPROVED,
            Case.Status.NEEDS_INFORMATION,
            Case.Status.ESCALATED,
        },
        Case.Status.NEEDS_INFORMATION: {
            Case.Status.IN_REVIEW,
            Case.Status.ESCALATED,
        },
        Case.Status.ESCALATED: {
            Case.Status.IN_REVIEW,
        },
        Case.Status.APPROVED: set(),
    }
    def get_queryset(self):
        user = self.request.user

        if user.groups.filter(name="Clinician").exists():
            return Case.objects.all().order_by("-created_at")

        return Case.objects.filter(
            owner=user
        ).order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(
        detail=True,
        methods=["patch"],
        permission_classes=[IsAuthenticated, IsClinician],
    )
    def update_status(self, request, pk=None):
        case = self.get_object()
        new_status = request.data.get("status")

        # Validate the requested status
        if new_status not in Case.Status.values:
            raise ValidationError({
                "status": "Invalid status."
            })

        old_status = case.status

        if new_status not in self.ALLOWED_TRANSITIONS.get(old_status, set()):
            raise ValidationError({
                "status": (
                    f"Transition from {old_status} to {new_status} is not allowed."
                )
            })
        # Update status and create audit entry atomically
        with transaction.atomic():
            case.status = new_status
            case.save(update_fields=["status"])

            CaseActivity.objects.create(
                case=case,
                actor=request.user,
                action="STATUS_CHANGED",
                old_status=old_status,
                new_status=new_status,
            )

        return Response(
            {
                "id": case.id,
                "status": case.status,
            },
            status=status.HTTP_200_OK,
        )
    @action(
        detail=True,
        methods=["get"],
        permission_classes=[IsAuthenticated, IsClinician],
    )
    def activities(self, request, pk=None):
        case = self.get_object()

        activities = case.activities.order_by("-timestamp")

        serializer = CaseActivitySerializer(
            activities,
            many=True,
        )
        return Response(serializer.data)