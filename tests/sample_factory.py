"""Builds small, anonymised sample files in memory for the tests.

All names, invoice numbers and amounts are fake. Nothing here is a real document.
"""
import csv
import io
import zipfile

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MiB, same limit as documents/views.py

INVOICE_ROWS = [
    ["name", "date", "invoice_number", "amount"],
    ["Acme Test Pvt Ltd", "2026-01-15", "INV-0001", "1500.50"],
    ["Sample Traders", "2026-02-01", "INV-0002", "320.00"],
]


def csv_bytes(rows=None, encoding="utf-8"):
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows or INVOICE_ROWS)
    return buf.getvalue().encode(encoding)


def pdf_bytes(text="Invoice INV-0001 Total 1500.50", pages=1):
    try:
        try:
            import pymupdf as fitz
        except ImportError:  # older PyMuPDF
            import fitz
    except ImportError:  # fallback so samples can be built without PyMuPDF
        from reportlab.pdfgen import canvas

        buf = io.BytesIO()
        c = canvas.Canvas(buf)
        for n in range(pages):
            c.drawString(72, 750, f"{text} (page {n + 1})")
            c.showPage()
        c.save()
        return buf.getvalue()
    doc = fitz.open()
    for n in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"{text} (page {n + 1})")
    data = doc.tobytes()
    doc.close()
    return data


def _image_bytes(fmt, size=(40, 30)):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, (200, 220, 240)).save(buf, format=fmt)
    return buf.getvalue()


def png_bytes():
    return _image_bytes("PNG")


def jpeg_bytes():
    return _image_bytes("JPEG")


def tiff_bytes():
    return _image_bytes("TIFF")


def xlsx_bytes(sheets=None):
    import openpyxl

    sheets = sheets or {"Invoices": INVOICE_ROWS}
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def xls_bytes():
    """Returns None when xlwt is not installed (callers should skip)."""
    try:
        import xlwt
    except ImportError:
        return None
    wb = xlwt.Workbook()
    ws = wb.add_sheet("Invoices")
    for r, row in enumerate(INVOICE_ROWS):
        for c, value in enumerate(row):
            ws.write(r, c, value)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def zip_not_excel_bytes():
    """A valid ZIP archive that is NOT an Excel workbook."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "not a workbook")
    return buf.getvalue()


def valid_samples():
    """filename -> bytes for every supported type (xls only if xlwt exists)."""
    samples = {
        "invoice.pdf": pdf_bytes(),
        "invoice.csv": csv_bytes(),
        "invoice.xlsx": xlsx_bytes(),
        "scan.png": png_bytes(),
        "scan.jpg": jpeg_bytes(),
        "scan.jpeg": jpeg_bytes(),
        "scan.tif": tiff_bytes(),
        "scan.tiff": tiff_bytes(),
    }
    xls = xls_bytes()
    if xls is not None:
        samples["invoice.xls"] = xls
    return samples


def exact_size_csv(size):
    """A text file of exactly `size` bytes that is still valid CSV/UTF-8."""
    return b"a" * size
