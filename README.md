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

### Week 2 — PDF Text Extraction & Optical Character Recognition (OCR)

The objective of Week 2 was to implement document text extraction functionality for digital PDFs, scanned PDFs, and images. The extraction system was developed using PyMuPDF and Tesseract OCR and integrated with the existing Django file-processing application.

The implementation focuses on automatically identifying the appropriate extraction method, processing documents page by page, handling invalid documents, and returning extracted text in a consistent JSON response format.

#### 1. Development Environment and Configuration

Configured the Python development environment and installed the required libraries for PDF processing, image handling, and OCR.

**Libraries and tools configured:**

- **PyMuPDF:** Used for opening PDF documents, validating PDF files, rendering PDF pages, and extracting digital PDF text.
- **Tesseract OCR:** Used as the OCR engine to recognize text from scanned documents and images.
- **pytesseract:** Python wrapper used to communicate with the Tesseract OCR engine.
- **Pillow:** Used for opening, validating, and processing image files.
- **pytest:** Used for automated testing of the extraction modules.
- **Django:** Used to integrate the extraction functionality into the existing API.

Tesseract OCR was installed separately on Windows and configured in the Python extraction module using its executable path:

```python
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)
```

Verified the Tesseract installation and its availability from the development environment.

#### 2. Digital PDF Text Extraction

Developed the `pdf_extractor.py` module to extract text from digitally generated PDF documents using PyMuPDF.

**Implementation process:**

1. Accept the PDF file path as input.
2. Verify that the file exists and has a valid PDF extension.
3. Check whether the file is empty.
4. Open the PDF document using PyMuPDF.
5. Check whether the PDF is encrypted or contains readable pages.
6. Iterate through each page of the document.
7. Extract text from individual pages using PyMuPDF's text extraction functionality.
8. Combine the extracted page content into a complete document text.
9. Return the extracted information in a structured dictionary.

**Output information includes:**

- Original filename.
- Total number of pages.
- Extraction method.
- Extraction status.
- Complete extracted text.
- Individual page numbers and their extracted text.

The module also handles missing files, empty PDFs, corrupted documents, encrypted PDFs, and PDFs without extractable text.

#### 3. Scanned PDF and Image OCR

Developed the `ocr_extractor.py` module to recognize text from scanned PDF documents and image files using Tesseract OCR.

Unlike digital PDFs, scanned documents generally contain page images instead of directly extractable text. OCR is therefore required to recognize their contents.

**A. Image OCR implementation**

1. Accept PNG, JPG, or JPEG image files.
2. Verify that the image exists and is not empty.
3. Validate the image using Pillow.
4. Convert the image into RGB format for processing.
5. Pass the image to Tesseract OCR.
6. Recognize and extract the available text.
7. Return the extracted text in the standardized output structure.

**B. Scanned PDF OCR implementation**

1. Accept a scanned PDF document.
2. Open the document using PyMuPDF.
3. Validate the PDF and check its page count.
4. Iterate through the PDF pages individually.
5. Render each page into an image using a higher-resolution rendering matrix.
6. Convert the rendered page into an RGB image.
7. Pass each page image to Tesseract OCR.
8. Extract recognized text from every page.
9. Combine the extracted content and return page-wise results.

This approach allows the application to process scanned PDFs even when their pages do not contain directly selectable text.

#### 4. Automatic Extraction Service

Developed `extraction_service.py` to coordinate the PDF and image extraction modules.

The extraction service determines which method should be used based on the uploaded document type and its contents.

**Extraction workflow:**

1. Receive the document path.
2. Identify the document extension.
3. For PDF files, first call the PyMuPDF extraction module.
4. Check the extraction status.
5. If digital text is successfully extracted, return the PyMuPDF result.
6. If the PDF contains no extractable text, automatically call the scanned PDF OCR module.
7. For PNG, JPG, and JPEG files, directly call the image OCR module.
8. Return the extraction result in a consistent format.
9. Reject unsupported extraction formats with an appropriate error.

