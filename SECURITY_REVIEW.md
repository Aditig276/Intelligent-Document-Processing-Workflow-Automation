# Security Review & Permission Fixes Report

**Project:** Intelligent Document Processing & Workflow Automation
**Responsibility:** Week 4 Security Review and Permission Fixes
**Branch:** `feature/security-review`
**Base Branch:** `main`
**Auditor / Engineer:** Senior Application Security Engineer & Django Security Auditor
**Date:** November 2026
**Status:** Completed & Verified

---

## 1. Project Security Review Overview

This security review assesses the Django backend of the **Intelligent Document Processing & Workflow Automation** system. The application handles sensitive document ingestion, OCR and PDF extraction, structured financial validation, multi-tenant processing history, and report generation (Excel and PDF exports).

The objective of Week 4 was to perform an end-to-end security audit across authentication, authorization, access control, file storage, input validation, secret hygiene, logging, and temporary file management, and to implement targeted, production-grade defensive fixes without breaking existing functionality or overwriting teammates' contributions.

---

## 2. Audit Scope

The audit covered the following codebase components:

| Area | Key Files & Modules Inspected |
|---|---|
| **Core Architecture & Settings** | `config/settings.py`, `config/urls.py`, `config/wsgi.py`, `.env.example`, `.gitignore` |
| **Authentication & Access Control** | `processing_jobs/api_auth.py`, `app/security/permissions.py`, `app/security/django_adapter.py` |
| **Job Management & Web Views** | `processing_jobs/views.py`, `processing_jobs/urls.py`, `processing_jobs/models.py` |
| **REST APIs & Upload Pipelines** | `processing_jobs/api_views.py`, `processing_jobs/services.py`, `documents/views.py`, `documents/urls.py`, `documents/upload_handlers.py` |
| **Secure File Serving & Confinement** | `processing_jobs/security.py`, `processing_jobs/reports.py` |
| **Background Processing & Workers** | `processing_jobs/management/commands/process_pending_jobs.py` |
| **Logging & Signal Auditing** | `processing_jobs/signals.py`, Django logging configuration in `config/settings.py` |
| **Test Suites** | `tests/test_access_control_integration.py`, `tests/test_job_auth_ownership.py`, `tests/test_report_access_control.py`, `tests/test_upload_api.py`, `tests/test_unified_upload.py`, `tests/test_logging_system.py`, `tests/test_security_review.py` |

---

## 3. Authentication Review

### Findings & Architecture
- **Web UI Session Authentication:** Protected views enforce `@login_required` redirecting unauthenticated requests to `settings.LOGIN_URL` (`/accounts/login/`). Inactive user sessions are rejected.
- **REST API Authentication:** Implemented via `authenticate_api_request()` in `processing_jobs/api_auth.py`. Supports RFC 7617 HTTP Basic Authentication and active authenticated Django sessions.
- **Header & Token Validation:** Authentication headers are validated against malformed tokens and unsupported schemes, returning `401 Unauthorized` with `WWW-Authenticate: Basic realm="API"` without leaking internal state.
- **Signal Tracking:** Django authentication signals (`user_logged_in`, `user_logged_out`, `user_login_failed`) record client IP and username while strictly omitting plaintext passwords.
- **Vulnerabilities Identified & Remediated:**
  - `documents/views.py` (`extract_file`): The `/api/extract/` endpoint lacked authentication. It has now been secured with `authenticate_api_request()`.
  - `documents/views.py` (`extraction_review`): Lacked `@login_required`. It has now been decorated with `@login_required`.

---

## 4. User Ownership Review

### Findings & Architecture
- **Object-Level Authorization Architecture:** Enforced through `app/security/permissions.py` and `app/security/django_adapter.py`. Resources are modeled with `OwnedResource(resource_id, owner_user_id)`.
- **Database Model:** `ProcessingJob` defines an explicit `owner` foreign key with `on_delete=models.CASCADE`.
- **Queryset Multi-Tenant Isolation:** `filter_user_processing_history(request.user)` confines queries strictly to `owner=request.user`, returning `none()` for anonymous or inactive users.
- **IDOR Defense:** Direct object lookups in `get_authorized_job_or_404()` raise `Http404` instead of `Http403` for missing, unowned, or foreign jobs, preventing resource enumeration.
- **Vulnerabilities Identified & Remediated:**
  - `documents/views.py` (`extraction_review`): Previously used `if job.owner_id and job.owner_id != request.user.id:` which allowed any user to view and modify unowned jobs (`owner_id=None`). Fixed to strictly enforce `can_django_user_access_job(request.user, job)`.

