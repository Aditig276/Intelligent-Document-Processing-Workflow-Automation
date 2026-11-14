
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.report_generators.excel_generator import generate_excel_report


@pytest.fixture
def sample_reviewed_data():
    return {
        "document_name": "invoice_001.pdf",
        "invoice_number": "INV-1001",
        "document_date": "2026-11-12",
        "customer_name": "ABC Technologies",
        "total_amount": "15000.50",
    }


def test_generate_excel_report(sample_reviewed_data):
    report = generate_excel_report(sample_reviewed_data)

    assert isinstance(report, BytesIO)

    workbook = load_workbook(report)

    assert workbook.sheetnames == [
        "Invoice Details",
        "Processing Summary",
        "Extraction Details",
    ]


def test_invoice_details(sample_reviewed_data):
    report = generate_excel_report(sample_reviewed_data)
    workbook = load_workbook(report)

    sheet = workbook["Invoice Details"]

    assert sheet["A4"].value == "Document Name"
    assert sheet["A5"].value == "invoice_001.pdf"
    assert sheet["B5"].value == "INV-1001"
    assert sheet["D5"].value == "ABC Technologies"
    assert sheet["E5"].value == 15000.50


def test_processing_summary(sample_reviewed_data):
    report = generate_excel_report(
        sample_reviewed_data,
        job_id=123,
        processing_status="Completed",
    )

    workbook = load_workbook(report)
    sheet = workbook["Processing Summary"]

    assert sheet["B3"].value == 123
    assert sheet["B5"].value == "Completed"


def test_missing_fields_are_reported(sample_reviewed_data):
    sample_reviewed_data["customer_name"] = ""

    report = generate_excel_report(sample_reviewed_data)
    workbook = load_workbook(report)

    sheet = workbook["Processing Summary"]

    assert sheet["B10"].value == 1

    details = workbook["Extraction Details"]
    assert details["C7"].value == "Missing"
    assert details["D7"].value == "Pending"


def test_empty_data_raises_error():
    with pytest.raises(ValueError):
        generate_excel_report({})


def test_invalid_amount_raises_error(sample_reviewed_data):
    sample_reviewed_data["total_amount"] = "invalid"

    with pytest.raises(ValueError, match="Invalid total amount"):
        generate_excel_report(sample_reviewed_data)
