# Intelligent Document Processing & Workflow Automation

A platform designed to automate repetitive office tasks, process uploaded documents, and extract useful information from PDFs, spreadsheets, and scanned files. The goal is to reduce manual data entry, improve processing reliability, and maintain a clear history of document-processing activities.

## Current Implementation

### Week 1 — File Upload API

The current implementation uses Django to provide a health-check endpoint and a file-upload API with file validation, size restrictions, content checks, and metadata generation.

### Technology Stack

- Python 3.11+
- Django
- PyMuPDF — PDF validation
- Pillow — image validation
- openpyxl — XLSX validation
- xlrd — XLS validation
- pytest / Django test framework
- Postman — API testing
- Git and GitHub

## Features Implemented

- File uploads through a REST-style HTTP endpoint.
- Validation of supported file extensions.
- Rejection of missing files and empty uploads.
- A 10 MiB maximum file-size limit.
- Basic content validation for PDFs, images, spreadsheets, and CSV files.
- Unique filenames generated using UUIDs to reduce filename conflicts.
- SHA-256 checksum generation for uploaded files.
- JSON responses containing upload metadata.
- Cleanup of partially saved files when a storage error occurs.
- CSRF protection for the upload endpoint.
- Automated tests covering successful uploads, invalid files, missing files, empty files, oversized uploads, and CSRF protection.

## Supported File Formats

The current implementation accepts the following extensions:

- **PDF:** `.pdf`
- **Spreadsheets:** `.xlsx`, `.xls`
- **CSV:** `.csv`
- **Images:** `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`

**Note:** The final supported formats and upload limits should be confirmed with the project lead before being treated as the project's agreed specification.

## Project Setup

### 1. Clone the Repository

```bash
git clone https://github.com/Aditig276/Intelligent-Document-Processing-Workflow-Automation.git
cd Intelligent-Document-Processing-Workflow-Automation
```

### 2. Create a Virtual Environment

```bash
python -m venv .venv
```

Activate it on Windows:

```bash
.venv\Scripts\activate
```

### 3. Install Dependencies

```bash
python -m pip install -r requirements.txt
```

### 4. Apply Database Migrations

```bash
python manage.py migrate
```

### 5. Start the Development Server

```bash
python manage.py runserver
```

The development server runs at:

`http://127.0.0.1:8000/`

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health/` | Check API availability |
| POST | `/api/upload/` | Upload and validate a document |

### Health Check

Send a GET request to:

`http://127.0.0.1:8000/api/health/`

Expected response:

```json
{
  "status": "healthy"
}
```

### Upload a File

Send a POST request to:

`http://127.0.0.1:8000/api/upload/`

Using Postman:

1. Select **POST**.
2. Enter the upload endpoint URL.
3. Open **Body → form-data**.
4. Create a key named `file`.
5. Change the key type from Text to **File**.
6. Select a supported file and click **Send**.

A successful upload returns HTTP `201 Created` and a JSON response containing upload metadata, including the original filename, stored filename, file size, and SHA-256 checksum.

### Validation Rules

- The request must contain a file in the `file` field.
- The file extension must be supported.
- Empty files are rejected.
- Files exceeding 10 MiB are rejected.
- Basic content checks are performed to reject files that do not match the expected format.
- Uploaded files are assigned unique stored filenames.
- Unsupported HTTP methods are rejected.

## Run Automated Tests

Execute the upload API test suite using:

```bash
python manage.py test documents
```

**Current test results:** 10 tests passed.

The test suite covers:

- Successful CSV upload.
- Unsupported file extensions.
- Missing file input.
- Empty file rejection.
- Oversized file rejection.
- Invalid PDF content.
- Invalid image content.
- Invalid XLSX content.
- Invalid CSV content.
- CSRF protection.

Run Django's configuration check with:

```bash
python manage.py check
```

## Development Branch

Current feature branch:

`feature/file-upload-api`

GitHub:

https://github.com/Aditig276/Intelligent-Document-Processing-Workflow-Automation/tree/feature/file-upload-api

## Planned Work

The broader project roadmap includes:

- Processing-job model and status tracking.
- Document and result access controls.
- PDF, spreadsheet, and image content extraction.
- Structured data processing and workflow automation.
- Processing history, error logging, and auditability.
- Expanded testing and integration of team-developed features.

These features remain planned or under development until implemented and integrated into the project.

## Project Status

The Week 1 file-upload API has been implemented, tested, committed, and pushed to the `feature/file-upload-api` branch. The upload endpoint includes file validation, size restrictions, metadata generation, and automated tests.

The overall project is still under development, with additional components being developed by the team.
