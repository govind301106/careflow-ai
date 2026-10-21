# CareFlow AI

CareFlow is a human-led case intake and clinician review workspace. Django/DRF provides session-authenticated APIs; React/Vite provides patient and clinician portals. SQLite is the local default and PostgreSQL is selected with `DATABASE_URL`. Medical reports use private local storage in development. AI output is advisory only, and clinician review remains the final decision.

## Local setup (Windows PowerShell)

From this directory (the one containing `manage.py`):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `DJANGO_SECRET_KEY` to a random secret in `.env`; set `DJANGO_DEBUG=True` for local development. Keep `DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost`. The default database remains `db.sqlite3`; migrations do not remove or reset existing data.

```powershell
python manage.py check
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
```

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Vite uses `http://127.0.0.1:8000/api` by default. Set `VITE_API_URL` in `frontend/.env` to change it. For the default Vite origin, set `CORS_ALLOWED_ORIGINS=http://localhost:5173` and `CSRF_TRUSTED_ORIGINS=http://localhost:5173` in root `.env`. Use a consistent hostname (`localhost` or `127.0.0.1`) in browser URLs because cookies are host-specific.

## Accounts and roles

Patients may register from the portal. Registration validates the password with Django's configured validators, hashes it through `create_user`, assigns only the `Patient` group, and starts a session. It never accepts a public role field. Clinician accounts must be created by a trusted administrator and placed in the `Clinician` group through Django admin. Do not use patient self-registration to provision clinicians. Create a demo clinician from Django admin or the shell only in local demo environments.

## Main workflows and API

- Auth: `GET /api/csrf/`, `POST /api/auth/register/`, `POST /api/auth/login/`, `POST /api/auth/logout/`, `GET /api/auth/me/`.
- Patients: `GET/POST /api/cases/`; case detail, `PUT/PATCH /api/cases/{id}/intake/`, `GET/POST /api/cases/{id}/consent/`, and `POST /api/cases/{id}/attachments/`.
- Deterministic intake chat: `GET/POST /api/cases/{id}/chat/`. Prompts are rule-based, clearly labelled, ask for missing fields, and retain patient messages against the case. The patient reviews and confirms the structured intake before the confirmation action.
- Clinicians: `GET /api/cases/` is limited to unassigned and self-assigned cases. Use `PATCH /api/cases/{id}/assign/`, `PATCH /api/cases/{id}/update_status/`, `POST /api/cases/{id}/add_review/`, and read-only `GET /api/cases/{id}/ai_results/` / `activities/`.
- Patient case detail: `GET /api/cases/{id}/patient-review/` returns only the owner's finalized, patient-visible review fields. `GET /api/cases/{id}/patient-ai-suggestions/` returns an independent AI processing state and, only for a validated result, an allowlisted suggestions object.
- Appointments: `GET/POST /api/appointments/` and clinician updates on `/api/appointments/{id}/`.
- Reports: metadata at `GET /api/attachments/`, authorized bytes at `GET /api/attachments/{id}/download/`. Uploads accept PDF/JPEG/PNG up to 10 MB and require active case consent. Files are stored outside static/public paths. Back up `private_uploads/` securely; never expose it through a web server alias.

The clinician portal keeps case assignment, status, and review decisions behind backend authorization. Patients see only their own records. The UI displays missing intake information and case status. The current schema has explicit priority values but no automated urgency rules; an unassessed case stays unassessed. Do not interpret absence of a warning as clinical reassurance.

Consent withdrawal is recorded in the audit trail and prevents new report uploads and intake confirmation. Existing records and files remain for authorized case review and any applicable retention policy; withdrawal is not data erasure.

## AI pipeline integration status

There is no teammate service contract or endpoint in this repository. CareFlow therefore does not fabricate AI responses or submit clinical records to an assumed service. `web/ai_pipeline.py` provides an opt-in adapter requiring `AI_PIPELINE_URL`; optional bearer authentication uses `AI_PIPELINE_TOKEN`, and timeout uses `AI_PIPELINE_TIMEOUT` (default 8 seconds). It sends JSON by POST with an `Idempotency-Key` header and expects `schema_version`, `status`, `structured_output`, `evidence`, and `uncertainty_flags` in the JSON response. Error and malformed response handling becomes an explicit unavailable state. The adapter is not called automatically, and no pipeline response consumer currently creates `AIResult` rows.

