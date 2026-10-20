from django.contrib.auth.models import Group, User
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Case, CaseActivity


class CaseSecurityTests(APITestCase):
    def setUp(self):
        self.patient_group, _ = Group.objects.get_or_create(name="Patient")
        self.clinician_group, _ = Group.objects.get_or_create(name="Clinician")

        self.patient1 = User.objects.create_user(
            username="patient1", password="TestPass123!"
        )
        self.patient1.groups.add(self.patient_group)

        self.patient2 = User.objects.create_user(
            username="patient2", password="TestPass123!"
        )
        self.patient2.groups.add(self.patient_group)

        self.clinician = User.objects.create_user(
            username="clinician1", password="TestPass123!"
        )
        self.clinician.groups.add(self.clinician_group)

        self.unauthorized = User.objects.create_user(
            username="unassigned", password="TestPass123!"
        )

        self.case1 = Case.objects.create(
            owner=self.patient1,
            patient_name="Patient One",
            description="Synthetic test case one",
        )

        self.case2 = Case.objects.create(
            owner=self.patient2,
            patient_name="Patient Two",
            description="Synthetic test case two",
        )

        self.cases_url = reverse("case-list")

    def test_patient_sees_only_own_cases(self):
        self.client.force_authenticate(user=self.patient1)

        response = self.client.get(self.cases_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [case["id"] for case in response.data["results"]]
            if isinstance(response.data, dict) and "results" in response.data
            else [case["id"] for case in response.data],
            [self.case1.id],
        )

    def test_patient_cannot_access_another_patients_case(self):
        self.client.force_authenticate(user=self.patient1)

        response = self.client.get(
            reverse("case-detail", kwargs={"pk": self.case2.id})
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patient_cannot_change_case(self):
        self.client.force_authenticate(user=self.patient1)

        response = self.client.patch(
            reverse("case-detail", kwargs={"pk": self.case1.id}),
            {"description": "Unauthorized change"},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.case1.refresh_from_db()
        self.assertEqual(
            self.case1.description, "Synthetic test case one"
        )

    def test_patient_can_create_case_with_self_as_owner(self):
        self.client.force_authenticate(user=self.patient1)

        response = self.client.post(
            self.cases_url,
            {
                "patient_name": "New Synthetic Patient",
                "description": "Synthetic intake for testing",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        created_case = Case.objects.get(id=response.data["id"])
        self.assertEqual(created_case.owner, self.patient1)

    def test_user_without_valid_role_is_denied(self):
        self.client.force_authenticate(user=self.unauthorized)

        response = self.client.get(self.cases_url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_clinician_can_update_status_and_activity_is_logged(self):
        self.client.force_authenticate(user=self.clinician)

        response = self.client.patch(
            reverse(
                "case-update-status",
                kwargs={"pk": self.case1.id},
            ),
            {"status": Case.Status.IN_REVIEW},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.case1.refresh_from_db()
        self.assertEqual(self.case1.status, Case.Status.IN_REVIEW)

        activity = CaseActivity.objects.get(
            case=self.case1,
            action="STATUS_CHANGED",
        )
        self.assertEqual(activity.actor, self.clinician)
        self.assertEqual(
            activity.old_status, Case.Status.NEEDS_REVIEW
        )
        self.assertEqual(
            activity.new_status, Case.Status.IN_REVIEW
        )

    def test_patient_cannot_update_status(self):
        self.client.force_authenticate(user=self.patient1)

        response = self.client.patch(
            reverse(
                "case-update-status",
                kwargs={"pk": self.case1.id},
            ),
            {"status": Case.Status.APPROVED},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.case1.refresh_from_db()
        self.assertEqual(
            self.case1.status, Case.Status.NEEDS_REVIEW
        )
        self.assertFalse(
            CaseActivity.objects.filter(
                case=self.case1,
                action="STATUS_CHANGED",
            ).exists()
        )
    def test_invalid_status_transition_is_rejected(self):
        self.client.force_authenticate(user=self.clinician)

        response = self.client.patch(
            reverse(
                "case-update-status",
                kwargs={"pk": self.case1.id},
            ),
            {"status": Case.Status.APPROVED},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.case1.refresh_from_db()
        self.assertEqual(self.case1.status, Case.Status.NEEDS_REVIEW)

        self.assertFalse(
            CaseActivity.objects.filter(
                case=self.case1,
                action="STATUS_CHANGED",
            ).exists()
        )


    def test_unauthenticated_user_cannot_access_cases(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(self.cases_url)

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )

    def test_patient_cannot_change_status_or_owner(self):
        self.client.force_authenticate(user=self.patient1)

        response = self.client.patch(
            reverse("case-detail", kwargs={"pk": self.case1.id}),
            {
                "status": Case.Status.APPROVED,
                "owner": self.patient2.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.case1.refresh_from_db()
        self.assertEqual(self.case1.owner, self.patient1)
        self.assertEqual(
            self.case1.status,
            Case.Status.NEEDS_REVIEW,
        )