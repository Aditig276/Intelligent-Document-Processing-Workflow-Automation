# Intelligent-Document-Processing-Workflow-Automation
A platform that automates repetitive office tasks, processes uploaded documents, and extracts  useful information.  Office teams frequently process PDFs, spreadsheets, and scanned documents manually. Repetitive data  entry can be slow and error-prone, while limited processing history makes it difficult to audit failures or  reproduce outputs.

## Current Implementation

**Week 1 — File Upload API**

The current implementation uses Django to provide a health-check endpoint and a file-upload endpoint.

### Technology Stack

- Python 3.11+
- Django
- pytest / Django test framework
- Git and GitHub
- Postman for API testing

## Features Implemented

- File upload through a REST-style HTTP endpoint.
- Validation for supported file extensions.
- Rejection of empty files and files larger than 10 MB.
- Unique filenames for stored uploads.
- SHA-256 checksum generation.
- JSON responses with file metadata.
- Automated tests for upload validation and successful uploads.

### Supported File Extensions

The current code allows:

`.pdf`, `.csv`, `.xlsx`, `.xls`, `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`

**Note:** Confirm the final supported formats with the project lead before treating this list as the agreed project specification.

## Project Setup

### 1. Clone the repository

```bash
git clone https://github.com/Aditig276/Intelligent-Document-Processing-Workflow-Automation.git
cd Intelligent-Document-Processing-Workflow-Automation
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Apply database migrations

```bash
python manage.py migrate
```

### 5. Start the development server

```bash
python manage.py runserver
```

The server runs at `http://127.0.0.1:8000/` by default.

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health/` | Check whether the API is running |
| POST | `/api/upload/` | Upload a document |

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

In Postman:

1. Select **POST**.
2. Enter the upload endpoint URL.
3. Open **Body → form-data**.
4. Set the key to `file` and change its type to **File**.
5. Select a supported file and click **Send**.

A successful upload returns HTTP `201 Created`, along with the original filename, stored filename, file size, and SHA-256 checksum.

### Validation Rules

- A file must be provided using the `file` field.
- The extension must be in the supported-extension list.
- Empty files are rejected.
- Files larger than 10 MB are rejected.

## Run Automated Tests

Run the upload API tests with:

```bash
python manage.py test documents
```

The current test suite contains five tests covering successful uploads, unsupported formats, missing files, empty files, and oversized files.

## Development Branch

Current feature branch:

`feature/file-upload-api`

GitHub branch:

https://github.com/Aditig276/Intelligent-Document-Processing-Workflow-Automation/tree/feature/file-upload-api

## Planned Work

The broader project plan includes:

- Processing-job model and status tracking.
- Document and result access controls.
- Document content extraction and structured data processing.
- Workflow automation, logging, and expanded testing.

These are planned team features and should not be considered complete until implemented and integrated.

## Project Status

The file-upload API has been implemented, tested, committed, and pushed to its feature branch. The project is still under development.
