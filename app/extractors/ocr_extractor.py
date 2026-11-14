
from pathlib import Path
import shutil

import pymupdf
import pytesseract
from PIL import Image, UnidentifiedImageError

windows_tesseract = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
tesseract_path = shutil.which("tesseract")

if windows_tesseract.is_file():
    pytesseract.pytesseract.tesseract_cmd = str(windows_tesseract)
elif tesseract_path:
    pytesseract.pytesseract.tesseract_cmd = tesseract_path
