
from datetime import datetime
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


MAX_CELL_LENGTH = 30000

FIELD_LABELS = {
    "document_name": "Document Name",
    "invoice_number": "Invoice Number",
    "document_date": "Document Date",
    "customer_name": "Customer Name",
    "total_amount": "Total Amount",
}


def safe_excel_text(value):
    """Convert values to safe Excel text and prevent formula execution."""
    if value is None:
        return ""

    text = str(value)

    # Explicitly store text as text, never as an Excel formula.
    return text


def write_text_chunks(sheet, text, start_row, label, page_number=None):
    """Write long extracted text without exceeding Excel cell limits."""

    text = str(text or "")
    chunks = [
        text[i:i + MAX_CELL_LENGTH]
        for i in range(0, len(text), MAX_CELL_LENGTH)
    ]

    if not chunks:
        chunks = [""]

    for index, chunk in enumerate(chunks, start=1):
        row = start_row

        sheet.cell(row=row, column=1, value=label).data_type = "s"

        if page_number is not None:
            sheet.cell(row=row, column=2, value=page_number)

        value_column = 3 if page_number is not None else 2

        cell = sheet.cell(
            row=row,
            column=value_column,
            value=safe_excel_text(chunk),
        )
        cell.data_type = "s"
        cell.alignment = Alignment(
            vertical="top",
            wrap_text=True,
        )

        if len(chunks) > 1:
            sheet.cell(
                row=row,
                column=value_column + 1,
                value=f"Part {index}/{len(chunks)}",
            )

        sheet.row_dimensions[row].height = 60

        start_row += 1

    return start_row


