# Report Access Control & Authorization (Week 3)

**Project:** Intelligent Document Processing & Workflow Automation
**Module:** Report Access Control
**Assigned Engineer:** Member 4 (Brijesh)
**Branch:** `feature/report-access-control`
**Status:** Implemented & Verified

---

## 1. Purpose of the Access-Control Module

The Week 3 Report Access Control module provides server-enforced, multi-tenant authorization for:
1. **Source Documents:** The original uploaded files stored on the server.
2. **Generated Reports:** Both Excel (`.xlsx`, `.xls`) and PDF (`.pdf`) reports generated from extracted document data.
3. **Processing History & Job Details:** Multi-tenant isolation for dashboard views and REST API endpoints.

This module guarantees that:
- Unauthenticated users cannot view or download documents, reports, or history.
- Authenticated users can access **only** resources they own.
- No user can download another user's documents or reports by manipulating identifiers in request URLs (Insecure Direct Object Reference / IDOR prevention).
- Filesystem path traversal attempts are strictly prevented.

---

## 2. Security Architecture

The architecture follows the **Deny by Default** security principle, enforcing authorization at the object level before file system I/O or database exposure:

```
[ HTTP Client / Browser / API ]
             â”‚
             â–¼
[ Authentication Middleware / RFC 7617 Basic Auth ]
             â”‚
      (Authenticated?)
       â”œâ”€â”€ No  â”€â”€â–º [ 401 / 302 Redirect to Login ]
       â””â”€â”€ Yes â”€â”€â–º (Active User?)
                     â”œâ”€â”€ No  â”€â”€â–º [ 403 Forbidden ]
                     â””â”€â”€ Yes â”€â”€â–º [ Ownership & Object Authorization ]
                                        â”‚
                                 (User == Owner?)
                                  â”œâ”€â”€ No  â”€â”€â–º [ 404 Not Found (IDOR Shield) ]
                                  â””â”€â”€ Yes â”€â”€â–º [ Confinement & Safe File Serving ]
                                                     â”‚
                                              (Path Traversal Check)
                                               â”œâ”€â”€ Failed  â”€â”€â–º [ 404 Not Found ]
                                               â””â”€â”€ Success â”€â”€â–º [ Stream FileResponse with nosniff ]
```

### Core Architecture Components:
- **`app.security.permissions`:** Pure Python domain policy definitions (`AuthenticatedUser`, `OwnedResource`, `can_upload_document`, `can_access_document`, `can_access_result`, `can_download_report`).
- **`app.security.django_adapter`:** Bridges Django's `request.user` and database models (`ProcessingJob`) to the domain policy. Provides `can_django_user_access_document`, `can_django_user_download_report`, `can_django_user_access_history`, `get_authorized_job_or_404`, and `filter_user_processing_history`.
- **`processing_jobs.security`:** Safe binary file streaming (`serve_secure_file`), path normalization, directory confinement validation against `MEDIA_ROOT`, and header injection sanitization (`sanitize_filename`).
- **`processing_jobs.reports`:** Report integration contract and resolution engine (`resolve_report_for_job`, `register_report_resolver`).
- **`processing_jobs.views` & `api_views`:** Server-rendered views and REST endpoints enforcing authentication and ownership checks.

---

## 3. Authentication and Authorization Flow

### Browser Flow:
1. Requests to `/dashboard/`, `/job/<id>/`, `/job/<id>/document/`, or `/job/<id>/report/<type>/` pass through Django `SessionMiddleware` and `AuthenticationMiddleware`.
2. Protected views use the `@login_required` decorator. If unauthenticated, the user is redirected to `LOGIN_URL` (`/accounts/login/`).
3. View calls `get_authorized_job_or_404(request.user, job_id)`.
4. If the job does not exist or `job.owner != request.user`, an `Http404` is raised. This deliberately conceals the existence of other users' jobs.
5. The view checks the relevant permission predicate (`can_django_user_access_document` or `can_django_user_download_report`).
6. The file is streamed as a download attachment with safe MIME and header attributes.

