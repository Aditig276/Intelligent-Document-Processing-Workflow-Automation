
from pathlib import Path

import pandas as pd


SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls"}


def extract_tabular_data(file_path, required_columns=None):
    """
    Read CSV or Excel files and convert their contents
    into a JSON-compatible Python dictionary.

    Args:
        file_path: Path to the uploaded CSV or Excel file.
        required_columns: Optional list of columns that must exist.

    Returns:
        Dictionary containing extracted rows and metadata.
    """

    file_path = Path(file_path)
    extension = file_path.suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file format: {extension}")

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    try:
        # Read CSV files
        if extension == ".csv":
            dataframe = pd.read_csv(file_path)

            sheet_name = None

        # Read Excel files
        else:
            engine = "openpyxl" if extension == ".xlsx" else "xlrd"

            with pd.ExcelFile(file_path, engine=engine) as excel_file:
                sheet_name = excel_file.sheet_names[0]

                dataframe = pd.read_excel(
                    excel_file,
                    sheet_name=sheet_name,
                )
        # Remove extra spaces from column names
        dataframe.columns = [
            str(column).strip() for column in dataframe.columns
        ]

        # Identify completely empty rows
        empty_rows_removed = int(dataframe.isna().all(axis=1).sum())

        # Remove completely empty rows
        dataframe = dataframe.dropna(how="all")

        # Identify missing required columns
        missing_columns = []

        if required_columns:
            missing_columns = [
                column
                for column in required_columns
                if column not in dataframe.columns
            ]

        # Convert missing values to None for JSON compatibility
        dataframe = dataframe.astype(object).where(
            pd.notna(dataframe), None
        )

        # Convert table data into dictionaries
        rows = dataframe.to_dict(orient="records")

        return {
            "file_name": file_path.name,
            "file_type": extension.lstrip("."),
            "sheet_name": sheet_name,
            "columns": list(dataframe.columns),
            "row_count": len(rows),
            "rows": rows,
            "empty_rows_removed": empty_rows_removed,
            "missing_columns": missing_columns,
        }

    except (ValueError, FileNotFoundError):
        raise

    except Exception as error:
        raise ValueError(
            f"Unable to extract tabular data: {error}"
        ) from error
