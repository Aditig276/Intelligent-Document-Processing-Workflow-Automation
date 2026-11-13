# Week 4 - Tabular and Report Validation Results

## 1. CSV and Excel extraction

| Test case | Input | Expected result | Result |
|---|---|---|---|
| Valid CSV | valid_invoices.csv | Extract all invoice records and values | PASS |
| Valid XLSX | valid_invoices.xlsx | Extract records from the Invoices sheet | PASS |
| Missing column | missing_column.csv | Identify customer_name as missing | PASS |
| Missing column | missing_column.xlsx | Identify missing required column | PASS |
| Empty rows | empty_rows.csv | Remove fully empty rows and retain valid records | PASS |
| Malformed CSV | malformed_rows.csv | Reject inconsistent field count | PASS |
| XLS extraction | Test-generated .xls file | Extract records and remove empty rows | PASS |

## 2. Automated extractor tests

Command:
python -m pytest -v app/extractors/test_tabular_extractor.py

Result:
- 5 tests passed.
- 0 tests failed.
- 1 Pandas deprecation warning concerning the xlrd engine.

## 3. Source-data comparison

- Valid CSV extracted values matched the original source records.
- Valid Excel extracted values matched the original source records.
- Generated Excel report was independently checked against the original CSV source.
- Verified invoice: INV-1001.
- Verified customer: ABC Technologies.
- Verified amount: 15000.50.

## 4. Report-generation checks

The Excel report generator was tested in an isolated worktree of the report-generation branch.
- 6 existing Excel generator tests passed.
- Generated report values matched the original CSV source.

A PDF report generator was not found in the inspected report-generation branch. PDF extraction and OCR code were present, but these are not PDF report generation. Therefore, PDF report-content validation could not be performed.

## 5. Malformed, missing and inconsistent data observations

- Missing columns are identified by the tabular extractor.
- Fully empty rows are removed.
- Malformed CSV rows with extra fields are rejected by pandas.
- The tabular extractor performs structural extraction; it does not enforce all invoice business rules, such as requiring a non-empty invoice number or rejecting negative amounts. These require a separate validation layer.
- The Excel report generator rejects invalid negative amounts in its existing tests.

## 6. Overall result

CSV, XLSX and XLS extraction tests passed.
Excel report generation tests passed in the isolated report-generation worktree.
PDF report-content validation remains pending because a PDF report generator was not found in the inspected branch.