The patient Suggestions panel is wired to persisted `AIResult` records. A row is patient-visible only when its status is `COMPLETED` and `is_validated=True`. The marker defaults to false, including for rows that predate migration `0012`; it must only be set by a trusted pipeline consumer after schema validation and patient-safety filtering. The patient endpoint does not return raw `structured_output`, internal error codes, evidence traces, or rule triggers. It allowlists these `structured_output` keys into `suggestions`: `patient_summary`, `missing_information`, `unclear_information`, `contradictions`, `urgent_alerts`, `suggested_follow_up_questions`, `suggested_priority`, `priority_explanation`, and `source_references`.

Before teammate integration, they must provide: (1) the service URL, auth, timeout, retry and idempotency behavior; (2) request schema and a versioned JSON response with the existing envelope fields above and the listed patient suggestion keys; (3) field types and null/empty behavior; (4) evidence/source-reference identifiers and the exact patient-safe text policy; (5) explicit semantics for uncertainty, contradiction, urgent alerts, triage priority, and failure; and (6) a trusted persistence callback/worker that maps `PENDING`/`COMPLETED`/`FAILED` to `AIResult` and sets `is_validated=True` only after validating the versioned shape and patient-visible content. Until those exist, the UI correctly shows not configured/not started and no AI output. AI remains advisory and never populates a clinician decision.

Before activation, agree with the AI service owner on the URL/method, authentication, exact request/response schemas, schema/model version, retry policy, idempotency retention, timeout, evidence source identifiers and excerpts, missing-information/contradiction flags, follow-up questions, priority semantics, and failure behavior. Configure these secrets only in deployment secret management. The adapter is a boundary, not yet called automatically by case submission; no AI processing occurs today. The patient assistant is deterministic, not an LLM.

## PostgreSQL

Install the pinned dependency set, including `psycopg[binary]`, and set a secret `DATABASE_URL`, for example `postgresql://careflow:password@db-host:5432/careflow`. Django parses this URL with connection health checks. Never put production credentials in source control. Run `python manage.py migrate` against the selected database.

Applying migrations creates schema only; it does not copy existing SQLite records or uploaded reports. Back up SQLite and private uploads first. For a controlled migration, stop writes, provision PostgreSQL, export data (`python manage.py dumpdata --natural-foreign --natural-primary -o data.json`), switch `DATABASE_URL`, migrate, load fixtures, verify counts, ownership and file downloads, then cut over. SQLite sequence/content types or binary uploads may need an explicitly tested migration procedure; keep the original SQLite and upload backups until verified. Do not reset either store.

## Deployment preparation

Deploy Django behind an HTTPS reverse proxy, a managed PostgreSQL service, and a separately served Vite production build. Configure `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`, exact `DJANGO_ALLOWED_HOSTS`, `DATABASE_URL`, `CORS_ALLOWED_ORIGINS`, and `CSRF_TRUSTED_ORIGINS` from a secret manager/environment. Production settings enable secure session and CSRF cookies and HTTPS redirects. Serve collected static assets from a static host/CDN; do not serve private uploads publicly.

The current upload backend is local filesystem storage (`private_uploads/`), suitable only where the disk is durable, private and backed up. Production needs a private persistent volume or a private object-storage backend with authorization, encryption, retention and backup controls; ephemeral container disks are not suitable. Configure TLS, restore-tested database backups, restricted operational access, monitoring, data retention/deletion policy and incident response before handling real patient data. No deployment has been performed.

Voice recording is not implemented. There is no browser recording, transcription, or audio source-reference flow.

## Verification

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
cd frontend
npm run lint
npm run build
```

Browser automation is not configured in this project. After starting both servers, manually verify registration and duplicate rejection, login persistence/logout, patient case isolation, consent and withdrawal, report upload/download authorization, chat follow-up and confirmation, clinician assignment/status/review, and appointment request/update.

Never commit `.env`, `db.sqlite3`, or `private_uploads/`.
