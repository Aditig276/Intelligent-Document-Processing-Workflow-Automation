import csv
import io
from pathlib import Path

import pymupdf
import pandas as pd


def extract_document(file_data, file_name):
    extension = Path(file_name).suffix.lower()

    if extension == ".csv":
        import tempfile
        from app.extractors.tabular_extractor import extract_tabular_data

        with tempfile.NamedTemporaryFile(
            suffix=extension,
            delete=False
        ) as temp_file:
            temp_file.write(file_data)
            temp_path = Path(temp_file.name)

        try:
            result = extract_tabular_data(temp_path)

            return {
                "file_type": "csv",
                "columns": result["columns"],
                "row_count": result["row_count"],
                "data": result["rows"],
            }
        finally:
            temp_path.unlink(missing_ok=True)

    if extension == ".pdf":
        return extract_pdf(file_data)

    if extension in [".xlsx", ".xls"]:
        return extract_excel(file_data, extension=extension)

    raise ValueError(f"Unsupported file type: {extension}")


def extract_csv(file_data):
    if isinstance(file_data, bytes):
        file_data = io.BytesIO(file_data)

    text = io.TextIOWrapper(
        file_data,
        encoding="utf-8-sig",
        newline=""
    )

    reader = csv.DictReader(text)

    if not reader.fieldnames:
        raise ValueError("Empty CSV file")

    rows = list(reader)

    cleaned_rows = []

    for row in rows:
        cleaned_rows.append({
            key: value if value != "" else None
            for key, value in row.items()
        })

    return {
        "file_type": "csv",
        "columns": reader.fieldnames,
        "row_count": len(cleaned_rows),
        "data": cleaned_rows,
    }


def extract_pdf(file_data):
    document = pymupdf.open(
        stream=file_data,
        filetype="pdf"
    )

    if document.page_count == 0:
        raise ValueError("Empty PDF file")

    pages = []

    for page_number, page in enumerate(document, start=1):
        pages.append({
            "page": page_number,
            "text": page.get_text()
        })

    return {
        "file_type": "pdf",
        "page_count": document.page_count,
        "text": "\n".join(
            page["text"] for page in pages
        ),
        "pages": pages,
    }


def extract_excel(file_data, extension=None):
    import tempfile

    from app.extractors.tabular_extractor import extract_tabular_data

    extension = extension or ".xlsx"

    with tempfile.NamedTemporaryFile(
        suffix=extension,
        delete=False
    ) as temp_file:
        temp_file.write(file_data)
        temp_path = Path(temp_file.name)

    try:
        engine = "openpyxl" if extension == ".xlsx" else "xlrd"

        with pd.ExcelFile(temp_path, engine=engine) as excel_file:
            sheet_names = excel_file.sheet_names

        result = {}

        for sheet_name in sheet_names:
            extracted = extract_tabular_data(
                temp_path,
                sheet_name=sheet_name
            )

            result[sheet_name] = {
                "columns": extracted["columns"],
                "row_count": extracted["row_count"],
                "data": extracted["rows"],
            }

        return {
            "file_type": "excel",
            "sheet_count": len(result),
            "sheets": result,
        }

    finally:
        temp_path.unlink(missing_ok=True)