### API Flow:
1. API endpoints `/api/jobs/`, `/api/jobs/<id>/`, `/api/jobs/<id>/document/`, and `/api/jobs/<id>/report/<type>/` call `authenticate_api_request(request)`.
2. Supports both active Django sessions and RFC 7617 HTTP Basic Authentication.
3. If credentials are missing, returns `401 Unauthorized` with `WWW-Authenticate: Basic realm="API"`.
4. If credentials are invalid, returns `401 Unauthorized`.
5. If the account is inactive (`is_active=False`), returns `403 Forbidden`.
6. Authorized user queries are automatically constrained via `filter_user_processing_history(user)`.

---

## 4. Source-Document Ownership Checks

Original uploaded documents are referenced by `ProcessingJob.storage_reference` in `settings.MEDIA_ROOT`.

- **Endpoint:** `GET /job/<job_id>/document/` (Browser) and `GET /api/jobs/<job_id>/document/` (API).
- **Ownership Verification:** `can_django_user_access_document(request.user, job)`.
- **Path Confinement:** `serve_secure_file()` resolves the path and calls `candidate.relative_to(settings.MEDIA_ROOT)`. Any path traversal (`../`) is caught and returns `404 Not Found`.
- **Storage Safety:** If the file is missing from disk, safe `404` is returned without leaking internal server directory paths.

---

## 5. Excel and PDF Report Download Permissions

The application protects both Excel spreadsheets and PDF summaries:

- **Browser Endpoints:**
  - `GET /job/<job_id>/report/excel/` (or `/job/<job_id>/report/<str:report_type>/`)
  - `GET /job/<job_id>/report/pdf/`
- **API Endpoints:**
  - `GET /api/jobs/<job_id>/report/excel/`
  - `GET /api/jobs/<job_id>/report/pdf/`
