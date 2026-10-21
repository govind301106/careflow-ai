
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client
from django.test import override_settings
import json
from unittest.mock import patch
from django.db import DatabaseError
from django.db.models.query import QuerySet
from rest_framework import status
from rest_framework.test import APITestCase
from .models import Case, PatientIntake, ConsentRecord, ClinicianReview, AIResult
from .models import ClinicianRegistration

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
        case = Case.objects.create(owner=self.patient, patient_name="Owned", description="Headache")
        response = self.client.get("/api/cases/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item = next(record for record in response.data if record["id"] == case.pk)
        self.assertNotIn("owner", item)
        self.assertNotIn("assigned_clinician", item)
        self.assertNotIn("processing_error", item)

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

    def test_intake_endpoint_uses_patient_intake_serializer(self):
        case = Case.objects.create(owner=self.patient, patient_name="API Patient", description="Cough")
        response = self.client.put(
            f"/api/cases/{case.pk}/intake/",
            {"symptoms": ["cough"], "duration": "2 days", "severity_description": "Mild"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["duration"], "2 days")
        self.assertTrue(PatientIntake.objects.filter(case=case).exists())

    def test_patient_consent_can_be_read_after_grant(self):
        case = Case.objects.create(owner=self.patient, patient_name="API Patient", description="Cough")
        created = self.client.post(
            f"/api/cases/{case.pk}/consent/",
            {"granted": True, "purpose": "Case review", "notice_version": "1.0"},
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        response = self.client.get(f"/api/cases/{case.pk}/consent/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(ConsentRecord.objects.filter(case=case).count(), 1)

    def test_session_login_patient_submission_and_dashboard_refresh(self):
        self.client.force_authenticate(user=None)
        login_response = self.client.post(
            "/api/auth/login/",
            {"username": "api_patient", "password": "test-password-123"},
            format="json",
        )
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        self.assertEqual(login_response.json()["role"], "patient")

        case_response = self.client.post(
            "/api/cases/",
            {"patient_name": "API Patient", "description": "Headache"},
            format="json",
        )
        self.assertEqual(case_response.status_code, status.HTTP_201_CREATED)
        case_id = case_response.data["id"]
        consent_response = self.client.post(
            f"/api/cases/{case_id}/consent/",
            {"granted": True, "purpose": "Case review", "notice_version": "1.0"},
            format="json",
        )
        self.assertEqual(consent_response.status_code, status.HTTP_201_CREATED)
        intake_response = self.client.put(
            f"/api/cases/{case_id}/intake/",
            {"symptoms": ["headache"], "duration": "one day"},
            format="json",
        )
        self.assertEqual(intake_response.status_code, status.HTTP_200_OK)

        dashboard = self.client.get("/api/cases/")
        dashboard_items = dashboard.data.get("results", []) if isinstance(dashboard.data, dict) else dashboard.data
        self.assertEqual(dashboard.status_code, status.HTTP_200_OK)
        self.assertIn(case_id, [item["id"] for item in dashboard_items])

    def test_clinician_queue_assignment_review_and_status(self):
        clinician_group, _ = Group.objects.get_or_create(name="Clinician")
        clinician = User.objects.create_user(username="api_clinician", password="test-password-123")
        clinician.groups.add(clinician_group)
        case = Case.objects.create(owner=self.patient, patient_name="API Patient", description="Cough")
        PatientIntake.objects.create(case=case, symptoms=["cough"])
        self.client.force_authenticate(user=None)
        login_response = self.client.post(
            "/api/auth/login/",
            {"username": "api_clinician", "password": "test-password-123"},
            format="json",
        )
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        self.assertEqual(login_response.json()["role"], "clinician")

        queue = self.client.get("/api/cases/")
        queue_items = queue.data.get("results", []) if isinstance(queue.data, dict) else queue.data
        self.assertIn(case.pk, [item["id"] for item in queue_items])
        assignment = self.client.patch(
            f"/api/cases/{case.pk}/assign/", {"clinician_id": clinician.pk}, format="json"
        )
        self.assertEqual(assignment.status_code, status.HTTP_200_OK)
        review = self.client.post(
            f"/api/cases/{case.pk}/add_review/",
            {"decision": "IN_REVIEW", "reviewer_comments": "Reviewed by clinician."},
            format="json",
        )
        self.assertEqual(review.status_code, status.HTTP_201_CREATED)
        status_response = self.client.patch(
            f"/api/cases/{case.pk}/update_status/", {"status": "ESCALATED"}, format="json"
        )
        self.assertEqual(status_response.status_code, status.HTTP_200_OK)
        case.refresh_from_db()
        self.assertEqual(case.status, "ESCALATED")

    def test_patient_review_is_pending_until_finalized_and_excludes_internal_notes(self):
        clinician_group, _ = Group.objects.get_or_create(name="Clinician")
        clinician = User.objects.create_user(username="review_writer", password="test-password-123")
        clinician.groups.add(clinician_group)
        case = Case.objects.create(owner=self.patient, assigned_clinician=clinician, patient_name="API Patient", description="Cough")
        patient_url = f"/api/cases/{case.pk}/patient-review/"

        self.client.force_authenticate(user=self.patient)
        self.assertEqual(self.client.get(patient_url).json(), {"status": "pending", "review": None})

        self.client.force_authenticate(user=clinician)
        draft = self.client.post(f"/api/cases/{case.pk}/add_review/", {
            "decision": "IN_REVIEW", "reviewer_comments": "private draft note",
        }, format="json")
        self.assertEqual(draft.status_code, status.HTTP_201_CREATED)
        self.client.force_authenticate(user=self.patient)
        self.assertEqual(self.client.get(patient_url).json(), {"status": "in_review", "review": None})

        self.client.force_authenticate(user=clinician)
        finalized = self.client.post(f"/api/cases/{case.pk}/add_review/", {
            "decision": "NEEDS_INFORMATION", "reviewer_comments": "internal notes",
            "edited_note": "private edited note", "patient_comments": "Please provide the test result.",
            "follow_up_instructions": "Upload the result when available.", "referral_details": "Clinic referral pending.",
        }, format="json")
        self.assertEqual(finalized.status_code, status.HTTP_201_CREATED)
        self.client.force_authenticate(user=self.patient)
        response = self.client.get(patient_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "completed")
        self.assertEqual(response.data["review"]["patient_comments"], "Please provide the test result.")
        self.assertEqual(response.data["review"]["follow_up_instructions"], "Upload the result when available.")
        self.assertEqual(response.data["review"]["referral_details"], "Clinic referral pending.")
        self.assertIn("created_at", response.data["review"])
        self.assertNotIn("reviewer_comments", response.data["review"])
        self.assertNotIn("edited_note", response.data["review"])

    def test_case_status_in_review_is_reported_without_inventing_a_review(self):
        case = Case.objects.create(owner=self.patient, patient_name="API Patient", description="Cough", status=Case.Status.IN_REVIEW)
        self.client.force_authenticate(user=self.patient)
        response = self.client.get(f"/api/cases/{case.pk}/patient-review/")
        self.assertEqual(response.data, {"status": "pending", "review": None})

    def test_patient_ai_suggestions_states_are_independent_and_unconfigured_is_explicit(self):
        case = Case.objects.create(owner=self.patient, patient_name="AI state", description="Headache", status=Case.Status.IN_REVIEW)
        with patch.dict("os.environ", {"AI_PIPELINE_URL": ""}):
            self.assertEqual(self.client.get(f"/api/cases/{case.pk}/patient-ai-suggestions/").data, {"status": "not_configured", "result": None})
        with patch.dict("os.environ", {"AI_PIPELINE_URL": "https://pipeline.example.test"}):
            self.assertEqual(self.client.get(f"/api/cases/{case.pk}/patient-ai-suggestions/").data, {"status": "not_started", "result": None})
        AIResult.objects.create(case=case, status=AIResult.ProcessingStatus.PENDING)
        self.assertEqual(self.client.get(f"/api/cases/{case.pk}/patient-ai-suggestions/").data, {"status": "in_progress", "result": None})
        self.assertEqual(self.client.get(f"/api/cases/{case.pk}/patient-review/").data, {"status": "pending", "review": None})
        AIResult.objects.filter(case=case).delete()
        AIResult.objects.create(case=case, status=AIResult.ProcessingStatus.FAILED, error_code="private_failure")
        failed = self.client.get(f"/api/cases/{case.pk}/patient-ai-suggestions/")
        self.assertEqual(failed.data, {"status": "failed", "result": None})
        self.assertNotIn("private_failure", str(failed.data))

    def test_patient_ai_result_requires_validation_and_exposes_only_allowlisted_suggestions(self):
        case = Case.objects.create(owner=self.patient, patient_name="Validated AI", description="Cough")
        result = AIResult.objects.create(
            case=case,
            status=AIResult.ProcessingStatus.COMPLETED,
            schema_version="1",
            model_name="pipeline-model",
            structured_output={"patient_summary": "Cough reported", "missing_information": ["onset"], "urgent_alerts": [{"alert": "example", "evidence": "patient wording"}], "source_references": ["intake.symptoms"], "private_note": "clinician-only"},
            evidence=[{"internal_trace": "private"}],
            error_code="internal_error",
        )
        url = f"/api/cases/{case.pk}/patient-ai-suggestions/"
        self.assertEqual(self.client.get(url).data, {"status": "unavailable", "result": None})
        result.is_validated = True
        result.save(update_fields=["is_validated"])
        response = self.client.get(url)
        self.assertEqual(response.data["status"], "completed")
        self.assertEqual(response.data["result"]["suggestions"], {"patient_summary": "Cough reported", "missing_information": ["onset"], "urgent_alerts": [{"alert": "example", "evidence": "patient wording"}], "source_references": ["intake.symptoms"]})
        self.assertNotIn("private_note", str(response.data))
        self.assertNotIn("internal_trace", str(response.data))
        self.assertNotIn("error_code", response.data["result"])

    def test_patient_ai_endpoint_enforces_case_ownership_and_patient_role(self):
        case = Case.objects.create(owner=self.patient, patient_name="Private", description="Private case")
        other = User.objects.create_user(username="other_ai_patient", password="test-password-123")
        other.groups.add(Group.objects.get(name="Patient"))
        url = f"/api/cases/{case.pk}/patient-ai-suggestions/"
        self.client.force_authenticate(user=other)
        self.assertEqual(self.client.get(url).status_code, status.HTTP_404_NOT_FOUND)
        clinician_group, _ = Group.objects.get_or_create(name="Clinician")
        clinician = User.objects.create_user(username="ai_endpoint_clinician", password="test-password-123")
        clinician.groups.add(clinician_group)
        case.assigned_clinician = clinician
        case.save(update_fields=["assigned_clinician"])
        self.client.force_authenticate(user=clinician)
        self.assertEqual(self.client.get(url).status_code, status.HTTP_403_FORBIDDEN)

    def test_completed_ai_can_coexist_with_in_progress_review_and_final_review_with_unavailable_ai(self):
        clinician_group, _ = Group.objects.get_or_create(name="Clinician")
        clinician = User.objects.create_user(username="independent_workflows", password="test-password-123")
        clinician.groups.add(clinician_group)
        case = Case.objects.create(owner=self.patient, assigned_clinician=clinician, patient_name="Independent", description="Pain")
        result = AIResult.objects.create(case=case, status=AIResult.ProcessingStatus.COMPLETED, is_validated=True)
        self.client.force_authenticate(user=clinician)
        self.client.post(f"/api/cases/{case.pk}/add_review/", {"decision": "IN_REVIEW"}, format="json")
        self.client.force_authenticate(user=self.patient)
        self.assertEqual(self.client.get(f"/api/cases/{case.pk}/patient-ai-suggestions/").data["status"], "completed")
        self.assertEqual(self.client.get(f"/api/cases/{case.pk}/patient-review/").data["status"], "in_review")
        self.client.force_authenticate(user=clinician)
        finalized = self.client.post(f"/api/cases/{case.pk}/add_review/", {"decision": "APPROVED", "patient_comments": "Please book a follow-up."}, format="json")
        self.assertEqual(finalized.status_code, status.HTTP_201_CREATED)
        self.client.force_authenticate(user=self.patient)
        self.assertEqual(self.client.get(f"/api/cases/{case.pk}/patient-review/").data["status"], "completed")
        self.assertEqual(self.client.get(f"/api/cases/{case.pk}/patient-ai-suggestions/").data["status"], "completed")
        self.assertTrue(AIResult.objects.filter(pk=result.pk).exists())

    def test_finalized_clinician_review_is_available_when_ai_is_not_configured(self):
        clinician_group, _ = Group.objects.get_or_create(name="Clinician")
        clinician = User.objects.create_user(username="review_without_ai", password="test-password-123")
        clinician.groups.add(clinician_group)
        case = Case.objects.create(owner=self.patient, assigned_clinician=clinician, patient_name="Review only", description="Question")
        self.client.force_authenticate(user=clinician)
        response = self.client.post(f"/api/cases/{case.pk}/add_review/", {"decision": "NEEDS_INFORMATION", "patient_comments": "Please add the missing detail."}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.client.force_authenticate(user=self.patient)
        with patch.dict("os.environ", {"AI_PIPELINE_URL": ""}):
            self.assertEqual(self.client.get(f"/api/cases/{case.pk}/patient-ai-suggestions/").data["status"], "not_configured")
        review = self.client.get(f"/api/cases/{case.pk}/patient-review/")
        self.assertEqual(review.data["status"], "completed")
        self.assertEqual(review.data["review"]["decision"], "NEEDS_INFORMATION")

    def test_patient_ai_database_failure_is_logged_and_sanitized(self):
        case = Case.objects.create(owner=self.patient, patient_name="AI error", description="Question")
        def fail_ai_query(queryset, *fields):
            if queryset.model is AIResult:
                raise DatabaseError("private pipeline database error")
            return queryset
        with patch.object(QuerySet, "order_by", fail_ai_query):
            with self.assertLogs("web.views", level="ERROR") as captured:
                response = self.client.get(f"/api/cases/{case.pk}/patient-ai-suggestions/")
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["detail"], "AI suggestions are temporarily unavailable.")
        self.assertNotIn("private pipeline database error", str(response.data))
        self.assertTrue(any("case_id=" in line for line in captured.output))

    def test_clinician_can_open_case_without_structured_intake_and_original_description_is_preserved(self):
        clinician_group, _ = Group.objects.get_or_create(name="Clinician")
        clinician = User.objects.create_user(username="no_intake_clinician", password="test-password-123")
        clinician.groups.add(clinician_group)
        case = Case.objects.create(owner=self.patient, assigned_clinician=clinician, patient_name="Original", description="Patient's original description")
        self.client.force_authenticate(user=clinician)
        self.assertEqual(self.client.get(f"/api/cases/{case.pk}/intake/").status_code, status.HTTP_404_NOT_FOUND)
        detail = self.client.get(f"/api/cases/{case.pk}/")
        self.assertEqual(detail.data["description"], "Patient's original description")

    def test_review_status_and_content_are_scoped_to_each_case(self):
        clinician_group, _ = Group.objects.get_or_create(name="Clinician")
        clinician = User.objects.create_user(username="case_review_writer", password="test-password-123")
        clinician.groups.add(clinician_group)
        completed_case = Case.objects.create(owner=self.patient, assigned_clinician=clinician, patient_name="One", description="Case one")
        pending_case = Case.objects.create(owner=self.patient, patient_name="Two", description="Case two")
        self.client.force_authenticate(user=clinician)
        saved = self.client.post(f"/api/cases/{completed_case.pk}/add_review/", {
            "decision": "NEEDS_INFORMATION", "patient_comments": "Case one review only.",
        }, format="json")
        self.assertEqual(saved.status_code, status.HTTP_201_CREATED)
        self.client.force_authenticate(user=self.patient)
        first_review = self.client.get(f"/api/cases/{completed_case.pk}/patient-review/")
        second_review = self.client.get(f"/api/cases/{pending_case.pk}/patient-review/")
        self.assertEqual(first_review.data["review"]["patient_comments"], "Case one review only.")
        self.assertEqual(second_review.data, {"status": "pending", "review": None})

    def test_patient_cannot_read_another_patients_review(self):
        case = Case.objects.create(owner=self.patient, patient_name="API Patient", description="Cough")
        other = User.objects.create_user(username="other_review_patient", password="test-password-123")
        other.groups.add(Group.objects.get(name="Patient"))
        self.client.force_authenticate(user=other)
        self.assertEqual(self.client.get(f"/api/cases/{case.pk}/patient-review/").status_code, status.HTTP_404_NOT_FOUND)

    def test_clinician_cannot_use_patient_review_endpoint(self):
        clinician_group, _ = Group.objects.get_or_create(name="Clinician")
        clinician = User.objects.create_user(username="review_reader", password="test-password-123")
        clinician.groups.add(clinician_group)
        case = Case.objects.create(owner=self.patient, assigned_clinician=clinician, patient_name="API Patient", description="Cough")
        self.client.force_authenticate(user=clinician)
        response = self.client.get(f"/api/cases/{case.pk}/patient-review/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_patient_review_database_failure_is_logged_and_sanitized(self):
        case = Case.objects.create(owner=self.patient, patient_name="API Patient", description="Cough")
        self.client.force_authenticate(user=self.patient)
        def fail_review_query(queryset, *fields):
            if queryset.model is ClinicianReview:
                raise DatabaseError("internal database details")
            return queryset

        with patch.object(QuerySet, "order_by", fail_review_query):
            with self.assertLogs("web.views", level="ERROR") as captured:
                response = self.client.get(f"/api/cases/{case.pk}/patient-review/")
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["detail"], "Review information is temporarily unavailable.")
        self.assertNotIn("internal database details", str(response.data))
        self.assertTrue(any("case_id=" in line for line in captured.output))

    def test_final_review_requires_patient_facing_comment(self):
        clinician_group, _ = Group.objects.get_or_create(name="Clinician")
        clinician = User.objects.create_user(username="incomplete_writer", password="test-password-123")
        clinician.groups.add(clinician_group)
        case = Case.objects.create(owner=self.patient, assigned_clinician=clinician, patient_name="API Patient", description="Cough")
        self.client.force_authenticate(user=clinician)
        response = self.client.post(f"/api/cases/{case.pk}/add_review/", {"decision": "NEEDS_INFORMATION"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_session_login_rejects_missing_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.get("/api/csrf/")
        rejected = client.post(
            "/api/auth/login/",
            data=json.dumps({"username": "api_patient", "password": "test-password-123"}),
            content_type="application/json",
        )
        self.assertEqual(rejected.status_code, 403)
        token = client.cookies["csrftoken"].value
        accepted = client.post(
            "/api/auth/login/",
            data=json.dumps({"username": "api_patient", "password": "test-password-123"}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(accepted.status_code, 200)

    @override_settings(CORS_ALLOWED_ORIGINS=["http://localhost:5173"])
    def test_vite_cors_preflight_allows_credentials(self):
        response = self.client.options(
            "/api/cases/",
            HTTP_ORIGIN="http://localhost:5173",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type,x-csrftoken",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Access-Control-Allow-Origin"], "http://localhost:5173")
        self.assertEqual(response["Access-Control-Allow-Credentials"], "true")

    def test_public_registration_creates_patient_and_session(self):
        self.client.force_authenticate(user=None)
        csrf = self.client.get("/api/csrf/")
        response = self.client.post("/api/auth/register/", {
            "full_name": "New Patient", "username": "new_patient", "email": "new@example.test",
            "password": "A-long-test-password-927!", "password_confirmation": "A-long-test-password-927!",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username="new_patient")
        self.assertTrue(user.check_password("A-long-test-password-927!"))
        self.assertTrue(user.groups.filter(name="Patient").exists())
        self.assertFalse(user.groups.filter(name="Clinician").exists())
        self.assertTrue(self.client.get("/api/auth/me/").json()["authenticated"])

    def test_registration_rejects_duplicate_username_and_bad_confirmation(self):
        response = self.client.post("/api/auth/register/", {
            "full_name": "Duplicate", "username": "api_patient", "password": "A-long-test-password-927!",
            "password_confirmation": "wrong",
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_clinician_registration_is_pending_and_has_no_clinical_access(self):
        self.client.force_authenticate(user=None)
        response = self.client.post("/api/auth/register/", {
            "account_type": "clinician", "role": "admin", "is_staff": True,
            "full_name": "Pending Clinician", "username": "pending_clinician", "email": "pending@example.test",
            "password": "A-long-test-password-927!", "password_confirmation": "A-long-test-password-927!",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["role"], "pending_clinician")
        user = User.objects.get(username="pending_clinician")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.groups.filter(name="Clinician").exists())
        self.assertEqual(user.clinician_registration.status, ClinicianRegistration.Status.PENDING)
        self.client.force_authenticate(user=user)
        self.assertEqual(self.client.get("/api/cases/").status_code, status.HTTP_403_FORBIDDEN)

    def test_pending_clinician_can_sign_in_to_see_pending_status_only(self):
        pending = User.objects.create_user(username="pending_login", password="test-password-123")
        ClinicianRegistration.objects.create(user=pending)
        self.client.force_authenticate(user=None)
        response = self.client.post("/api/auth/login/", {"username": "pending_login", "password": "test-password-123"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["role"], "pending_clinician")
        self.assertEqual(self.client.get("/api/cases/").status_code, 403)

    def test_non_admin_cannot_approve_and_admin_can_approve_or_reject(self):
        candidate = User.objects.create_user(username="request_user", password="test-password-123")
        registration = ClinicianRegistration.objects.create(user=candidate)
        self.client.force_authenticate(user=self.patient)
        denied = self.client.post(f"/api/admin/clinician-requests/{registration.pk}/review/", {"decision": "approve"}, format="json")
        self.assertEqual(denied.status_code, 403)
        self.assertFalse(candidate.groups.filter(name="Clinician").exists())
        admin = User.objects.create_superuser(username="review_admin", email="admin@example.test", password="test-password-123")
        self.client.force_authenticate(user=None)
        self.client.force_login(admin)
        approved = self.client.post(f"/api/admin/clinician-requests/{registration.pk}/review/", {"decision": "approve"}, format="json")
        self.assertEqual(approved.status_code, 200)
        candidate.refresh_from_db()
        self.assertTrue(candidate.groups.filter(name="Clinician").exists())
        rejected_user = User.objects.create_user(username="rejected_user", password="test-password-123")
        rejected = ClinicianRegistration.objects.create(user=rejected_user)
        response = self.client.post(f"/api/admin/clinician-requests/{rejected.pk}/review/", {"decision": "reject"}, format="json")
        self.assertEqual(response.status_code, 200)
        rejected_user.refresh_from_db()
        self.assertEqual(rejected_user.clinician_registration.status, ClinicianRegistration.Status.REJECTED)
        self.assertFalse(rejected_user.groups.filter(name="Clinician").exists())

    def test_registration_cannot_escalate_patient_to_clinician_or_admin(self):
        response = self.client.post("/api/auth/register/", {
            "full_name": "Only Patient", "username": "only_patient", "role": "clinician", "is_staff": True, "is_superuser": True,
            "password": "A-long-test-password-927!", "password_confirmation": "A-long-test-password-927!",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username="only_patient")
        self.assertTrue(user.groups.filter(name="Patient").exists())
        self.assertFalse(user.groups.filter(name="Clinician").exists())
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_chat_is_private_to_case_owner_and_confirmation_requires_consent(self):
        case = Case.objects.create(owner=self.patient, patient_name="Test", description="headache")
        other = User.objects.create_user(username="other_chat_patient", password="test-password-123")
        other.groups.add(Group.objects.get(name="Patient"))
        self.client.force_authenticate(user=other)
        denied = self.client.post(f"/api/cases/{case.pk}/chat/", {"message": "Today"}, format="json")
        self.assertEqual(denied.status_code, 404)
        self.client.force_authenticate(user=self.patient)
        ConsentRecord.objects.create(case=case, user=self.patient, purpose="review", notice_version="1", granted=True)
        self.client.post(f"/api/cases/{case.pk}/chat/", {"message": "The pain began this morning."}, format="json")
        response = self.client.post(f"/api/cases/{case.pk}/chat/", {"confirm": True, "intake": {"symptoms": ["headache"]}}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("chat_messages", response.data["intake"]["original_answers"])

    def test_ai_adapter_unavailable_without_contract_configuration(self):
        from unittest.mock import patch
        from web.ai_pipeline import PipelineUnavailable, submit_case
        with patch.dict("os.environ", {"AI_PIPELINE_URL": ""}):
            with self.assertRaises(PipelineUnavailable):
                submit_case({}, "case-1")

    def test_ai_adapter_validates_success_and_handles_transport_failure(self):
        from unittest.mock import MagicMock, patch
        from web.ai_pipeline import PipelineUnavailable, submit_case
        expected = {"schema_version": "1", "status": "COMPLETED", "structured_output": {}, "evidence": [], "uncertainty_flags": []}
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(expected).encode()
        with patch.dict("os.environ", {"AI_PIPELINE_URL": "https://pipeline.invalid/contract"}), patch("web.ai_pipeline.urlopen", return_value=response) as opener:
            self.assertEqual(submit_case({"case": 1}, "case-1"), expected)
            self.assertEqual(opener.call_args.kwargs["timeout"], 8.0)
        with patch.dict("os.environ", {"AI_PIPELINE_URL": "https://pipeline.invalid/contract"}), patch("web.ai_pipeline.urlopen", side_effect=TimeoutError):
            with self.assertRaises(PipelineUnavailable):
                submit_case({}, "case-1")
