# Week 2 – Extraction and Validation Test Scenarios

This file records the shared acceptance scenarios for the tabular extraction,
field-validation and PDF/OCR tasks. Use synthetic documents only.

## A. Bhanu – CSV and Excel extraction

| ID | Test scenario / sample input | Expected result |
|---|---|---|
| TAB-01 | Valid CSV with invoice_number, vendor, invoice_date and amount | Correct headers, rows, file type and row count are returned |
| TAB-02 | Valid XLSX with an Invoices worksheet | First worksheet is read and sheet_name is reported |
| TAB-03 | XLSX with multiple worksheets | Behaviour for first-sheet selection is documented; no worksheet data is mixed |
| TAB-04 | Blank rows between valid CSV/XLSX rows | Completely empty rows are removed and counted |
| TAB-05 | Required column vendor is absent | missing_columns contains vendor; extraction does not silently invent it |
| TAB-06 | A cell is blank/NA | Missing cell is represented as null/None in JSON-compatible output |
| TAB-07 | Header has leading/trailing spaces | Header names are trimmed |
| TAB-08 | Unsupported .txt or .png file passed to tabular extractor | Clear unsupported-format error |
| TAB-09 | File path does not exist | FileNotFoundError is raised |
| TAB-10 | Empty or malformed CSV / corrupt workbook | Clear extraction error; application does not crash |
| TAB-11 | Legacy .xls workbook | Extracts successfully when the optional xlrd dependency is installed |
| TAB-12 | Large but allowed spreadsheet | Completes within the configured upload/processing limits |

## B. Brijesh – field validation

Use this synthetic record as the positive baseline:

```json
{
  "invoice_number": "INV-2026-001",
  "vendor": "Acme Test Pvt Ltd",
  "invoice_date": "2026-11-10",
  "amount": 1250.50
}
```

| ID | Test scenario / sample value | Expected result |
|---|---|---|
| VAL-01 | All required fields populated | Valid record; no errors |
| VAL-02 | Required key absent | required_field_missing error |
| VAL-03 | Required value is null | required_field_missing error |
| VAL-04 | Required value is empty string | empty_value error |
| VAL-05 | Required value contains only spaces | whitespace_value error |
| VAL-06 | Optional field absent | No required-field error |
| VAL-07 | Invoice number is 000123 | Leading zeroes are preserved |
| VAL-08 | Invoice number violates configured regex | invalid_invoice_format error |
| VAL-09 | Valid ISO date 2026-11-10 | Date accepted when ISO format is configured |
| VAL-10 | Impossible date 2026-02-30 | Date validation error |
| VAL-11 | Amount is numeric and within range | Amount accepted |
| VAL-12 | Amount is text such as "one thousand" | invalid_numeric error |
| VAL-13 | Negative amount when negatives are disallowed | numeric_out_of_range error |
| VAL-14 | Amount exceeds configured maximum | numeric_out_of_range error |
| VAL-15 | Same invoice number occurs twice | Duplicate warning/error according to configured policy |
| VAL-16 | Two records both lack the duplicate key | They are not falsely marked as duplicates |
| VAL-17 | Confidence below configured threshold | Low-confidence warning; extracted value is not silently changed |
| VAL-18 | Multiple validation rules fail on one record | All applicable errors are returned together |

## C. Mallikarjun – PDF text extraction and scanned-image OCR

The repository branch currently needs a confirmed public extractor function/interface before
these can be executable unit tests. The cases below are the acceptance criteria to implement
against the final PDF/OCR API.

| ID | Input fixture | Expected result |
|---|---|---|
| OCR-01 | Searchable, one-page PDF containing invoice fields | Text is extracted and key values are available |
| OCR-02 | Searchable, multi-page PDF | Text from every page is captured in page order |
| OCR-03 | Scanned PDF (image-only pages) | OCR is invoked and readable text is returned |
| OCR-04 | PNG/JPG scan of an invoice | OCR extracts visible text |
| OCR-05 | Rotated scan (90°/180°) | Orientation is corrected or a clear low-quality warning is returned |
| OCR-06 | Low-resolution / blurred scan | No fabricated values; low-confidence or review warning is produced |
| OCR-07 | Blank PDF page or blank image | Empty text is returned safely; no crash |
| OCR-08 | Corrupt PDF/image bytes | A controlled, descriptive extraction error is raised |
| OCR-09 | Unsupported file extension | Unsupported-format error is raised |
| OCR-10 | PDF with mixed searchable and scanned pages | Text extraction and OCR are both applied as needed |
| OCR-11 | Large multi-page PDF within upload limits | Processing completes or reports a controlled limit error |
| OCR-12 | Invoice number and amount appear on different pages | Extracted content preserves page association and does not merge unrelated fields |
| OCR-13 | Same scan processed twice | Deterministic output for the same OCR engine/configuration |
| OCR-14 | OCR returns uncertain characters (O/0, I/1) | Uncertainty is flagged for review rather than silently guessed |

### Suggested Mallikarjun sample fixtures

Create anonymised fixtures under `tests/samples/pdf_ocr/`:
- `searchable_invoice_one_page.pdf`
- `searchable_invoice_two_pages.pdf`
- `scanned_invoice.pdf`
- `invoice_scan.png`
- `rotated_invoice.png`
- `blurred_invoice.png`
- `blank_page.pdf`
- `corrupt.pdf` (small invalid byte fixture)

For every fixture, maintain a small expected-output JSON containing expected page count,
must-find text snippets, and expected warning/error behaviour. Avoid asserting exact OCR
spacing; OCR engines can differ in whitespace. Assert key fields and confidence thresholds
where the implementation exposes them.

## Run

```bash
pip install pytest pandas openpyxl
pytest -q tests/test_tabular_extraction.py tests/test_field_validation.py
```

Run the OCR cases after Mallikarjun confirms the extractor import path and function signature.