---

## 5. Document and Report Access Review

### Findings & Architecture
- **Direct Media URL Blocking:** Django settings do not wire `settings.MEDIA_URL` into `urlpatterns`. File assets cannot be accessed via direct static URLs.
- **Source Document Downloads:** Protected via `processing_jobs:download_document` and `/api/jobs/<job_id>/document/`. Both verify `can_django_user_access_document()` before delegating to `serve_secure_file()`.
- **Report Downloads (Excel & PDF):** Protected via `processing_jobs:download_report` and `/api/jobs/<job_id>/report/<report_type>/`. Both verify `can_django_user_download_report()` and canonicalize report types before resolution.
- **Extraction Result JSON:** Protected via `processing_jobs:download_result` ensuring only the job owner can download or trigger on-demand extraction.
- **Vulnerabilities Identified & Remediated:**
  - `download_result` omitted `X-Content-Type-Options: nosniff` header on direct `HttpResponse`. Added explicitly.
  - `download_result` on-demand extraction caught only narrow exceptions, risking 500 crashes and exposing raw exceptions. Fixed to catch general exceptions, log detailed traceback on server with `exc_info=True`, save a generic user-facing message (`"Document extraction failed. Please verify the file and try again."`), and return a clean 404.

---

## 6. File Storage Security & Confinement Review (`processing_jobs/security.py`)

### Findings & Analysis: TOCTOU and File Confinement
- **Does `os.fstat()` alone prevent a file outside `MEDIA_ROOT` from being opened after path validation?**
  **No.** `os.fstat(fd)` verifies only metadata of the open file descriptor—specifically `stat.S_ISREG(fd_stat.st_mode)` checks that the descriptor is a regular file (rather than a FIFO, pipe, directory, or socket). If an attacker substitutes a path with a regular file outside `MEDIA_ROOT` (e.g. `C:\Windows\System32\drivers\etc\hosts` or `/etc/passwd`) via a Time-of-Check to Time-of-Use (TOCTOU) race condition between path validation and `candidate.open()`, `os.fstat()` will report `S_ISREG == True`.
- **Multi-Layered Descriptor Confinement Implemented:**
  1. **Pre-Open Stat Recording:** `expected_stat = candidate.stat()` records the file device and inode before opening.
  2. **Descriptor Regular File Verification:** `stat.S_ISREG(fd_stat.st_mode)` verifies that the open descriptor is a regular file.
  3. **Identity Verification (`samestat`):** `os.path.samestat(expected_stat, fd_stat)` verifies that the opened file descriptor references the exact same inode/device as the pre-validated path, defeating file replacement races.
  4. **Open Descriptor Canonical Confinement:** `_get_descriptor_path(file_handle)` queries the operating system kernel for the real target path of the open file descriptor:
     - On Windows: Uses `msvcrt.get_osfhandle(fd)` and `ctypes.windll.kernel32.GetFinalPathNameByHandleW`.
     - On Linux: Resolves `/proc/self/fd/{fd}` via `readlink`.
     - Enforces `real_fd_path.relative_to(root)`, raising `Http404` and immediately closing the file handle if the open descriptor escapes `MEDIA_ROOT`.

### Filename Sanitization & Content-Type Whitelisting
- **Filename Sanitization:** `sanitize_filename()` strips directory traversal sequences (`..`), leading/trailing dots and spaces, control characters, and falls back to `"download"` if the result is empty or equals `"."` or `"`..`"`.
- **Content-Type Whitelisting:** Caller-supplied `content_type` is checked against `ALLOWED_SERVE_CONTENT_TYPES` and checked for CRLF (`\r`, `\n`). Any untrusted, malformed, or injected value is rejected and safely falls back to `CONTENT_TYPE_MAPPING[ext]` or `"application/octet-stream"`.
- **MIME Sniffing Defense:** `X-Content-Type-Options: nosniff` is enforced on all served responses.

