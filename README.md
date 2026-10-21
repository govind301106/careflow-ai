# CareFlow AI: technical handoff

CareFlow is a human-led case intake and clinician review workspace. Patients submit symptom information and optional reports, clinicians review assigned cases, and administrators approve or reject clinician registration requests. The repository contains a small optional HTTP adapter for an AI service, but it does not currently submit cases to that service or persist its responses. Treat the AI integration sections below as a precise description of the current boundary plus a separately marked proposal for the teammate to agree with the CareFlow owner.

> Development and demonstration data must be synthetic. This application has not been assessed or approved for clinical use or production handling of patient data.

## Table of contents

- [Project overview and implementation status](#project-overview-and-implementation-status)
- [Repository structure](#repository-structure)
- [Authentication and roles](#authentication-and-roles)
- [API reference](#api-reference)
- [AI pipeline integration](#ai-pipeline-integration)
- [Frontend integration points](#frontend-integration-points)
- [Database models and migrations](#database-models-and-migrations)
- [Local development setup](#local-development-setup)
- [Security, privacy, and clinical safeguards](#security-privacy-and-clinical-safeguards)
- [AI teammate implementation checklist](#ai-teammate-implementation-checklist)
- [Deployment status and limitations](#deployment-status-and-limitations)
- [Verification and manual review](#verification-and-manual-review)

## Project overview and implementation status

### Architecture

| Component | Current responsibility |
| --- | --- |
| React 19 and Vite 8 | Patient and clinician screens, registration/login forms, case detail, patient intake chat, appointments, and clinician registration queue. `frontend/src/api.js` sends JSON or multipart requests with the session cookie and obtains a CSRF token for writes. |
| Django (supported requirement range `>=5.2,<7.0`; local migrations were generated with Django 6.1.1) / Django REST Framework | Session authentication, role and ownership checks, serializers, case/intake/consent/review/appointment APIs, private upload authorization, and case activity records. |
| SQLite | Default local relational database at `db.sqlite3`. An optional `DATABASE_URL` selects a database parsed by `dj-database-url`; PostgreSQL support is configured but has not been verified in this repository's test runs. |
| AI service | **Not integrated end to end.** `web/ai_pipeline.py` can POST an arbitrary JSON payload to a configured URL and check a small response envelope. No case view calls it, no job/worker/callback persists its output, and no API endpoint creates AI results. |

### Workflows

- **Patient:** register or sign in; create a case; record consent; submit structured intake, clarify it through a deterministic rule-based chat, and confirm it; optionally upload a report; review appointment requests; see AI state/result and the patient-visible portion of a finalized clinical review.
- **Clinician:** register and wait for staff approval; after approval, view unassigned and self-assigned cases, claim a case, inspect its intake and authorized report, and use the case review actions. Escalating records a reason and returns the case to the unassigned queue. Finalization stores the existing terminal value `APPROVED`, displayed in the UI as “Completed / Reviewed.”
- **Administrator:** staff users can list pending clinician registrations and **Approve** or **Reject** them. Staff status is required by these endpoints. The Django admin site is mounted, but `web/admin.py` does not register CareFlow models.

### Status separation and implementation state

These are distinct values in the current application:

- Case workflow: `NEEDS_REVIEW`, `PROCESSING`, `IN_REVIEW`, `NEEDS_INFORMATION`, `ESCALATED`, or `APPROVED` (UI label “Completed / Reviewed”).
- Case priority: `UNASSESSED`, `RED`, `YELLOW`, or `GREEN`. There is no automated priority scoring in this repository; a new case defaults to `UNASSESSED`.
- Consent: individual `ConsentRecord` rows; consent is not a review decision.
- AI processing: `AIResult.status` (`PENDING`, `COMPLETED`, `FAILED`) plus the separate `is_validated` flag.
- Clinical review: `ClinicianReview.is_finalized` and its `decision`; a draft, request for information, or escalation is unfinished.

**Implemented:** session-based accounts, patient/clinician/staff role checks, case and intake APIs, consent, deterministic intake chat, private local reports, appointments, case activity, clinician registration approval, explicit clinician review actions, patient-safe review serialization, validated AI result display, and unit/API tests.

**Not implemented:** automatic AI submission, an AI task queue or callback, persistence of adapter responses, automatic triage, OCR/report extraction, voice recording/transcription, email notifications, production hosting, durable object storage, and browser end-to-end tests. An appointment API exists; no calendar integration is present.

## Repository structure

| Path | Purpose |
| --- | --- |
| `careflow/settings.py` | Django apps/middleware, session-only DRF authentication, environment variables, SQLite/PostgreSQL database selection, CORS/CSRF origins, upload request-size cap, and production security flags. |
| `careflow/urls.py` | Authentication/CSRF routes, staff clinician-registration routes, Django admin, API router inclusion, and DRF browsable-auth URLs. |
| `careflow/asgi.py`, `careflow/wsgi.py` | ASGI and WSGI application entry points. |
| `manage.py` | Django management commands. |
| `frontend/src/App.jsx` | Main React application, screens, case selection/loading, patient AI/review panels, clinician AI/review panels, and review action buttons. |
| `frontend/src/api.js` | Fetch wrapper. Uses `VITE_API_URL` or `/api`, includes session credentials, fetches a CSRF cookie, and sends `X-CSRFToken` on unsafe methods. |
| `frontend/src/App.css`, `frontend/src/index.css` | Application and global styles, including the dark case detail/review layout. |
| `frontend/vite.config.js` | Vite plugins and local `/api` proxy to `http://127.0.0.1:8000`. |
| `frontend/package.json`, `frontend/package-lock.json` | Frontend scripts and locked npm dependency graph. |
| `web/models.py` | Case, intake, chat, consent, AI result, clinician review, activity, appointment, attachment, and clinician registration models. |
| `web/serializers.py` | DRF representations, including the clinician review serializer and patient-safe allowlists. |
| `web/views.py` | Registration/login/logout, staff approval, case actions, role-scoped viewsets, and patient endpoints. |
| `web/permissions.py` | `IsClinician`, `HasValidRole`, and `IsClinicianOrReadOnly` permission classes. The API currently uses session authentication globally; viewsets select these permissions. |
| `web/urls.py` | DRF `DefaultRouter` registrations for cases, appointments, attachments, consents, reviews, and AI results; private attachment download route. |
| `web/ai_pipeline.py` | Optional synchronous HTTP POST adapter. It has no persistence or caller in the current application. |
| `web/storage.py`, `web/validators.py`, `web/downloads.py` | Private local file storage, report size/type checks, and authenticated report download authorization. |
| `web/tests_api.py` | API tests for authentication, ownership, AI result visibility/states, clinician review actions, consent, and chat. |
| `web/test.py`, `web/tests.py`, `web/test_uploads.py` | Case permission/status tests, additional tests, and report upload/download security tests. `web/test.py` is discovered by Django's test runner because it starts with `test`. |
| `web/migrations/` | Ordered database schema/data migrations, listed in [Database models and migrations](#database-models-and-migrations). |
| `requirements.txt` | Python dependency ranges, including Django, DRF, CORS headers, database URL parsing, dotenv, and psycopg. |
| `.env.example` | Names of the base Django/database/CORS environment variables; values are blank. Optional AI adapter variables are read by code but are not currently listed here. |
| `.gitignore` | Excludes `.env`, SQLite database files, virtual environments, static build output, and `private_uploads/`. |

## Authentication and roles

### Session and CSRF behavior

DRF's configured authentication class is `SessionAuthentication`; there is no JWT or token API in this project. Successful registration/login creates a Django session. The browser uses `credentials: "include"`. Before `POST`, `PUT`, `PATCH`, or `DELETE`, `apiRequest` calls `GET /api/csrf/` and sends the `csrftoken` cookie as `X-CSRFToken`. Django CSRF middleware and `@csrf_protect` guard the authentication writes.

### Registration and login

`POST /api/auth/register/` accepts JSON:

```json
{
  "account_type": "patient",
  "full_name": "Synthetic Patient",
  "username": "demo_patient",
  "email": "demo.patient@example.test",
  "password": "<local synthetic password>",
  "password_confirmation": "<same local synthetic password>"
}
```

`account_type` may be `patient` or `clinician`; omission defaults to `patient`. Username and full name are required; email is optional for a patient and required for a clinician. Email and username uniqueness are checked case-insensitively. Password validation uses Django's configured validators. Public registration ignores caller-supplied role/admin fields.

Patient success (`201`):

```json
{
  "authenticated": true,
  "id": 12,
  "username": "demo_patient",
  "full_name": "Synthetic Patient",
  "email": "demo.patient@example.test",
  "role": "patient"
}
```

Clinician success (`201`) creates a `ClinicianRegistration` in `PENDING`, creates a session, and grants no Clinician group membership:

```json
{
  "authenticated": true,
  "id": 13,
  "username": "demo_clinician",
  "full_name": "Synthetic Clinician",
  "email": "demo.clinician@example.test",
  "role": "pending_clinician",
  "approval_status": "pending"
}
```

Validation failures return `400` with field errors (or `{"detail":"Invalid JSON."}`).

`POST /api/auth/login/` accepts `{"username":"demo_patient","password":"<local synthetic password>"}`. Successful patient/approved-clinician/admin login returns `authenticated`, `id`, `username`, `role`, and `is_staff`. Pending clinicians can log in but receive `role: "pending_clinician"` and `approval_status: "pending"`; role-protected clinical APIs remain unavailable. Rejected clinician registrations receive `403`. Bad credentials return `400`; accounts with no CareFlow role receive `403`.

`GET /api/auth/me/` returns `{"authenticated":false}` when anonymous. For a signed-in account, it returns `authenticated`, `id`, `username`, `full_name`, `email`, `role`, `approval_status`, and `is_staff`.

`POST /api/auth/logout/` logs out the current session and returns `{"authenticated":false}`. It is CSRF-protected.

### Role and approval rules

- Patient accounts belong to the `Patient` group and see only cases they own.
- Clinician applicants have a `ClinicianRegistration` row. Until staff approves the request, they have no `Clinician` group and cannot use clinician APIs. Rejected applicants cannot log in. Approval adds the `Clinician` group; the registration status is recorded separately.
- `is_staff` is required for the custom clinician-request endpoints. This is not a patient-facing or clinician-facing permission.
- `IsClinician` also checks a registration row, if present, and requires it to be approved. `HasValidRole` admits Patient group members or approved Clinician group members.
- Staff/admin users are not automatically granted Patient or Clinician API access. The `web` models are not registered in `web/admin.py`; the implemented registration decision queue is the custom API below.

## API reference

All paths below include the `/api` prefix and trailing slash. JSON endpoints use session cookies; unsafe methods require CSRF. `IsAuthenticated` is required unless noted. DRF validation errors are generally `400`; permission failures are `403`; inaccessible objects commonly resolve as `404` due to queryset scoping. The coverage notes describe existing automated coverage, not a guarantee that every edge case has been tested.

### Authentication and clinician registration

| Method and path | Access and purpose | Body / success | Errors and test status |
| --- | --- | --- | --- |
| `GET /api/csrf/` | Anonymous or authenticated. Sets the CSRF cookie. | `{"detail":"CSRF cookie set"}` | Covered as part of CSRF tests. |
| `POST /api/auth/register/` | Public; creates patient or pending clinician account and session. | See [Registration and login](#registration-and-login). | `400` validation/JSON; API tests cover registration and privilege escalation attempts. |
| `POST /api/auth/login/` | Public; creates session. | JSON `username`, `password`; role-specific JSON response described above. | `400` invalid credentials/JSON; `403` rejected/no-role account; tested. |
| `GET /api/auth/me/` | Session optional. Returns current session identity or anonymous marker. | JSON described above. | Covered by authentication tests. |
| `POST /api/auth/logout/` | Session optional; CSRF-protected. | `{}`; returns `{"authenticated":false}`. | Test coverage exists for session auth, but logout behavior is not separately asserted by the current API tests. |
| `GET /api/admin/clinician-requests/` | `is_staff` only; lists pending registrations ordered oldest first. | JSON array: `id`, `user_id`, `username`, `full_name`, `email`, `created_at`. | `403` if not staff; tested. |
| `POST /api/admin/clinician-requests/{registration_id}/review/` | `is_staff` only; one-time pending registration decision. | `{"decision":"approve"}` or `{"decision":"reject"}`; returns `{"id":N,"status":"approved"|"rejected"}`. | `400` invalid decision/JSON; `403` not staff; `404` missing/non-pending record; approve and reject covered. |

### Cases, intake, consent, chat, and reports

| Method and path | Access and purpose | Body / success | Errors and test status |
| --- | --- | --- | --- |
| `GET /api/cases/` | Patient: own cases. Clinician: unassigned cases plus cases assigned to self. | JSON array of `CaseSerializer` fields. Patient output omits `owner`, `assigned_clinician`, and `processing_error`; fields include `id`, `patient_name`, `description`, `preferred_language`, `priority`, `status`, timestamps. | `403` invalid role; ownership/list isolation tested. |
| `POST /api/cases/` | Patient role; creates a patient-owned case. Clinicians cannot create cases here. | `patient_name`, `description`, optional `preferred_language`; returns case representation (`201`). Owner, assignment, priority, status, timestamps are server-managed. | `400` invalid/blank patient name or description; `403` clinician; tested. |
| `GET /api/cases/{id}/` | Owner patient or clinician whose queue includes the case (assigned to self or unassigned). | Case serializer output. | Other patients get `404`. |
| `PUT/PATCH /api/cases/{id}/` | Assigned clinician only; serializer fields `patient_name`, `description`, `preferred_language` are editable. Patient receives `403`. | Updated case representation. | `403` unless clinician and assigned. Not a normal UI workflow; limited direct update coverage. |
| `DELETE /api/cases/{id}/` | Clinician role and case visible in clinician queryset. The current view does not additionally require assignment, so a clinician can delete an unassigned case. | `204` on success. | Destructive endpoint; not surfaced in UI. **Requires policy confirmation before production use.** |
| `PATCH /api/cases/{id}/assign/` | Clinician role; case must be visible to the requesting clinician. Assigns to `clinician_id` or defaults to the current clinician. Target must be in Clinician group. Used to claim an unassigned/escalated case. | `{"clinician_id": 17}`; returns case. | `400` non-clinician target; `404` unknown target/case. Assignment path covered in API tests. |
| `PATCH /api/cases/{id}/update_status/` | Assigned clinician; validates the allowed transition. | `{"status":"IN_REVIEW"}` (or supported ordinary transition); returns case. | `400` invalid transition. Direct `NEEDS_INFORMATION`, `ESCALATED`, and `APPROVED` are rejected: use the review actions so requests/reasons/finalization are recorded. Transition tests cover valid/invalid paths. |
| `GET /api/cases/{id}/intake/` | Owner patient or assigned clinician. | `PatientIntakeSerializer`: symptoms, onset, duration, severity, progression, history, medications, allergies, extra info, original answers, completeness and contradiction flags. | `404` if no intake; `403` clinician not assigned; patient ownership enforced. |
| `PUT/PATCH /api/cases/{id}/intake/` | Owner patient only. Clinicians cannot write intake. | Same intake fields; `PUT` is full serializer validation, `PATCH` partial. Returns intake. | `403` wrong role/owner; covered by API tests. Intake write itself is not gated on consent in this endpoint. |
| `GET /api/cases/{id}/consent/` | Owner patient; assigned clinician can read case consent records. | Array of consent records with case/user, purpose/version, granted and timestamps. | `403` clinician not assigned; case scoping enforced. |
| `POST /api/cases/{id}/consent/` | Owner patient only; creates an explicit consent record. | `{"granted":true,"purpose":"CareFlow case processing","notice_version":"1.0"}`; returns consent record (`201`). | `403` wrong owner/role or false/missing grant. |
| `GET/POST /api/cases/{id}/chat/` | Owner patient only. GET returns ordered `{role,content,mode,created_at}` messages. POST either sends a chat message or confirms intake. | Message: `{"message":"The synthetic symptom began this morning."}`. Confirm: `{"confirm":true,"intake":{}}`. Message response includes `mode`, `message`, `safety`; confirm returns `confirmed` and serialized `intake`. | `400` empty/over-4000-character message or invalid intake; `403` on confirm without active consent; case ownership and consent confirmation are tested. This assistant is deterministic and not the AI pipeline. |
| `POST /api/cases/{id}/attachments/` | Owner patient only; active consent required. Multipart form field `file`. | Validated PDF/JPEG/PNG up to 10 MiB; returns attachment metadata (`201`). | `403` wrong owner/no active consent; `400` file size/type/signature validation. Upload security is tested. |
| `GET /api/attachments/`, `GET /api/attachments/{id}/` | Read-only metadata. Patient sees own case attachments; clinician sees attachments for cases assigned to them. | `CaseAttachmentSerializer`: id, case, uploaded_by, filename, MIME type, size, SHA-256, processing status, creation time. | Out-of-scope records are not listed/retrieved. Upload/download security tests exist. |
| `GET /api/attachments/{attachment_id}/download/` | Authenticated owner patient or assigned clinician. | Attachment bytes as `application/octet-stream`, forced attachment disposition, `X-Content-Type-Options: nosniff`. | `404` absent, out-of-scope, or missing stored file; download authorization tested. |
| `GET /api/consents/`, `GET /api/consents/{id}/` | Read-only. Patient sees their consent rows; clinician sees rows for assigned cases. | Consent serializer fields described above. | Scope enforced by queryset; some coverage through consent tests. |
| `POST /api/consents/{id}/withdraw/` | Consenting patient only. Records `withdrawn_at` and a case activity. | No required body; returns consent record. | `403` if not the consenting user; repeated withdrawal is idempotent. Direct endpoint coverage is limited. Withdrawal does not erase case data or report files. |

### Clinician review, patient review, and AI results

| Method and path | Access and purpose | Body / success | Errors and test status |
| --- | --- | --- | --- |
| `POST /api/cases/{id}/add_review/` | Assigned clinician only. Saves/updates the unfinished review or finalizes it. | JSON shown below; response is the clinician-only `ClinicianReviewSerializer` (`201`). | `400` unsupported action, invalid field, missing request/reason/comments, or invalid workflow transition; `403` unassigned; tests cover draft, request, escalation, finalization, privacy, and transitions. |
| `GET /api/cases/{id}/reviews/` | Assigned clinician only; case-specific reviews, newest first. | Array of full clinician review records, including internal notes, patient request, escalation reason, and finalization fields. | `403` unless assigned. API tests cover privacy through patient endpoints; direct route coverage is limited. |
| `GET /api/cases/{id}/activities/` | Assigned clinician only; case-specific activity history, newest first. | Array of activity ID, case ID, actor username, action, old/new status, and timestamp. | `403` unless assigned. Activity creation/status behavior is covered; direct read route coverage is limited. |
| `GET /api/reviews/`, `GET /api/reviews/{id}/` | Clinician role; read-only records filtered to cases currently assigned to that clinician. | Full `ClinicianReviewSerializer`. | `403` non-clinician; queryset excludes other clinicians' cases. Direct route coverage is limited. |
| `GET /api/cases/{id}/patient-review/` | Owner patient only. Returns no draft fields. | No review or unfinished review: `{"status":"in_progress","request":null-or-string,"review":null}`. Finalized: `{"status":"completed","review":{...}}`. Final review allowlist is decision, patient comments, follow-up instructions, referral details, created time, and `approved_at`. | `404` another patient's case; `503` sanitized temporary database failure; tests verify ownership and internal-note privacy. |
| `GET /api/cases/{id}/ai_results/` | Assigned clinician only. Case-specific AI rows, newest first. | Array of `AIResultSerializer` fields, including raw structured output/evidence and internal error metadata; clinician-authorized only. | `403` unless assigned. Direct route coverage is limited. |
| `GET /api/ai-results/`, `GET /api/ai-results/{id}/` | Clinician role; read-only rows filtered to cases currently assigned to that clinician. | Full `AIResultSerializer`. | `403` non-clinician. Patient must use the patient-safe case endpoint instead. |
| `GET /api/cases/{id}/patient-ai-suggestions/` | Owner patient only. Returns AI processing state and allowlisted suggestion fields only after validation. | See [Persisted result model and patient status behavior](#persisted-result-model-and-patient-status-behavior). | `404` another patient's case; `503` sanitized database failure; validation/allowlist and status tests exist. |

#### Review write request

`decision` is required by the existing serializer and must be one of `IN_REVIEW`, `NEEDS_INFORMATION`, `ESCALATED`, or `APPROVED`. The explicit `workflow_action` controls the workflow and the backend stores the corresponding supported decision/status. Use `APPROVED` only with `finalize`; it is the old canonical database value displayed as “Completed / Reviewed,” not an administrative approval button or a diagnosis.

```json
{
  "workflow_action": "save_draft",
  "decision": "IN_REVIEW",
  "reviewer_comments": "Synthetic internal note, visible to authorized clinicians only.",
  "patient_comments": "",
  "follow_up_instructions": "",
  "referral_details": ""
}
```

Supported actions and effects:

| `workflow_action` | Required fields | Result |
| --- | --- | --- |
| `save_draft` | `decision` | Unfinished review, case moves to `IN_REVIEW`; no patient-facing review is published. |
| `request_information` | `patient_request` non-empty | Unfinished review, case moves to `NEEDS_INFORMATION`; request text appears in the patient's Clinical Review section. |
| `escalate` | `escalation_reason` non-empty | Unfinished review, case moves to `ESCALATED`; assignment is cleared so another clinician can claim the case from the unassigned queue. It is a handoff state, not a diagnosis or emergency finding. |
| `finalize` | `decision: "APPROVED"` and non-empty `patient_comments` | Finalizes the review, sets `approved_at`, moves the case to canonical `APPROVED` / UI “Completed / Reviewed,” and exposes only the patient serializer's allowlisted fields. |

Optional write fields include `ai_result` (must belong to the same case), `edited_note`, `reviewer_comments`, `patient_comments`, `follow_up_instructions`, and `referral_details`. `reviewer_comments` and `edited_note` are internal. A draft cannot be finalized directly from every workflow state: transition out of `NEEDS_INFORMATION` or `ESCALATED` to `IN_REVIEW` first. The backend enforces transitions; frontend checks are not authorization.

### Appointments

| Method and path | Access and purpose | Body / success | Errors and test status |
| --- | --- | --- | --- |
| `GET /api/appointments/` | Patient sees own appointments. Clinician sees appointments assigned to them or not yet assigned. | Array of appointment fields: id, patient, clinician, case, scheduled time, reason, status, creation time. | Role required. Listing tested. |
| `POST /api/appointments/` | Patient only. Creates request with patient/current user, `REQUESTED` status, no clinician. | Requires `scheduled_at`; optional `case`, `reason`. Returns appointment (`201`). A case must belong to patient. | `403` clinician or other patient's case; route coverage is limited. |
| `GET /api/appointments/{id}/` | Patient owner or clinician within appointment queryset. | Appointment serializer. | Out-of-scope appointment `404`. |
| `PUT/PATCH /api/appointments/{id}/` | Clinician only; may claim an unassigned request or update own appointment. | Appointment fields; clinician is set to current clinician if previously unassigned. Serializer status choices: `REQUESTED`, `CONFIRMED`, `CANCELLED`, `COMPLETED`. | `403` patient or appointment assigned to another clinician. Current code does not define a transition graph for appointment status. |
| `DELETE /api/appointments/{id}/` | DRF viewset currently exposes delete within the scoped appointment queryset. | `204` on success. | Not surfaced in UI; production policy requires confirmation. |

## AI pipeline integration

### Current implementation: optional adapter, no end-to-end processing

`web/ai_pipeline.py` implements:

```python
submit_case(payload, idempotency_key) -> dict
```

It reads these environment variables at call time:

- `AI_PIPELINE_URL`: exact URL to POST to; blank/missing raises `PipelineUnavailable("AI pipeline is not configured")`.
- `AI_PIPELINE_TOKEN`: optional bearer token (`Authorization: Bearer ...`).
- `AI_PIPELINE_TIMEOUT`: optional numeric seconds; default `8`.

The adapter serializes `payload` as JSON and sends `Content-Type: application/json`, `Accept: application/json`, and `Idempotency-Key: <idempotency_key>`. It does not append a path to the configured URL. It performs one synchronous `urllib.request.urlopen` call. There is no retry, polling, callback, queue, persistence, or duplicate suppression in CareFlow. The header delegates idempotency behavior to the remote service; the adapter itself does not store keys.

The request body has **no defined schema in current code**: the adapter accepts any JSON-serializable `payload`. A mocked test calls it with `{"case": 1}` and key `case-1`; that is a test fixture, not a production case payload contract. For example, this synthetic body can be serialized and POSTed by the current code, but its keys have no agreed meaning:

```json
{
  "case": {"description": "Synthetic example: intermittent dry cough."},
  "intake": {"duration": "Two days"}
}
```

The adapter decodes the response as JSON and requires these top-level keys to exist: `schema_version`, `status`, `structured_output`, `evidence`, and `uncertainty_flags`. It accepts only `status` values `PENDING`, `COMPLETED`, or `FAILED`. It does not currently validate the types or nested fields of those values, require case correlation, enforce an output schema version, validate sources/evidence, or map response keys into `AIResult`.

HTTP errors, URL errors, timeouts, invalid JSON, invalid timeout text, missing required keys, and unsupported status are converted to generic `PipelineUnavailable` errors. No retries occur. The `HTTPError` response body is not returned to the caller. Other unexpected errors (for example some character decoding errors or non-JSON-serializable input types) are not explicitly normalized. Adapter tests mock an accepted response, an unconfigured URL, and a timeout; there is no live service integration test.

Example of the **minimal mocked adapter response accepted today** (the nested output can be empty because current checks are envelope-only):

```json
{
  "schema_version": "1",
  "status": "COMPLETED",
  "structured_output": {},
  "evidence": [],
  "uncertainty_flags": []
}
```

The adapter returns that response JSON dictionary unchanged. Its unit test uses a mocked HTTP response with this envelope and verifies the default timeout; it does not validate a live AI service or clinical output.

No current CareFlow request invokes `submit_case`. Case creation does not call it. The adapter response is not saved, and there is no HTTP endpoint to create/update `AIResult` rows. The AI results viewsets are read-only. Therefore the adapter is a **transport helper only**, not a working pipeline integration.

### Persisted result model and patient status behavior

`AIResult` belongs to `Case` and stores `status`, `schema_version`, `model_name`, `structured_output`, `evidence`, `uncertainty_flags`, `rule_triggers`, `error_code`, `is_validated`, and `created_at`. `is_validated` defaults to false. A trusted backend integration must create/update rows and set `is_validated=True` only after agreed schema and patient-safety validation; no such integration currently exists.

Patient endpoint status logic uses the newest `AIResult`:

| Stored/configuration state | API `status` | Portal behavior |
| --- | --- | --- |
| No result and `AI_PIPELINE_URL` blank | `not_configured` | “Not configured.” |
| No result and URL set | `not_started` | “Not submitted”; a configured URL alone does not claim work is running. |
| Newest row is `PENDING` | `in_progress` | “In Progress.” This is only truthful if a trusted integration has actually persisted a pending attempt. |
| Newest row is `FAILED` | `failed` | “Failed”; no error details are returned to patient. |
| Newest row is `COMPLETED` and validated | `completed` | Patient receives row metadata and allowlisted suggestion fields. |
| Completed but not validated, or other unsupported state | `unavailable` | Result withheld. |

The patient allowlist maps only these keys from `structured_output` into `suggestions`: `patient_summary`, `missing_information`, `unclear_information`, `contradictions`, `urgent_alerts`, `suggested_follow_up_questions`, `suggested_priority`, `priority_explanation`, and `source_references`. The patient endpoint does not return raw `evidence`, `rule_triggers`, `error_code`, internal traces, or other output keys. Clinician AI result endpoints are scoped to assigned cases and return the full serializer. AI status is independent from case workflow and clinical review status.

### Proposed contract requiring agreement

Everything in this subsection is **proposed, not implemented or agreed**. Confirm it with the CareFlow owner and AI teammate before building a consumer. The current adapter can carry this JSON, but it does not enforce this schema.

#### Proposed request

The backend integration should create a request from case data the patient has consented to share. Include stable source identifiers with every text excerpt so the service can cite only supplied material. Do not send attachment bytes or assume OCR exists; report extraction is not implemented. Do not include internal clinician notes, other patients' data, account credentials, or unnecessary identifiers.

```json
{
  "schema_version": "careflow-ai-request/1",
  "case_id": "synthetic-case-0042",
  "patient_context": {
    "preferred_language": "en"
  },
  "sources": [
    {
      "source_id": "case.description",
      "source_type": "patient_description",
      "text": "Synthetic example: intermittent dry cough for two days."
    },
    {
      "source_id": "intake.duration",
      "source_type": "patient_intake",
      "text": "Two days"
    },
    {
      "source_id": "intake.allergies",
      "source_type": "patient_intake",
      "availability": "not_provided"
    }
  ]
}
```

The proposed `availability: "not_provided"` is distinct from a negative allergy response. For real requests, represent absent fields with a documented rule; do not convert absence into “none,” “negative,” or “no allergy.” Decide whether source records should contain raw text or typed values before implementation.

#### Proposed response

Use the existing adapter envelope keys and add `case_id` for correlation. The recommended synchronous contract is one `COMPLETED` or `FAILED` response. Returning `PENDING` is only useful after the team defines a separate polling/callback mechanism and a trusted backend persistence path; neither exists today.

```json
{
  "schema_version": "careflow-ai-response/1",
  "case_id": "synthetic-case-0042",
  "status": "COMPLETED",
  "model_name": "synthetic-model-name",
  "structured_output": {
    "patient_summary": "Synthetic intake reports a dry cough for two days.",
    "missing_information": [
      {
        "item": "Allergy information",
        "reason": "No allergy response was supplied.",
        "source_references": ["intake.allergies"]
      }
    ],
    "unclear_information": [],
    "contradictions": [],
    "urgent_alerts": [],
    "suggested_follow_up_questions": ["Have you noticed any change in the cough?"] ,
    "suggested_priority": "UNASSESSED",
    "priority_explanation": "Synthetic example; no configured trigger matched.",
    "source_references": ["case.description", "intake.duration"]
  },
  "evidence": [],
  "uncertainty_flags": [],
  "rule_triggers": [],
  "error_code": ""
}
```

Suggested types and requiredness for **proposal only**:

| Field | Proposed type / allowed values | Requiredness and meaning |
| --- | --- | --- |
| `schema_version` | Non-empty string | Required in request and response; version the payload contract. |
| `case_id` | Opaque string (or agreed opaque correlation token) | Required in request/response; must match exactly. Avoid sending a database primary key if external correlation policy requires a separate token. |
| `status` | `PENDING`, `COMPLETED`, `FAILED` | Required response enum, matching `AIResult`. Recommended first integration uses synchronous terminal statuses. |
| `model_name` | String | Optional response metadata; do not treat as a clinical authority. |
| `structured_output.patient_summary` | String | Required for `COMPLETED`; clearly attributed summary of supplied data, not a diagnosis. |
| `missing_information` | Array of objects `{item:string, reason?:string, source_references?:string[]}` | Required for `COMPLETED`; lists absent data. Absence is not a negative finding. |
| `unclear_information` | Array of objects `{item:string, explanation:string, source_references:string[]}` | Required for `COMPLETED`; only cite material supplied in the request. |
| `contradictions` | Array of objects `{description:string, statements:[{text:string,source_reference:string}]}` | Required for `COMPLETED`; empty means none identified from supplied data, not proof none exist. |
| `urgent_alerts` | Array of objects `{alert:string, evidence:[{source_reference:string, excerpt:string}]}` | Required for `COMPLETED`; each alert must have supporting supplied evidence. Define alert categories and safety copy with the clinical owner; never infer emergency certainty. |
| `suggested_follow_up_questions` | Array of strings | Required for `COMPLETED`; questions only, not claims that information exists. |
| `suggested_priority` | `UNASSESSED`, `RED`, `YELLOW`, `GREEN` | Required for `COMPLETED` if returned. These are existing `Case.Priority` values; meanings and thresholds require clinical agreement. Advisory only. |
| `priority_explanation` | String | Required when `suggested_priority` is present; cite reasons/sources. |
| `source_references` | Array of strings | Required for `COMPLETED`; each identifier must match a request source. Never invent citations. |
| top-level `evidence` | Array of structured evidence objects (exact object shape **requires agreement**) | Required by current adapter envelope; proposed structured evidence supporting output. |
| top-level `uncertainty_flags` | Array (exact item schema **requires agreement**) | Required by current adapter envelope; uncertainty, not a hidden risk score. |
| top-level `rule_triggers` | Array of structured trigger objects (exact item schema **requires agreement**) | Optional in proposed schema; stored in `AIResult`, not exposed as a top-level patient field. |
| `error_code` | Safe, non-PHI string or empty string | Optional for `FAILED`; no raw prompt, report text, traceback, credentials, or patient information. Decide whether to persist this field. |

For `FAILED`, return no clinical suggestions, use empty structured collections or omit them according to the final schema, and return only a safe error code. Validate required keys, nested types, enum values, source-reference membership, size limits, and schema version in the trusted CareFlow backend before persistence. Define whether unknown fields are rejected or ignored. Never set `is_validated=True` for `PENDING` or `FAILED`.

#### Integration decisions still required

Confirm the owner and deployment location of the AI service; exact request shape and source policy; response schema and version; synchronous versus asynchronous execution; authentication/secret rotation; timeout; retry and idempotency retention; maximum input/output sizes; status persistence/update lifecycle; safe error codes/logging; whether `model_name`, `rule_triggers`, and `error_code` are used; and clinical meaning of priority and urgent alerts. There is currently no callback/poll endpoint, AI submit API, worker, or service URL in `.env.example`.

## Frontend integration points

- `AIResultsSection` in `frontend/src/App.jsx` renders between Patient Intake and Clinical Review on case detail for both roles.
- For clinicians, `openCase()` requests `/api/cases/{id}/ai_results/`; the clinician card uses the persisted rows and can show validated structured output, evidence, uncertainty flags, and rule triggers.
- For patients, `openCase()` requests `/api/cases/{id}/patient-ai-suggestions/`; the card displays only the API's patient-safe allowlist. It shows Not configured, Not submitted, In Progress, Completed, Failed, or unavailable/error states based on persisted/API state.
- `PatientReviewPanel` separately reads `/api/cases/{id}/patient-review/`. It shows In Progress and any actual patient request until finalized; then it shows the final decision label and patient-facing comments, follow-up, referral, and review date. It never consumes the AI result as a clinical decision.
- The React fetch/CSRF helper is `apiRequest` in `frontend/src/api.js`. Once a backend submit/job/status API is agreed and implemented, extend the relevant `openCase`/submission flow through `apiRequest`. **Do not put the AI service token or direct service credential in React.**

The UI is currently read-only with respect to AI submission. It does not claim that a request is running merely because a URL is configured. It cannot display an AI result until some trusted component persists a validated `AIResult` row.

## Database models and migrations

### Models and relationships

- `Case`: owner and optional assigned clinician; patient name/description/language; independent priority/status; processing error; timestamps. Patient owner is protected from deletion; assignment is protected. New case defaults are `NEEDS_REVIEW` and `UNASSESSED`.
- `PatientIntake`: one-to-one with case; structured symptoms and context plus original answers, completeness flags, contradiction flags, timestamps.
- `IntakeChatMessage`: many-to-one with case; patient/assistant content, deterministic mode label, timestamp. Confirmation copies patient chat messages into intake original answers.
- `ConsentRecord`: many-to-one with case and user; purpose, notice version, grant/withdrawal timestamps. Consent is append-oriented; withdrawal records a timestamp rather than deleting.
- `CaseAttachment`: many-to-one with case/uploader; filename/type/size/storage key/SHA-256 and a processing status. Stored file bytes live under `private_uploads/`, not in the database.
- `AIResult`: many-to-one with case; status, schema/model names, JSON structured output/evidence/uncertainty/rule triggers, safe error code, validation flag, timestamp. No uniqueness constraint limits results per case; newest is selected for patient state.
- `ClinicianReview`: many-to-one with case/reviewer and optional AI result; existing decision enum, internal note fields, patient-visible comments/instructions/referral, patient request, escalation reason, finalized flag and date. Drafts are retained server-side but not exposed by the patient serializer.
- `CaseActivity`: many-to-one with case/actor; action, old/new workflow values and timestamp.
- `Appointment`: patient, optional clinician and optional case; requested time, reason, status and timestamp.
- `ClinicianRegistration`: one-to-one with user; pending/approved/rejected status, reviewing staff user and review time.

### Migration history

Migrations are applied in order by Django:

1. `0001_initial.py`
2. `0002_alter_cases_patient_name.py`
3. `0003_rename_cases_case.py`
4. `0004_alter_case_status.py`
5. `0005_case_owner.py`
6. `0006_caseactivity.py`
7. `0007_case_assigned_clinician_case_preferred_language_and_more.py`
8. `0008_rename_symptom_duration_patientintake_duration_and_more.py`
9. `0009_intakechatmessage.py`
10. `0010_clinicianregistration.py`
11. `0011_clinicianreview_follow_up_instructions_and_more.py`
12. `0012_airesult_is_validated.py`
13. `0013_clinicianreview_escalation_reason_and_more.py` (patient request/escalation reason fields, status label, and data correction that unfinalizes legacy `NEEDS_INFORMATION`/`ESCALATED` reviews)
14. `0014_alter_clinicianregistration_status_and_more.py` (registration label correction and canonical review label)

Apply pending schema changes without resetting data:

```powershell
python manage.py migrate
python manage.py showmigrations
```

Never delete `db.sqlite3` or use `flush`/database reset as a migration shortcut. Back up the database and private uploads before any database move. Applying migrations does not copy data between SQLite and PostgreSQL or move file bytes.

## Local development setup

Run these commands in Windows PowerShell from the repository root (the directory containing `manage.py`). Use only synthetic names, notes, case details, and reports.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit the root `.env`. `DJANGO_SECRET_KEY` is required; Django fails at startup if it is empty. For local development use values similar to these placeholders:

```dotenv
DJANGO_SECRET_KEY=<replace-with-a-random-local-development-secret>
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
DATABASE_URL=
CORS_ALLOWED_ORIGINS=
CSRF_TRUSTED_ORIGINS=
```

SQLite is selected when `DATABASE_URL` is empty. The current Vite configuration proxies `/api` to Django, so same-origin proxy development does not need CORS configuration. If instead the browser calls Django directly from another origin, configure the exact origin in both `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS`; use a consistent hostname because cookies are host-specific.

Optional adapter-only settings, not currently listed in `.env.example` and not sufficient to enable processing by themselves:

```dotenv
AI_PIPELINE_URL=
AI_PIPELINE_TOKEN=
AI_PIPELINE_TIMEOUT=8
```

Then migrate, check, create an administrator if needed, and start Django:

```powershell
python manage.py migrate
python manage.py check
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
```

In another PowerShell window from the repository root:

```powershell
Set-Location frontend
npm ci
npm run dev
```

Vite prints its local URL (typically `http://localhost:5173`). The default API base is `/api` and the Vite proxy forwards it to `http://127.0.0.1:8000`. `VITE_API_URL` can override the frontend API base; it is a frontend build-time value, not a secret. When changing this setting, verify CORS, CSRF trusted origins, and cookie host behavior.

### Optional PostgreSQL configuration

`careflow/settings.py` uses `dj-database-url` when `DATABASE_URL` is non-empty. `requirements.txt` includes `psycopg[binary]`. PostgreSQL support is configured but **not verified by the available test results**; the test suite here used local SQLite.

Use a placeholder URL in documentation only, for example `postgresql://<user>:<password>@<host>:5432/<database>`. Keep real credentials in a secret manager or local untracked `.env`. `migrate` creates/updates schema but does not transfer existing SQLite records or upload files. Any data move requires a separately tested export/import and file migration plan.

### Useful commands

From the repository root:

```powershell
python manage.py test
python manage.py check
python manage.py makemigrations --check --dry-run
```

From `frontend/`:

```powershell
npm run lint
npm run build
```

The frontend package also defines `npm test` (`node --test`); there are no dedicated browser test scripts configured.

## Security, privacy, and clinical safeguards

- **Authentication and CSRF:** session cookies, `SessionAuthentication`, CSRF middleware, and `X-CSRFToken` on unsafe browser requests. CORS credentials are enabled; allowed and trusted origins come from environment variables.
- **Case access:** patient case querysets are owner-scoped. Clinician queues include unassigned and self-assigned cases; intake, review, AI details, activities, consent details, and report downloads require assignment where applicable. Patients cannot access clinician-only routes. Backend checks remain authoritative.
- **Consent:** report upload and intake-chat confirmation require active consent. Consent withdrawal is audited and prevents those gated operations; it does not erase retained information or uploaded reports.
- **Private reports:** local filesystem storage uses `private_uploads/` with no public URL. Content type, size (10 MiB), and file signature are checked. Downloads stream through an authenticated endpoint and are authorized against owner/assignment. Keep this directory private and durably backed up; never expose it as a static web directory.
- **Clinician notes:** `reviewer_comments` and `edited_note` are internal fields in the clinician serializer. The patient review endpoint uses a separate allowlist and never returns them or drafts. Patient request text is intentionally visible; escalation reason is clinician-only.
- **Secrets:** `.env` is ignored by git. Never commit secret keys, database credentials, AI tokens, patient data, database files, or private report files. Frontend environment values are public after build and must never contain service credentials.
- **AI safety:** AI content is advisory. Only persisted `COMPLETED` results with `is_validated=True` reach the patient allowlist. The model does not finalize reviews, approve cases, determine an emergency, or replace clinician judgment. Priority `GREEN` is not a guarantee of safety.
- **Demonstrations:** use synthetic data and synthetic reports only. Do not test with real patient or clinician personal information.

Production settings (`DJANGO_DEBUG=False`) enable SSL redirect, secure session/CSRF cookies, `nosniff`, `DENY` frame policy, and same-origin referrer policy. These settings do not by themselves establish a complete production security posture.

## AI teammate implementation checklist

- [ ] Agree with the CareFlow owner on request/response schema version, source IDs, data minimization, and patient-safe output rules; do not treat the proposed schema above as accepted without agreement.
- [ ] Deliver a working Python integration function or authenticated HTTP service. Document its exact invocation, endpoint, auth, request, response, supported versions, and dependency list.
- [ ] Deliver synthetic request/response samples and a local run guide. Do not use real patient data in fixtures.
- [ ] Validate input sizes/types and output envelope/nested fields, enums, schema version, case correlation, evidence references, and allowed sources.
- [ ] Define explicit behavior for absent information, unclear/contradictory answers, no identified alerts, and advisory priority. Never turn missing data into a negative clinical finding or fabricate evidence.
- [ ] Define timeout, retry/backoff, idempotency/deduplication, safe error codes, logging, and service-unavailable behavior. Keep PHI, prompts, credentials, and tracebacks out of patient errors.
- [ ] Coordinate a trusted CareFlow backend consumer/worker that creates and updates `AIResult` rows for the correct case; set `PENDING` only after work actually begins and `is_validated=True` only after validation. No such caller, worker, callback, or write API exists today.
- [ ] Keep persistence inside the CareFlow backend integration. The pipeline must not write directly to CareFlow's database or bypass backend authorization/validation.
- [ ] Do not write clinician reviews, patient comments, case completion statuses, diagnoses, or final clinical decisions. Only a clinician can finalize the clinical review.
- [ ] Add tests for valid output, malformed JSON, wrong/missing fields, invalid enum/status/schema, mismatched case ID, fabricated/unknown source references, timeout, HTTP errors, unavailable service, duplicate/idempotency behavior, and patient-safe persistence.
- [ ] Add and document every new dependency and environment variable. Update `.env.example` with names and blank/example-safe placeholders only; never add credentials.
- [ ] Document how to run the service/worker and its tests locally, how to populate synthetic `AIResult` fixtures, and how the patient/clinician status is advanced.
- [ ] Coordinate backend endpoint, persistence, and frontend trigger changes with the CareFlow owner before presenting the integration as complete.

## Deployment status and limitations

### Implemented and locally verified

- Django/DRF API and React/Vite application run locally.
- Default database is SQLite. Migrations are applied through Django and preserve rows; see commands above.
- Session auth, CSRF, configured CORS support, role-aware APIs, private local report download, and review privacy controls are present.
- Current automated Django tests and frontend lint/build have been run in the development environment (see verification below).

### Configured but not production-verified

- PostgreSQL selection through `DATABASE_URL` and `psycopg` dependency.
- Production security flags in Django settings.
- Vite production build. Hosting, TLS termination, static serving, reverse-proxy behavior, cookie domains, and deployment settings have not been validated on a deployed environment.
- Private file storage currently uses local `private_uploads/`. Production must provide a private durable volume or an authorized private object-storage backend, plus restore-tested backups and retention controls. An object-storage adapter is not implemented.

### Pending or requiring confirmation

- AI service ownership, reachable URL, auth, request schema, response schema, semantic definitions, timeout/retries, idempotency, asynchronous behavior, persistence consumer, and production secret names/values.
- Product/policy decision on the exposed clinician case-delete endpoint and appointment-delete behavior.
- Production data retention/deletion, audit retention, incident response, monitoring, and database/file restore procedures.
- Browser/manual testing across patient, clinician, and administrator workflows.
- Whether external report storage, OCR, notifications, or voice features are in scope. They are not implemented here.

No database reset, GitHub push, or deployment is part of this handoff.

## Verification and manual review

Commands available in this repository:

```powershell
python manage.py test
python manage.py check
python manage.py makemigrations --check --dry-run
Set-Location frontend
npm run lint
npm run build
```

Latest recorded application verification before this documentation-only edit: Django test suite **53 tests passed**, `manage.py check` clean, migration consistency reported no changes, frontend lint passed, and Vite production build succeeded. These checks ran locally with SQLite; PostgreSQL and a live AI service were not tested. No browser verification is claimed.

Manual review after starting both servers should cover: patient and clinician registration; staff approve/reject; session persistence/logout; patient case isolation; consent grant/withdrawal; report upload, owner/assignment downloads, and invalid files; intake chat and consent-gated confirmation; assignment and escalation handoff; draft/request/finalized review privacy; appointment claim/status changes; AI status/result visibility; and narrow/mobile case detail layout.

Keep `.env`, `db.sqlite3`, and `private_uploads/` out of version control. Never reset a database containing data to resolve a migration issue.
