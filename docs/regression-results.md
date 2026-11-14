# Week 4 – Regression and Integration Test Results

## Environment
- OS: Ubuntu on WSL
- Python: 3.12.3
- Django: 6.1.2
- Pytest: 9.2.0

## Final Test Results
- Full test suite: 387 passed
- Failed tests: 0
- Errors: 0
- Execution time: 94.58 seconds
- Extraction and validation batch: 79 passed

## Areas Tested
- File upload and API validation
- CSV, Excel, PDF and image extraction
- OCR extraction
- Field validation and review workflow
- Processing job status and lifecycle
- Retry handling and partial failures
- User access control and permissions
- Reports and download access
- Duplicate file submissions

## Fix Applied
The OCR extractor used a hardcoded Windows Tesseract path.
Updated configuration to use the Windows executable when available,
otherwise locate Tesseract using shutil.which().
Verified Tesseract in WSL at /usr/bin/tesseract.
OCR tests pass after the fix.

## Behavior Requiring Team Confirmation
Identical file content submitted twice is currently accepted as two
separate processing jobs (HTTP 201 responses, distinct job IDs).
Both submissions have the same SHA-256 hash.

Confirm with the team lead whether duplicate submissions should be
rejected or whether the current behavior is expected.

## Conclusion
The full test suite completed successfully with 387 passed tests
and no failures or errors. Duplicate submission behavior requires
team confirmation.