def generate_document_excel_report(
    extracted_data,
    job_id=None,
    original_file_name=None,
    processing_status="Completed",
    created_at=None,
    reviewed_data=None,
    generated_at=None,
):
    """
    Generate a general-purpose Excel report for processed documents.

    Supports ordinary documents, scanned PDFs and OCR extraction results.
    """

    if not isinstance(extracted_data, dict):
        raise ValueError("Extracted data must be a dictionary.")

    extracted_text = extracted_data.get("text", "")

    if not isinstance(extracted_text, str):
        extracted_text = str(extracted_text or "")

    pages = extracted_data.get("pages", [])

    if not isinstance(pages, list):
        pages = []

    if not extracted_text.strip() and not pages:
        raise ValueError("No extracted document content available.")

    if not isinstance(reviewed_data, dict):
        reviewed_data = {}

    generated_at = generated_at or datetime.now()
    created_at = created_at or "Not available"

    workbook = Workbook()

    # Common formatting
    title_fill = PatternFill("solid", fgColor="1F4E78")
    header_fill = PatternFill("solid", fgColor="4472C4")

    title_font = Font(
        size=15,
        bold=True,
        color="FFFFFF",
    )

    header_font = Font(
        bold=True,
        color="FFFFFF",
    )

    thin_border = Border(
        bottom=Side(
            style="thin",
            color="D9E2F3",
        )
    )

    # ------------------------------------------------
    # SHEET 1: DOCUMENT SUMMARY
    # ------------------------------------------------
    summary = workbook.active
    summary.title = "Document Summary"

    summary.merge_cells("A1:B1")
    summary["A1"] = "DOCUMENT PROCESSING REPORT"
    summary["A1"].font = title_font
    summary["A1"].fill = title_fill
    summary["A1"].alignment = Alignment(horizontal="center")
    summary.row_dimensions[1].height = 30

    metadata = [
        ("Processing Job ID", job_id or "Not available"),
        ("Original File Name", original_file_name or "Not available"),
        ("File Type", extracted_data.get("file_type", "Not available")),
        (
            "Page Count",
            extracted_data.get("page_count", len(pages) or "Not available"),
        ),
        ("Processing Status", processing_status),
        ("Processing Started", created_at),
        (
            "Report Generated",
            generated_at.strftime("%d-%m-%Y %H:%M:%S"),
        ),
        ("Total Extracted Characters", len(extracted_text)),
        ("Total Extracted Pages", len(pages)),
    ]

    for row, (label, value) in enumerate(metadata, start=3):
        summary.cell(row=row, column=1, value=label)
        summary.cell(row=row, column=2, value=safe_excel_text(value))

        summary.cell(row=row, column=1).font = Font(bold=True)

        for col in range(1, 3):
            summary.cell(row=row, column=col).border = thin_border
            summary.cell(row=row, column=col).alignment = Alignment(
                vertical="center",
                wrap_text=True,
            )

    summary.column_dimensions["A"].width = 30
    summary.column_dimensions["B"].width = 55

    # ------------------------------------------------
    # SHEET 2: EXTRACTED TEXT
    # ------------------------------------------------
    text_sheet = workbook.create_sheet("Extracted Text")

    text_sheet.merge_cells("A1:B1")
    text_sheet["A1"] = "COMPLETE EXTRACTED DOCUMENT TEXT"
    text_sheet["A1"].font = title_font
    text_sheet["A1"].fill = title_fill
    text_sheet["A1"].alignment = Alignment(horizontal="center")

    text_sheet["A3"] = "Original File"
    text_sheet["B3"] = safe_excel_text(original_file_name)
    text_sheet["A3"].font = Font(bold=True)

    text_sheet["A5"] = "Extracted Content"
    text_sheet["A5"].font = header_font
    text_sheet["A5"].fill = header_fill

    text_sheet["B5"] = "Text"
    text_sheet["B5"].font = header_font
    text_sheet["B5"].fill = header_fill

    write_text_chunks(
        text_sheet,
        extracted_text,
        start_row=6,
        label="Document Text",
    )

    text_sheet.column_dimensions["A"].width = 25
    text_sheet.column_dimensions["B"].width = 110
    text_sheet.freeze_panes = "A6"

    # ------------------------------------------------
    # SHEET 3: PAGE-WISE DETAILS
    # ------------------------------------------------
    page_sheet = workbook.create_sheet("Page-wise Details")

    page_sheet.merge_cells("A1:D1")
    page_sheet["A1"] = "PAGE-WISE EXTRACTION DETAILS"
    page_sheet["A1"].font = title_font
    page_sheet["A1"].fill = title_fill
    page_sheet["A1"].alignment = Alignment(horizontal="center")

    headers = [
        "Page",
        "Content Type",
        "Extracted Text",
        "Part",
    ]

    for col, header in enumerate(headers, start=1):
        cell = page_sheet.cell(row=3, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    current_row = 4

    for page in pages:
        if not isinstance(page, dict):
            continue

        page_number = page.get("page", "Unknown")
        page_text = str(page.get("text", "") or "")

        current_row = write_text_chunks(
            page_sheet,
            page_text,
            start_row=current_row,
            label="Extracted Text",
            page_number=page_number,
        )

    if not pages:
        page_sheet.cell(
            row=4,
            column=1,
            value="No page-wise data available",
        )

    for col, width in enumerate([12, 22, 100, 18], start=1):
        page_sheet.column_dimensions[get_column_letter(col)].width = width

    page_sheet.freeze_panes = "A4"
    page_sheet.auto_filter.ref = (
        f"A3:D{max(3, current_row - 1)}"
    )

    # ------------------------------------------------
    # SHEET 4: REVIEWED FIELDS
    # ------------------------------------------------
    reviewed_sheet = workbook.create_sheet("Reviewed Fields")

    reviewed_sheet.merge_cells("A1:C1")
    reviewed_sheet["A1"] = "REVIEWED DOCUMENT FIELDS"
    reviewed_sheet["A1"].font = title_font
    reviewed_sheet["A1"].fill = title_fill
    reviewed_sheet["A1"].alignment = Alignment(horizontal="center")

    review_headers = [
        "Field Name",
        "Reviewed Value",
        "Review Status",
    ]

    for col, header in enumerate(review_headers, start=1):
        cell = reviewed_sheet.cell(row=3, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill

    fields = reviewed_data or {}

    for row, (field, value) in enumerate(fields.items(), start=4):
        label = FIELD_LABELS.get(
            field,
            field.replace("_", " ").title(),
        )

        reviewed_sheet.cell(row=row, column=1, value=label)

        value_cell = reviewed_sheet.cell(
            row=row,
            column=2,
            value=safe_excel_text(value),
        )
        value_cell.data_type = "s"

        reviewed_sheet.cell(
            row=row,
            column=3,
            value="Available" if str(value or "").strip() else "Missing",
        )

        for col in range(1, 4):
            reviewed_sheet.cell(row=row, column=col).border = thin_border
            reviewed_sheet.cell(row=row, column=col).alignment = Alignment(
                vertical="top",
                wrap_text=True,
            )

    if not fields:
        reviewed_sheet.cell(
            row=4,
            column=1,
            value="No reviewed fields available",
        )

    for col, width in enumerate([30, 65, 22], start=1):
        reviewed_sheet.column_dimensions[get_column_letter(col)].width = width

    reviewed_sheet.freeze_panes = "A4"

    # ------------------------------------------------
    # GENERATE WORKBOOK IN MEMORY
    # ------------------------------------------------
    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    return output
