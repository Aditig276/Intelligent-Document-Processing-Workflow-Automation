
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


FIELD_LABELS = {
    "document_name": "Document Name",
    "invoice_number": "Invoice Number",
    "document_date": "Document Date",
    "customer_name": "Customer Name",
    "total_amount": "Total Amount",
}


def generate_excel_report(
    reviewed_data,
    job_id=None,
    original_file_name=None,
    processing_status="Completed",
    created_at=None,
    generated_at=None,
):
    """Generate a formatted three-sheet invoice processing report."""

    if not isinstance(reviewed_data, dict):
        raise ValueError("Reviewed data must be a dictionary.")

    if not any(
        str(value).strip()
        for value in reviewed_data.values()
        if value is not None
    ):
        raise ValueError("No reviewed data available.")

    generated_at = generated_at or datetime.now()

    if created_at is None:
        created_at = "Not available"

    # Validate amount when provided.
    amount_value = reviewed_data.get("total_amount", "")

    if amount_value not in (None, ""):
        try:
            amount = Decimal(str(amount_value))
            if not amount.is_finite() or amount < 0:
                raise InvalidOperation
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError("Invalid total amount.")
    else:
        amount = None

    workbook = Workbook()

    # Common formatting
    title_fill = PatternFill("solid", fgColor="1F4E78")
    header_fill = PatternFill("solid", fgColor="4472C4")
    title_font = Font(size=16, bold=True, color="FFFFFF")
    header_font = Font(bold=True, color="FFFFFF")
    thin_border = Border(
        bottom=Side(style="thin", color="D9E2F3")
    )

    # ------------------------------------------------
    # SHEET 1: INVOICE DETAILS
    # ------------------------------------------------
    invoice = workbook.active
    invoice.title = "Invoice Details"

    invoice.merge_cells("A1:E1")
    invoice["A1"] = "INVOICE EXTRACTION REPORT"
    invoice["A1"].font = title_font
    invoice["A1"].fill = title_fill
    invoice["A1"].alignment = Alignment(horizontal="center")
    invoice.row_dimensions[1].height = 32

    invoice.merge_cells("A2:E2")
    invoice["A2"] = (
        "Generated: " + generated_at.strftime("%d-%m-%Y %H:%M:%S")
    )
    invoice["A2"].alignment = Alignment(horizontal="right")

    headers = list(FIELD_LABELS.values())

    for col, header in enumerate(headers, start=1):
        cell = invoice.cell(row=4, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    for col, field in enumerate(FIELD_LABELS, start=1):
        value = reviewed_data.get(field, "")

        if value is None:
            value = ""

        cell = invoice.cell(row=5, column=col, value=value)

        # Store text as text, preventing formula execution.
        if field != "total_amount":
            cell.data_type = "s"

        if field == "total_amount" and amount is not None:
            cell.value = float(amount)
            cell.number_format = '#,##0.00'

        cell.alignment = Alignment(horizontal="center")
        cell.border = thin_border

    for col in range(1, 6):
        invoice.column_dimensions[get_column_letter(col)].width = 25

    invoice.freeze_panes = "A5"
    invoice.auto_filter.ref = "A4:E5"

    # ------------------------------------------------
    # SHEET 2: PROCESSING SUMMARY
    # ------------------------------------------------
    summary = workbook.create_sheet("Processing Summary")

    summary.merge_cells("A1:B1")
    summary["A1"] = "PROCESSING SUMMARY"
    summary["A1"].font = title_font
    summary["A1"].fill = title_fill
    summary["A1"].alignment = Alignment(horizontal="center")

    completed_fields = [
        field for field in FIELD_LABELS
        if str(reviewed_data.get(field, "") or "").strip()
    ]

    missing_fields = [
        field for field in FIELD_LABELS
        if field not in completed_fields
    ]

    summary_data = [
        ("Processing Job ID", job_id or "Not available"),
        ("Original File Name", original_file_name or
         reviewed_data.get("document_name", "Not available")),
        ("Processing Status", processing_status),
        ("Processing Started", str(created_at)),
        ("Report Generated", generated_at.strftime(
            "%d-%m-%Y %H:%M:%S"
        )),
        ("Total Fields", len(FIELD_LABELS)),
        ("Completed Fields", len(completed_fields)),
        ("Missing Fields", len(missing_fields)),
    ]

    for row, (label, value) in enumerate(summary_data, start=3):
        summary.cell(row=row, column=1, value=label)
        summary.cell(row=row, column=2, value=value)
        summary.cell(row=row, column=1).font = Font(bold=True)

    summary.column_dimensions["A"].width = 28
    summary.column_dimensions["B"].width = 40

    # ------------------------------------------------
    # SHEET 3: EXTRACTION DETAILS
    # ------------------------------------------------
    details = workbook.create_sheet("Extraction Details")

    details.merge_cells("A1:D1")
    details["A1"] = "FIELD-LEVEL EXTRACTION DETAILS"
    details["A1"].font = title_font
    details["A1"].fill = title_fill
    details["A1"].alignment = Alignment(horizontal="center")

    detail_headers = [
        "Field Name",
        "Reviewed Value",
        "Data Status",
        "Review Status",
    ]

    for col, header in enumerate(detail_headers, start=1):
        cell = details.cell(row=3, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    for row, (field, label) in enumerate(FIELD_LABELS.items(), start=4):
        value = reviewed_data.get(field, "") or ""
        has_value = bool(str(value).strip())

        details.cell(row=row, column=1, value=label)
        details.cell(row=row, column=2, value=value)
        details.cell(
            row=row,
            column=3,
            value="Available" if has_value else "Missing",
        )
        details.cell(
            row=row,
            column=4,
            value="Reviewed" if has_value else "Pending",
        )

        # Keep reviewed text as text.
        details.cell(row=row, column=2).data_type = "s"

        for col in range(1, 5):
            details.cell(row=row, column=col).border = thin_border
            details.cell(row=row, column=col).alignment = Alignment(
                vertical="center"
            )

    for col, width in enumerate([25, 35, 20, 20], start=1):
        details.column_dimensions[get_column_letter(col)].width = width

    details.freeze_panes = "A4"
    details.auto_filter.ref = "A3:D8"

    # Save workbook in memory.
    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    return output
