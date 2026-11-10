"""Regression tests for the CSV/Excel extractor contributed by the tabular team.

These tests are intended to run after feature/csv-excel-extraction is merged
into the test branch. They use temporary files and never modify real uploads.
"""
import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("openpyxl")
extractor = pytest.importorskip("app.extractors.tabular_extractor")
extract_tabular_data = extractor.extract_tabular_data


def test_csv_extracts_rows_and_metadata(tmp_path):
    path = tmp_path / "invoices.csv"
    path.write_text(
        " invoice_number , amount , customer_name\n"
        "INV-001,1250.50,Acme Test\n"
        "INV-002,900.00,Sample Traders\n",
        encoding="utf-8",
    )

    result = extract_tabular_data(path, required_columns=["invoice_number", "amount"])

    assert result["file_name"] == "invoices.csv"
    assert result["file_type"] == "csv"
    assert result["sheet_name"] is None
    assert result["columns"] == ["invoice_number", "amount", "customer_name"]
    assert result["row_count"] == 2
    assert result["rows"][0]["invoice_number"] == "INV-001"
    assert result["missing_columns"] == []


def test_csv_removes_completely_empty_rows(tmp_path):
    path = tmp_path / "with_blanks.csv"
    path.write_text(
        "invoice_number,amount\nINV-001,100\n,\nINV-002,200\n",
        encoding="utf-8",
    )

    result = extract_tabular_data(path)

    assert result["row_count"] == 2
    assert result["empty_rows_removed"] == 1


def test_csv_reports_missing_required_columns(tmp_path):
    path = tmp_path / "missing_column.csv"
    path.write_text("invoice_number,amount\nINV-001,100\n", encoding="utf-8")

    result = extract_tabular_data(
        path, required_columns=["invoice_number", "vendor", "amount"]
    )

    assert result["missing_columns"] == ["vendor"]


def test_csv_converts_missing_cells_to_none(tmp_path):
    path = tmp_path / "nulls.csv"
    path.write_text(
        "invoice_number,amount\nINV-001,\nINV-002,250\n",
        encoding="utf-8",
    )

    result = extract_tabular_data(path)

    assert result["rows"][0]["amount"] is None
    assert result["rows"][1]["amount"] == 250


def test_xlsx_extracts_first_sheet_and_sheet_name(tmp_path):
    path = tmp_path / "invoices.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(
            {"invoice_number": ["INV-101", "INV-102"], "amount": [500, 750]}
        ).to_excel(writer, sheet_name="Invoices", index=False)
        pd.DataFrame({"note": ["not the first sheet"]}).to_excel(
            writer, sheet_name="Notes", index=False
        )

    result = extract_tabular_data(path)

    assert result["file_type"] == "xlsx"
    assert result["sheet_name"] == "Invoices"
    assert result["row_count"] == 2
    assert result["rows"][1]["invoice_number"] == "INV-102"


def test_xlsx_removes_empty_rows_and_preserves_valid_rows(tmp_path):
    path = tmp_path / "blank_rows.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(
            {"invoice_number": ["INV-201", None, "INV-202"], "amount": [100, None, 300]}
        ).to_excel(writer, sheet_name="Data", index=False)

    result = extract_tabular_data(path)

    assert result["row_count"] == 2
    assert result["empty_rows_removed"] == 1


def test_missing_file_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        extract_tabular_data("does-not-exist.csv")


def test_unsupported_extension_raises_value_error(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("not a spreadsheet", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported file format"):
        extract_tabular_data(path)


def test_empty_csv_is_reported_as_extraction_error(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="Unable to extract tabular data"):
        extract_tabular_data(path)