**Automatic method selection:**

| Document type | Extraction method |
|---|---|
| Digital PDF | PyMuPDF |
| Scanned PDF | Tesseract OCR |
| PNG image | Tesseract OCR |
| JPG image | Tesseract OCR |
| JPEG image | Tesseract OCR |

This service avoids requiring users to manually select between digital PDF extraction and OCR.

#### 5. Django API Integration

Integrated the extraction service with the existing Django application without replacing the Week 1 file-upload implementation.

Added the extraction functionality to `documents/views.py`.

**Extraction endpoint:**

`POST /api/extract/`

The API accepts documents through a multipart form-data request using the field name `file`.

**Implementation process:**

1. Receive the uploaded document through the Django request.
2. Check whether a file has been provided.
3. Reject empty files.
4. Enforce the existing 10 MiB upload-size restriction.
5. Validate the supported extraction file extensions.
6. Create a temporary directory for document processing.
7. Save the uploaded document temporarily using a generated filename.
8. Pass the temporary file path to `extract_document_text()`.
9. Automatically select the appropriate PDF or OCR extraction method.
10. Retrieve the extracted document information.
11. Restore the original uploaded filename in the response.
12. Return the extraction result as JSON.
13. Clean up temporary files after processing.

The extraction endpoint uses a temporary storage approach so that document extraction does not require permanently saving every uploaded file.

#### 6. Error Handling and Document Validation

Implemented error handling to prevent invalid documents from interrupting the extraction workflow.

The extraction modules include checks for:

- Missing files.
- Empty files.
- Unsupported file extensions.
- Invalid or corrupted PDF documents.
- Invalid or corrupted image files.
- Encrypted PDF documents.
- PDFs without extractable text.
- Unreadable documents.
- Extraction failures.

Custom exceptions were implemented using `PDFExtractionError` and `OCRExtractionError`.

The Django API returns appropriate HTTP responses:

| HTTP status | Scenario |
|---|---|
| 200 OK | Successful text extraction |
| 400 Bad Request | Missing, empty, unsupported, or invalid document |
| 413 Payload Too Large | File exceeds the 10 MiB limit |
| 500 Internal Server Error | Unexpected server-side extraction failure |

**Windows temporary-file handling:**

During corrupted PDF testing, PyMuPDF initially raised a `FileDataError`. Windows also prevented temporary-directory cleanup because the PDF file remained locked.

To address this, PDF extraction was updated to read the document into memory using PyMuPDF's stream-based opening method:

```python
with pymupdf.open(
    stream=path.read_bytes(),
    filetype="pdf"
) as document:
```

The same approach was applied to both digital PDF extraction and scanned PDF OCR. This resolved the temporary-file locking issue observed during corrupted PDF testing.

#### 7. CSRF Protection and Postman Configuration

Configured a CSRF token endpoint to support secure POST requests through Postman.

Added the following endpoint:

`GET /api/csrf/`

The endpoint uses Django's `ensure_csrf_cookie` decorator and `get_token()` to provide a CSRF token.

**Postman testing process:**

1. Send a GET request to `http://127.0.0.1:8000/api/csrf/`.
2. Receive the CSRF token in the JSON response.
3. Allow Postman to retain the CSRF cookie.
4. Create a POST request to `http://127.0.0.1:8000/api/extract/`.
5. Add the `X-CSRFToken` header using the returned token.
6. Open Body and select form-data.
7. Create a field named `file`.
8. Change the field type from Text to File.
9. Select the document to process.
10. Send the request and inspect the JSON response.

CSRF protection was maintained without disabling Django's CSRF middleware or using `csrf_exempt` on the extraction endpoint.

#### 8. API Testing Using Postman

Tested the extraction endpoint with different document types to verify automatic method selection and error handling.

**A. Digital PDF testing**

- Uploaded a digital PDF document.
- Verified successful extraction using PyMuPDF.
- Checked the filename, page count, extraction method, status, and extracted text.
- Successfully extracted text from a two-page PDF.

