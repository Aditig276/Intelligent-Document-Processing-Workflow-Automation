
from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)


def generate_pdf_report(
    extracted_data,
    job_id=None,
    original_file_name=None,
    processing_status="Completed",
    created_at=None,
    reviewed_data=None,
    generated_at=None,
):
    """
    Generate a general-purpose PDF report for document processing.

    Supports ordinary text documents, scanned PDFs and OCR results.
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

    generated_at = generated_at or datetime.now()
    created_at = created_at or "Not available"
    reviewed_data = reviewed_data or {}

    if not isinstance(reviewed_data, dict):
        reviewed_data = {}

    output = BytesIO()

    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title="Document Processing Report",
        author="Intelligent Document Processing System",
    )

    styles = getSampleStyleSheet()

    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            parent=styles["Title"],
            fontSize=18,
            leading=24,
            textColor=colors.HexColor("#1F4E78"),
            alignment=TA_CENTER,
            spaceAfter=12,
        )
    )

    styles.add(
        ParagraphStyle(
            name="SectionHeading",
            parent=styles["Heading2"],
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#1F4E78"),
            spaceBefore=12,
            spaceAfter=7,
        )
    )

    styles.add(
        ParagraphStyle(
            name="DocumentText",
            parent=styles["BodyText"],
            fontSize=9,
            leading=13,
            spaceAfter=5,
            wordWrap="CJK",
        )
    )

    styles.add(
        ParagraphStyle(
            name="SmallText",
            parent=styles["BodyText"],
            fontSize=8,
            leading=11,
        )
    )

    story = []

    def safe_text(value):
        """Escape text before adding it to a ReportLab Paragraph."""
        return escape(str(value if value is not None else ""))

    def add_metadata_table(rows):
        table = Table(
            [
                [
                    Paragraph(
                        f"<b>{safe_text(label)}</b>",
                        styles["SmallText"],
                    ),
                    Paragraph(
                        safe_text(value),
                        styles["SmallText"],
                    ),
                ]
                for label, value in rows
            ],
            colWidths=[48 * mm, 115 * mm],
        )

        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1),
                     colors.HexColor("#EAF0F6")),
                    ("GRID", (0, 0), (-1, -1), 0.4,
                     colors.HexColor("#D9E2F3")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )

        story.append(table)

    # ------------------------------------------------
    # REPORT HEADER
    # ------------------------------------------------
    story.append(
        Paragraph("DOCUMENT PROCESSING REPORT", styles["ReportTitle"])
    )

    story.append(
        Paragraph(
            f"Generated on: {generated_at.strftime('%d-%m-%Y %H:%M:%S')}",
            styles["SmallText"],
        )
    )

    story.append(Spacer(1, 10))

    # ------------------------------------------------
    # DOCUMENT SUMMARY
    # ------------------------------------------------
    story.append(
        Paragraph("1. Document Summary", styles["SectionHeading"])
    )

    metadata = [
        ("Processing Job ID", job_id or "Not available"),
        ("Original File Name", original_file_name or "Not available"),
        ("File Type", extracted_data.get("file_type", "Not available")),
        ("Page Count", extracted_data.get(
            "page_count", len(pages) or "Not available"
        )),
        ("Processing Status", processing_status),
        ("Processing Started", created_at),
        ("Report Generated", generated_at.strftime(
            "%d-%m-%Y %H:%M:%S"
        )),
    ]

    add_metadata_table(metadata)

    # ------------------------------------------------
    # REVIEWED FIELDS
    # ------------------------------------------------
    if reviewed_data:
        story.append(
            Paragraph("2. Reviewed Document Fields", styles["SectionHeading"])
        )

        reviewed_rows = [
            [
                Paragraph("<b>Field</b>", styles["SmallText"]),
                Paragraph("<b>Reviewed Value</b>", styles["SmallText"]),
            ]
        ]

        for field, value in reviewed_data.items():
            reviewed_rows.append(
                [
                    Paragraph(safe_text(field.replace("_", " ").title()),
                              styles["SmallText"]),
                    Paragraph(safe_text(value), styles["SmallText"]),
                ]
            )

        reviewed_table = Table(
            reviewed_rows,
            colWidths=[55 * mm, 108 * mm],
            repeatRows=1,
        )

        reviewed_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0),
                     colors.HexColor("#4472C4")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.4,
                     colors.HexColor("#D9E2F3")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )

        story.append(reviewed_table)

    # ------------------------------------------------
    # EXTRACTED DOCUMENT CONTENT
    # ------------------------------------------------
    if extracted_text.strip():
        story.append(
            Paragraph("3. Extracted Document Text", styles["SectionHeading"])
        )

        for line in extracted_text.splitlines():
            if line.strip():
                story.append(
                    Paragraph(safe_text(line), styles["DocumentText"])
                )
            else:
                story.append(Spacer(1, 4))

    # ------------------------------------------------
    # PAGE-WISE EXTRACTION
    # ------------------------------------------------
    if pages:
        story.append(PageBreak())

        story.append(
            Paragraph("4. Page-wise Extraction Details",
                      styles["SectionHeading"])
        )

        for page in pages:
            if not isinstance(page, dict):
                continue

            page_number = page.get("page", "Unknown")
            page_text = page.get("text", "")

            story.append(
                Paragraph(
                    f"Page {safe_text(page_number)}",
                    styles["Heading3"],
                )
            )

            if page_text:
                for line in str(page_text).splitlines():
                    if line.strip():
                        story.append(
                            Paragraph(
                                safe_text(line),
                                styles["DocumentText"],
                            )
                        )
            else:
                story.append(
                    Paragraph(
                        "No text extracted from this page.",
                        styles["SmallText"],
                    )
                )

            story.append(Spacer(1, 8))

    # ------------------------------------------------
    # GENERATE PDF
    # ------------------------------------------------
    document.build(story)

    output.seek(0)

    return output
