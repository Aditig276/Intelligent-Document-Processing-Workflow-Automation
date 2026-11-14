import csv
import io
import os
import tempfile
from pathlib import Path

import pandas as pd

from app.extractors.extraction_service import extract_document_text



def extract_document(file_data, file_name):
    extension = Path(file_name).suffix.lower()

    if extension == ".csv":
        return extract_csv(file_data)

    if extension == ".pdf":
        return extract_pdf(file_data)

    if extension in [".xlsx", ".xls"]:
        return extract_excel(file_data)

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
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            suffix=".pdf",
            delete=False
        ) as temp_file:
            temp_file.write(file_data)
            temp_path = temp_file.name

        result = extract_document_text(temp_path)

        pages = [
            {
                "page": page["page_number"],
                "text": page["text"]
            }
            for page in result["pages"]
        ]

        return {
            "file_type": "pdf",
            "page_count": result["total_pages"],
            "text": result["full_text"],
            "pages": pages,
        }

    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def extract_excel(file_data, extension=None):
    excel_file = pd.ExcelFile(io.BytesIO(file_data))

    result = {}

    for sheet_name in excel_file.sheet_names:
        dataframe = pd.read_excel(
            excel_file,
            sheet_name=sheet_name,
            header=None
        )

        # Remove completely empty rows and columns.
        dataframe = dataframe.dropna(
            axis=0,
            how="all"
        )

        dataframe = dataframe.dropna(
            axis=1,
            how="all"
        )

        if dataframe.empty:
            result[sheet_name] = {
                "columns": [],
                "row_count": 0,
                "data": [],
            }
            continue

        # Detect the first row containing actual column headings.
        header_index = None

        for index, row in dataframe.iterrows():
            non_empty_values = row.dropna()

            if len(non_empty_values) >= 2:
                header_index = index
                break

        if header_index is None:
            raise ValueError(
                f"No valid header row found in sheet: {sheet_name}"
            )

        # Set the detected row as the column headings.
        headers = dataframe.loc[header_index].tolist()

        cleaned_headers = []

        for index, header in enumerate(headers):
            if pd.isna(header):
                cleaned_headers.append(f"Column_{index + 1}")
            else:
                cleaned_headers.append(str(header).strip())

        dataframe = dataframe.loc[header_index + 1:].copy()

        dataframe.columns = cleaned_headers

        # Remove completely empty data rows.
        dataframe = dataframe.dropna(
            axis=0,
            how="all"
        )

        # Replace missing values with None.
        dataframe = dataframe.astype(object).where(
            pd.notna(dataframe),
            None
        )

        result[sheet_name] = {
            "columns": cleaned_headers,
            "row_count": len(dataframe),
            "data": dataframe.to_dict(orient="records"),
        }

    return {
        "file_type": "excel",
        "sheet_count": len(result),
        "sheets": result,
    }