---

## 7. Input Validation & Exception Disclosure Review

### Findings & Architecture
- **Upload Handlers:** `documents.upload_handlers.LimitUploadSizeHandler` terminates transfers exceeding 10 MiB, setting `request.upload_too_large = True`.
- **File Type & MIME Whitelisting:** Both browser and API upload endpoints enforce `ALLOWED_EXTENSIONS` (`.pdf`, `.csv`, `.xlsx`, `.xls`, `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`).
- **Server-Side Filename Generation:** Files are stored under random `uuid.uuid4().hex` filenames on disk.
- **Exception Sanitization & Information Disclosure Prevention:**
  - `sanitize_error_message(error)` strips internal server paths, drive letters (`C:\...`), unix hierarchies (`/var/...`), `[MEDIA_ROOT]`, and `[BASE_DIR]`.
  - In `download_result()`, failures store a generic message: `"Document extraction failed. Please verify the file and try again."` while logging detailed exceptions with `exc_info=True`.
  - In `extract_job()`, sanitized messages (`clean_msg[:2000]`) are stored and detailed tracebacks are logged on the server.
  - In `process_pending_jobs.py` (`_mark_job_failed`), error messages are sanitized with `sanitize_error_message(error)` before database persistence.
  - In `documents/views.py` (`extract_file`), raw `FileNotFoundError` paths are replaced with `"Requested file could not be found."`.
  - Browser upload view `upload_document` inspects `request.upload_too_large` after accessing `request.FILES`, reporting the 10 MB limit cleanly.

---

## 8. Secret and Environment Security

