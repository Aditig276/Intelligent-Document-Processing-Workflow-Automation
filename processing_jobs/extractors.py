
from io import BytesIO
from pathlib import Path

import fitz
import pandas as pd


def extract_pdf(file_bytes):
    """Extract selectable text from each page of a PDF."""
    pages = []

    with fitz.open(stream=file_bytes, filetype="pdf") as document:
        for page_number, page in enumerate(document, start=1):
            pages.append({
                "page": page_number,
                "text": page.get_text("text"),
            })

    return {
        "file_type": "pdf",
        "page_count": len(pages),
        "pages": pages,
        "text": "\n".join(page["text"] for page in pages),
    }


def extract_csv(file_bytes):
    """Extract CSV rows and columns."""
    dataframe = pd.read_csv(BytesIO(file_bytes))

    dataframe = dataframe.astype(object).where(
        pd.notna(dataframe), None
    )

    return {
        "file_type": "csv",
        "columns": [str(column) for column in dataframe.columns],
        "row_count": len(dataframe),
        "data": dataframe.to_dict(orient="records"),
    }


def extract_excel(file_bytes, extension):
    """Extract data from every worksheet in an Excel file."""
    engine = "openpyxl" if extension == ".xlsx" else "xlrd"

    sheets = {}

    with pd.ExcelFile(BytesIO(file_bytes), engine=engine) as workbook:
        for sheet_name in workbook.sheet_names:
            dataframe = workbook.parse(sheet_name=sheet_name)

            dataframe = dataframe.astype(object).where(
                pd.notna(dataframe), None
            )

            sheets[sheet_name] = {
                "columns": [str(column) for column in dataframe.columns],
                "row_count": len(dataframe),
                "data": dataframe.to_dict(orient="records"),
            }

    return {
        "file_type": "excel",
        "sheet_count": len(sheets),
        "sheets": sheets,
    }


def extract_document(file_bytes, file_name):
    """Choose the correct extraction function by file extension."""
    extension = Path(file_name).suffix.lower()

    if extension == ".pdf":
        return extract_pdf(file_bytes)

    if extension == ".csv":
        return extract_csv(file_bytes)

    if extension in {".xls", ".xlsx"}:
        return extract_excel(file_bytes, extension)

    raise ValueError(f"Unsupported file type: {extension or 'unknown'}")