**B. Scanned PDF testing**

- Uploaded a scanned PDF document.
- Verified that the document was processed through the OCR extraction workflow.
- Confirmed successful execution of the extraction endpoint.

**C. Image OCR testing**

- Created a sample invoice image containing invoice information, customer details, and total amount.
- Uploaded the image through Postman.
- Verified successful text recognition using Tesseract OCR.
- Confirmed that the API returned the extraction result in JSON format.

**D. Empty and corrupted document testing**

Tested invalid documents to verify the API's error-handling behaviour:

- Empty PDF file.
- Corrupted PDF file.
- Empty image file.
- Corrupted image file.

Verified that invalid documents are rejected instead of being processed as successful extraction requests.

During corrupted PDF testing, identified and resolved a Windows temporary-file locking issue. After the fix, the corrupted PDF request returned HTTP 400 Bad Request instead of HTTP 500 Internal Server Error.

#### 9. Automated Testing

Created dedicated automated test files for the PDF extractor, OCR extractor, and extraction service.

**Test files developed:**

- `tests/test_pdf_extractor.py`
- `tests/test_ocr_extractor.py`
- `tests/test_extraction_service.py`

**PDF extractor tests — 6 test cases**

- Successful digital PDF extraction.
- Multi-page PDF extraction.
- Missing PDF file handling.
- Empty PDF file handling.
- Corrupted PDF handling.
- PDF without extractable text.

**OCR extractor tests — 6 test cases**

- Successful image OCR.
- Successful scanned PDF OCR.
- Missing image file handling.
- Missing PDF file handling.
- Invalid image handling.
- Invalid PDF handling.

**Extraction service tests — 5 test cases**

- Automatic selection of PyMuPDF for digital PDFs.
- Automatic OCR fallback for scanned PDFs.
- Automatic image OCR selection.
- Unsupported file format handling.
- Missing PDF file handling.

**Total extraction-related automated tests: 17**

All 17 extraction-related tests passed during development.

Commands used to execute the tests:

```powershell
python -m pytest tests/test_pdf_extractor.py -v
```

```powershell
python -m pytest tests/test_ocr_extractor.py -v
```

```powershell
python -m pytest tests/test_extraction_service.py -v
```

Run all three extraction test files together:

```powershell
python -m pytest tests/test_pdf_extractor.py tests/test_ocr_extractor.py tests/test_extraction_service.py -v
```

Django configuration was also verified using:

```powershell
python manage.py check
```

#### 10. Files and Modules Developed

The following files were created or updated as part of the Week 2 extraction implementation.

**New extraction modules:**

```text
app/
└── extractors/
    ├── pdf_extractor.py
    ├── ocr_extractor.py
    └── extraction_service.py
```

**New automated test files:**

```text
tests/
├── test_pdf_extractor.py
├── test_ocr_extractor.py
└── test_extraction_service.py
```

**Existing Django application files updated for integration:**

```text
documents/
├── views.py
└── urls.py
```

The Django project URL configuration was checked to ensure the document API routes were included correctly.

#### 11. Week 2 Completion Status

The following activities were completed as part of the PDF extraction and OCR allocation:

- Python PDF-processing environment configured.
- PyMuPDF digital PDF extraction implemented.
- Tesseract OCR configured.
- Image text extraction implemented.
- Scanned PDF OCR implemented.
- Automatic extraction method selection implemented.
- Page-wise extraction and standardized JSON output implemented.
- Empty, corrupted, and unreadable document handling implemented.
- Django extraction endpoint integrated.
- CSRF-protected Postman requests configured.
- Digital PDF, scanned PDF, and image extraction tested through Postman.
- Three automated extraction test files developed.
- All 17 extraction-related automated tests passed.
- Django system configuration check passed.

**Current Status:** Week 2 PDF text extraction, scanned-document OCR, and Django API integration implemented and tested.

**Note:** CSV/Excel extraction, structured field extraction, validation, and review-interface tasks are separate team responsibilities and should be documented under their respective implementation milestones after integration.