
import pandas as pd
import pytest

from app.extractors.tabular_extractor import extract_tabular_data


def test_csv_extraction_and_empty_rows(tmp_path):
    file_path = tmp_path / "sample.csv"

    file_path.write_text(
        "invoice_number,amount,date\n"
        "INV001,1000,2026-11-01\n"
        ",,\n"
        "INV002,2500,2026-11-02\n",
        encoding="utf-8",
    )

    result = extract_tabular_data(
        file_path,
        required_columns=["invoice_number", "amount", "customer_name"],
    )

    assert result["row_count"] == 2
    assert result["empty_rows_removed"] == 1
    assert result["missing_columns"] == ["customer_name"]
    assert result["rows"][0]["invoice_number"] == "INV001"


def test_xlsx_extraction_and_sheet_name(tmp_path):
    file_path = tmp_path / "sample.xlsx"

    dataframe = pd.DataFrame({
        "invoice_number": ["INV101", None, "INV102"],
        "amount": [1500, None, 3000],
    })

    with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
        dataframe.to_excel(
            writer,
            sheet_name="Invoices",
            index=False,
        )

    result = extract_tabular_data(file_path)

    assert result["file_type"] == "xlsx"
    assert result["sheet_name"] == "Invoices"
    assert result["row_count"] == 2
    assert result["empty_rows_removed"] == 1


def test_missing_file():
    with pytest.raises(FileNotFoundError):
        extract_tabular_data("missing_file.csv")


def test_unsupported_file_format(tmp_path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("sample data")

    with pytest.raises(ValueError, match="Unsupported file format"):
        extract_tabular_data(file_path)


def test_xls_extraction(tmp_path):
    xlwt = pytest.importorskip("xlwt")

    file_path = tmp_path / "sample.xls"

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Invoices")

    headers = ["invoice_number", "amount"]
    for column, value in enumerate(headers):
        sheet.write(0, column, value)

    sheet.write(1, 0, "INV201")
    sheet.write(1, 1, 1800)

    sheet.write(3, 0, "INV202")
    sheet.write(3, 1, 3500)

    workbook.save(str(file_path))

    result = extract_tabular_data(file_path)

    assert result["file_type"] == "xls"
    assert result["sheet_name"] == "Invoices"
    assert result["row_count"] == 2
    assert result["empty_rows_removed"] == 1