- **Supported Report Types:**
  - **Excel:** `excel`, `xlsx`, `xls` -> MIME `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
  - **PDF:** `pdf` -> MIME `application/pdf`
- **Ownership Verification:** `can_django_user_download_report(request.user, job)`.
- **Resolution Strategy:** `resolve_report_for_job()` searches:
  1. Pluggable custom resolvers (registered by Mallikarjun's `feature/report-generation`).
  2. Model attributes on `ProcessingJob` (e.g. `report_excel`, `report_pdf`).
  3. Standard media subdirectories (`MEDIA_ROOT / "reports" / f"job_{job.id}_report.xlsx"`, etc.).
- If the report has not been generated yet or the file is missing, a safe `404 Not Found` response is returned.

---

## 6. Processing-History Permissions

Processing history displays past and ongoing jobs:

- **Browser Dashboard (`/dashboard/`):**
  Uses `filter_user_processing_history(request.user)` to retrieve only jobs where `owner == request.user`.
- **API History (`/api/jobs/` and `/api/history/`):**
  - Scopes all queries strictly to the authenticated user.
  - Supports filtering by `status` (e.g., `status=completed`, `status=failed`) and `file_type` (e.g., `file_type=csv`).
  - Supports pagination (`page`, `page_size` with bounds `1 <= page_size <= 100`).
  - Returns metadata and links to `/job/<id>/document/`, `/job/<id>/download/`, and `/job/<id>/report/<type>/`.
  - Never leaks other users' records during filtering or pagination.
- **Legacy Unowned Records:**
  Jobs where `owner is None` are treated as unowned and are inaccessible to standard users (`404 Not Found`).

---

## 7. Reusable Permission Functions and Services

Located in `app/security/django_adapter.py`:

```python
actor_from_django_user(django_user: object) -> AuthenticatedUser | None
can_django_user_upload(django_user: object) -> bool
can_django_user_access_job(django_user: object, job: object) -> bool
can_django_user_access_document(django_user: object, job_or_doc: object) -> bool
can_django_user_download_report(django_user: object, job_or_report: object) -> bool
can_django_user_access_history(django_user: object, job_or_record: object) -> bool
get_authorized_job_or_404(django_user: object, job_id: object) -> ProcessingJob
filter_user_processing_history(django_user: object, queryset=None) -> QuerySet
```

File security service in `processing_jobs/security.py`:
```python
serve_secure_file(file_path, download_filename, content_type=None, base_dir=None) -> FileResponse
sanitize_filename(filename: str) -> str
```

---

## 8. API / View Integration Points

| URL Route | Methods | Authentication | Authorization Scope |
|---|---|---|---|
| `/upload/` | GET, POST | Session (@login_required) | Active authenticated user |
| `/dashboard/` | GET | Session (@login_required) | Scoped to `owner=request.user` |
| `/job/<job_id>/` | GET | Session (@login_required) | Job owner only |
| `/job/<job_id>/document/` | GET | Session (@login_required) | Job owner only |
| `/job/<job_id>/download/` | GET | Session (@login_required) | Job owner only |
| `/job/<job_id>/report/<type>/` | GET | Session (@login_required) | Job owner only |
| `/api/upload/` | POST | Session or Basic Auth | Active authenticated user |
| `/api/jobs/` | GET | Session or Basic Auth | Scoped to `owner=request.user` |
| `/api/jobs/<job_id>/` | GET | Session or Basic Auth | Job owner only |
| `/api/jobs/<job_id>/document/` | GET | Session or Basic Auth | Job owner only |
| `/api/jobs/<job_id>/report/<type>/`| GET | Session or Basic Auth | Job owner only |

---

## 9. Error-Handling Behavior

- **401 Unauthorized:** Missing or invalid API Basic Auth credentials, with `WWW-Authenticate: Basic realm="API"`.
- **302 Redirect:** Unauthenticated browser requests redirected to `/accounts/login/?next=...`.
- **403 Forbidden:** Inactive/disabled user account or account lacking upload permission.
- **404 Not Found:**
  - Non-existent resource ID.
  - Resource owned by another user (deliberately disguises existence to prevent IDOR enumeration).
  - Legacy resource with no owner.
  - Resource where requested report or document file is missing from disk.
  - Path traversal attempt detected.
  - Invalid report type.
- **500 Internal Server Error:** Unexpected exceptions logged securely without leaking stack traces or credentials in response.

---

## 10. Automated Test Coverage

The module is verified by:
1. `tests/test_permissions.py` (Week 1 domain permission unit tests)
2. `tests/test_django_adapter.py` (Adapter unit tests)
3. `tests/test_job_auth_ownership.py` (View ownership integration tests)
4. `tests/test_report_access_control.py` (Week 3 comprehensive report access control suite)

Coverage Breakdown:
- **Authentication:** Anonymous and inactive user denials across UI and API.
- **Report Protection:** Excel and PDF download permissions, owner access, foreign user rejection, IDOR attempts, invalid types.
- **Source Document Protection:** Owner download, foreign user rejection, path traversal rejection (`../../etc/passwd`).
- **Processing History:** Dashboard scoping, API isolation, status and file-type filtering, pagination.
- **Edge Cases:** Unowned legacy records, missing files, malformed identifiers, filename sanitization.

---

## 11. Dependencies on Other Team Members

| Teammate | Assigned Branch | Integration Contract | Status |
|---|---|---|---|
| **Member 4 (Brijesh)** | `feature/report-access-control` | Access control for documents, reports & history | **Complete** |
| **Mallikarjun** | `feature/report-generation` | Stores Excel/PDF reports in `MEDIA_ROOT/reports/` or registers resolver via `register_report_resolver()` | Interface contract ready |
| **Team Lead** | `feature/processing-history` | Uses `filter_user_processing_history(request.user)` for multi-tenant isolation | Compatible |
| **Bhanu** | `feature/background-processing` | Preserves `job.owner` during asynchronous background task transitions | Compatible |
| **Tharun** | `feature/integration-tests` | Runs test fixtures and end-to-end integration tests | Ready |

---

## 12. Setup and Testing Commands

Run the Django checks:
```bash
python manage.py check
python manage.py makemigrations --check
```

Run pytest on the access control test suite:
```bash
pytest tests/test_report_access_control.py
pytest tests/test_django_adapter.py
pytest tests/test_job_auth_ownership.py
```

Run the complete test suite:
```bash
pytest
```

---

## 13. Known Limitations and Pending Integration Work

1. **Report Generation Integration:**
   `feature/report-generation` by Mallikarjun is being developed in parallel. Our resolution engine supports both conventional directory storage (`MEDIA_ROOT/reports/job_<id>_report.xlsx`) and dynamic registration (`register_report_resolver`). When Mallikarjun's branch is merged, reports will be served immediately with zero code changes required in the access-control module.
2. **Administrator Role:**
   As per project policy, administrators do not currently bypass owner checks. If administrative audit views are approved in future sprints, an explicit `is_staff` permission flag can be incorporated into `app/security/permissions.py`.