### Findings & Architecture
- **Git Hygiene:** `.gitignore` properly excludes `.env`, `.env.*`, `db.sqlite3`, `media/`, `uploads/`, `*.log`, and Python caches.
- **Configuration Templates:** `.env.example` contains only benign placeholders and development fallbacks.
- **Fail-Fast Secret Key:** When `DEBUG=False`, `config/settings.py` raises `ImproperlyConfigured` if `DJANGO_SECRET_KEY` is not provided.
- **Production Hardening:**
  - Added explicit `SESSION_COOKIE_HTTPONLY = True`.
  - Added explicit global `X_FRAME_OPTIONS = "DENY"`.
  - Configured conditional flags for `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, and HSTS.

---

## 9. Logging and Sensitive Information

### Findings & Architecture
- **Safe Logging Wrapper:** `safe_log()` protects application flows from crashing if the logging backend encounters I/O errors.
- **Rotating File Handler:** `app.log` utilizes a `RotatingFileHandler` with 10 MiB limit and 5 backup files.
- **Credential & Secret Protection:**
  - Authentication failure logs record only usernames and IPs; passwords and tokens are never logged.
  - Secret keys and authentication headers are excluded from log formats.
  - Internal filesystem paths are omitted from error messages returned to clients.

---

## 10. Temporary File Handling & Lifecycle Security

### Findings & Architecture
- **Context Management:** `tempfile.TemporaryDirectory()` is used in `documents/views.py` (`extract_file`), guaranteeing that the temporary directory is deleted upon exit on both successful extraction and extraction failure.
- **Failed Ingestion Rollback:** In `processing_jobs/services.py` (`ingest_document()`), atomic database transactions unlink written disk files if a database error occurs during job creation.
- **Failed Upload Rollback:** In `documents/views.py` (`extraction_review()`), `file_path.unlink(missing_ok=True)` deletes uploaded files if text extraction fails.

---

## 11. Confirmed Security Findings & Remediation Matrix

| # | Finding | Vulnerability Type | File | Severity | Status |
|---|---|---|---|---|---|
| **SEC-01** | Missing `@login_required` and Broken Object-Level Authorization (IDOR) on extraction review | IDOR / Broken Access Control | `documents/views.py` | **High** | **FIXED** |
| **SEC-02** | Unauthenticated access to CPU-intensive text extraction endpoint (`/api/extract/`) | Unauthenticated API / DoS risk | `documents/views.py` | **High** | **FIXED** |
| **SEC-03** | Internal filesystem path disclosure in extraction exception handling | Information Disclosure | `documents/views.py` | **Medium** | **FIXED** |
| **SEC-04** | Unconfined media path retrieval in review saving | Path Traversal Risk | `documents/views.py` | **Medium** | **FIXED** |
| **SEC-05** | Standalone dot-sequence and directory traversal in filename sanitization | Client-Side Path Traversal | `processing_jobs/security.py` | **Medium** | **FIXED** |
| **SEC-06** | TOCTOU race condition between path validation and file opening | Race Condition (TOCTOU) | `processing_jobs/security.py` | **Medium** | **FIXED** |
| **SEC-07** | Potential HTTP header injection via unescaped CRLF in Content-Type | Header Injection | `processing_jobs/security.py` | **Low** | **FIXED** |
| **SEC-08** | Missing `X-Content-Type-Options: nosniff` header on extraction JSON download | MIME-Sniffing Risk | `processing_jobs/views.py` | **Low** | **FIXED** |
| **SEC-09** | Broad exception unhandled and raw exception exposure in download extraction | Information Disclosure / DoS | `processing_jobs/views.py` | **Low** | **FIXED** |
| **SEC-10** | Browser upload size exceeded flag evaluated out-of-sequence | User Feedback / Validation | `processing_jobs/views.py` | **Low** | **FIXED** |
| **SEC-11** | Duplicate model field definition (`reviewed_data`) | Code Hygiene | `processing_jobs/models.py` | **Low** | **FIXED** |
| **SEC-12** | Global cookie and frame security settings implicit rather than explicit | Security Configuration | `config/settings.py` | **Low** | **FIXED** |

---

## 12. Implemented Fixes

### Fix 1: Hardened `processing_jobs/security.py`
- Updated `sanitize_filename()` to strip leading/trailing whitespace and dots, and fallback to `"download"` if the result is empty or in `(".", "..")`.
- Updated `serve_secure_file()` with multi-layered descriptor confinement: `expected_stat.stat()`, `os.fstat()`, `stat.S_ISREG`, `os.path.samestat`, and kernel descriptor path confinement via `_get_descriptor_path()`.
- Validated caller-supplied `content_type` strings against `ALLOWED_SERVE_CONTENT_TYPES`, rejecting invalid/injected values and falling back to safe extension mappings.
- Added `sanitize_error_message()` to sanitize internal server paths.

### Fix 2: Secured `documents/views.py`
- Added `@login_required` to `extraction_review()`.
- Enforced `can_django_user_access_job(request.user, job)` in `extraction_review()` to prevent cross-user and unowned job inspection/modification.
- Replaced unvalidated path concatenation with `validate_media_path(job.storage_reference, must_exist=True, expect_file=True)`.
- Added `authenticate_api_request(request)` to `extract_file()`.
- Replaced raw `FileNotFoundError` exception strings with generic error messages (`"Requested file could not be found."`).

### Fix 3: Hardened `processing_jobs/views.py`
- Added `response["X-Content-Type-Options"] = "nosniff"` to `download_result()`.
- In `download_result()`, set generic user-facing message `job.error_message = "Document extraction failed. Please verify the file and try again."` on extraction failures and logged detailed traceback with `exc_info=True`.
- In `extract_job()`, sanitized `error_message` using `sanitize_error_message(error)` and logged full exception with `exc_info=True`.
- In `upload_document()`, evaluated `request.upload_too_large` after file handler execution, providing immediate size limit error messaging.

### Fix 4: Hardened `processing_jobs/management/commands/process_pending_jobs.py`
- In `_mark_job_failed()`, sanitized stored error message via `sanitize_error_message(error)[:2000]`.
- Logged detailed failure traceback on server with `exc_info=True`.
- Preserved original worker execution logic without introducing extraneous worker retries.

### Fix 5: Cleaned `processing_jobs/models.py`
- Removed duplicate definition of `reviewed_data = models.JSONField(default=dict, blank=True)`.

### Fix 6: Hardened `config/settings.py`
- Explicitly declared `SESSION_COOKIE_HTTPONLY = True` and global `X_FRAME_OPTIONS = "DENY"`.

### Fix 7: Added Security Test Suite `tests/test_security_review.py` (29 Comprehensive Tests)
- Auth enforcement on review and extraction endpoints.
- Multi-tenant IDOR defense (User A vs User B).
- Unowned/legacy job rejection.
- Invalid job ID sanitization.
- Path traversal & TOCTOU descriptor confinement tests.
- Descriptor identity mismatch (`samestat`) test.
- Fail-closed descriptor resolution failure test (`_get_descriptor_path returning None`).
- Content-Type whitelisting and malformed input fallback tests.
- Generic error message storage and server path sanitization tests (covering UNC paths, spaces, and tracebacks).
- Platform-independent deterministic symlink rejection tests.
- Temporary directory lifecycle cleanup tests on success and failure.
- File upload unlink rollback tests on extraction failure and database error.

---

## 13. Test Results & Verification

### Test Suite Execution Summary
- **Command:** `pytest`
- **Total Tests Collected:** 405
- **Tests Passed:** 403
- **Tests Skipped:** 2
- **Tests Failed:** 0

### Explanation of the 2 Skipped Tests
The 2 skipped tests in the test suite are:
1. `tests/test_report_access_control.py::test_f8_symlink_escape_attempts_rejected_os_level`
2. `tests/test_report_access_control.py::test_g3_worker_rejects_symlink_source_and_extracted_paths_os_level`

**Reason for Skip:** On Windows, creating OS-level symbolic links with `os.symlink()` requires `SeCreateSymbolicLinkPrivilege` (Developer Mode or elevated Administrator privilege). When executed in standard unprivileged environments, the OS raises `[WinError 1314: A required privilege is not held by the client]`. The tests detect this operating system privilege restriction and skip gracefully:
```text
SKIPPED [1] tests/test_report_access_control.py: Symlink creation not supported in this environment: [WinError 1314] A required privilege is not held by the client
```

**Full Symlink Coverage via Deterministic Tests:**
Platform-independent symlink rejection is fully and deterministically tested and verified without requiring OS privileges:
- `tests/test_report_access_control.py::test_f9_symlink_rejection_is_deterministic_and_platform_independent` (PASSED)
- `tests/test_report_access_control.py::test_g4_worker_rejects_symlinks_deterministically` (PASSED)
- `tests/test_security_review.py::test_validate_media_path_rejects_symbolic_link` (PASSED)
- `tests/test_security_review.py::test_serve_secure_file_rejects_symbolic_link` (PASSED)

### Dedicated Security Test Suite (`tests/test_security_review.py`)
- **Command:** `pytest tests/test_security_review.py -v`
- **Collected:** 29
- **Passed:** 29
- **Failed:** 0

---

## 14. Known Limitations

1. **OCR Path Configuration:** `app/extractors/ocr_extractor.py` hardcodes the Windows Tesseract path (`C:\Program Files\Tesseract-OCR\tesseract.exe`). In containerized Linux deployments, `tesseract_cmd` should be set via environment variable (e.g. `TESSERACT_CMD=/usr/bin/tesseract`).
2. **Rate Limiting Cache Backend:** Local development uses `LocMemCache`. In multi-instance production deployments, Redis (`REDIS_URL`) must be enabled to ensure distributed synchronization across instances.
3. **Storage Backend:** Current file handling relies on `settings.MEDIA_ROOT` local filesystem storage. If migrated to Amazon S3 or Google Cloud Storage, `validate_media_path` and `serve_secure_file` should be paired with pre-signed URLs or dedicated cloud storage adapters.

---

## 15. Remaining Recommendations

1. **Automated Dependency Scanning:** Introduce `safety` or `pip-audit` into the GitHub Actions CI/CD pipeline to continuously monitor dependencies for known CVEs.
2. **Content Security Policy (CSP):** Add `django-csp` middleware to enforce strict Content Security Policies, restricting inline scripts and unauthorized font/style origins.
3. **API Rate Limiting on Extraction:** Apply sliding-window rate limiting (via `check_rate_limit`) to `/api/extract/` in addition to the upload endpoints to safeguard against compute-intensive abuse.
