
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()


class CareFlowAPITests(APITestCase):
    def setUp(self):
        patient_group, _ = Group.objects.get_or_create(name="Patient")

        self.patient = User.objects.create_user(
            username="api_patient",
            password="test-password-123",
        )
        self.patient.groups.add(patient_group)
        self.client.force_authenticate(user=self.patient)

    def test_patient_can_list_own_cases(self):
        response = self.client.get("/api/cases/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_patient_can_create_case(self):
        response = self.client.post(
            "/api/cases/",
            {
                "patient_name": "Test Patient",
                "description": "Headache for two days",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_patient_can_list_appointments(self):
        response = self.client.get("/api/appointments/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_patient_cannot_list_all_ai_results(self):
        response = self.client.get("/api/ai-results/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
