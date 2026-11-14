# Week 3 – Tharun Integration Test Scenarios & Results

**Branch:** `feature/integration-tests`  
**Owner:** Tharun  
**Scope:** Report generation, background/scheduled processing, retry/failure paths, processing history and error logs.

## Test execution

From the repository root, activate the project virtual environment and install test dependencies:

```bash
python -m pip install -r requirements.txt
python -m pip install -r tests/requirements-test.txt
python -m pytest tests/test_week3_integration.py -v
```

Report, Celery and scheduling checks skip when their feature modules/routes have not yet been integrated into this branch. A skip means **not integrated / not verified**, not a pass. Re-run after report-generation and background-processing branches are integrated.

## Test cases

| ID | Scenario | Expected result |
|---|---|---|
| TC-W3-01 Excel | Generate Excel report for completed job | HTTP 200, attachment, valid XLSX ZIP signature |
| TC-W3-01 PDF | Generate PDF report for completed job | HTTP 200, attachment, PDF signature `%PDF` |
| TC-W3-02 | Generate report for unknown job | HTTP 404 |
| TC-W3-03 | Open processing history | Source filename and job/status entry are visible |
| TC-W3-04 | Execute background task for pending job | Job reaches completed state |
| TC-W3-05 | Failed job and retry | Error is recorded; retry clears error and completes (when retry is supported) |
| TC-W3-06 | Processing failure logging | Error diagnostic is emitted to application logger |
| TC-W3-07 | Submit a scheduled-processing request | Schedule endpoint accepts request (HTTP 200/201/302) |

## Result recording

| Test ID | Result (Pass/Fail/Skip) | Evidence / error |
|---|---|---|
| TC-W3-01 Excel | Pending execution | Attach pytest output |
| TC-W3-01 PDF | Pending execution | Attach pytest output |
| TC-W3-02 | Pending execution | Attach pytest output |
| TC-W3-03 | Pending execution | Attach pytest output |
| TC-W3-04 | Pending integration | Celery task + broker/worker setup |
| TC-W3-05 | Pending integration | Retry configuration + task output |
| TC-W3-06 | Pending execution | Captured log output |
| TC-W3-07 | Pending integration | Scheduler endpoint/configuration output |

> Do not mark tests passed until they have been run against the integrated Week 3 modules. Save terminal output (including skipped tests and tracebacks) with the PR as test evidence.
