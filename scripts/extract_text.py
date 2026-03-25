"""
extract_text.py - 多格式文字抽取腳本
支援：.docx, .pdf, .xlsx/.xls, .jpg/.jpeg/.png
輸出 JSON：{text, metadata, ocr_used, page_count}
"""
import hashlib
import json
import os
import sys

# Force UTF-8 output on Windows to avoid cp950 mojibake
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


def calc_hash(file_path: str) -> str:
    """計算檔案 SHA-256 hex 字串"""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_word(path: str) -> tuple[str, int]:
    """從 .docx 抽取段落與表格文字，回傳 (text, page_count)"""
    from docx import Document
    doc = Document(path)
    parts = []
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text)
    for table in doc.tables:
        for row in table.rows:
            row_text = "\t".join(cell.text.strip() for cell in row.cells)
            if row_text.strip():
                parts.append(row_text)
    return "\n".join(parts), len(doc.sections) or 1


def extract_pdf_ocr(path: str) -> tuple[str, int]:
    """將 PDF 各頁轉圖片後 OCR（需 Poppler + Tesseract）"""
    import pytesseract
    from pdf2image import convert_from_path
    images = convert_from_path(path)
    texts = []
    for img in images:
        texts.append(pytesseract.image_to_string(img, lang="chi_tra+eng"))
    return "\n".join(texts), len(images)


def extract_pdf(path: str) -> tuple[str, bool, int]:
    """從 PDF 抽取文字；若為空則改用 OCR。回傳 (text, ocr_used, page_count)"""
    from pypdf import PdfReader
    reader = PdfReader(path)
    page_count = len(reader.pages)
    parts = []
    for page in reader.pages:
        t = page.extract_text()
        if t:
            parts.append(t)
    text = "\n".join(parts).strip()
    if not text:
        ocr_text, ocr_pages = extract_pdf_ocr(path)
        return ocr_text, True, max(page_count, ocr_pages)
    return text, False, page_count


def extract_excel(path: str) -> tuple[str, int]:
    """從 .xlsx/.xls 讀取所有 sheet 文字，保留 sheet_name 前綴"""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    parts = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        sheet_parts = [f"[Sheet: {sheet_name}]"]
        for row in ws.iter_rows(values_only=True):
            row_text = "\t".join(str(cell) if cell is not None else "" for cell in row)
            if row_text.strip():
                sheet_parts.append(row_text)
        parts.append("\n".join(sheet_parts))
    wb.close()
    return "\n\n".join(parts), len(wb.sheetnames)


def extract_image(path: str) -> tuple[str, int]:
    """對圖片執行 OCR（需 Tesseract）"""
    import pytesseract
    from PIL import Image
    img = Image.open(path)
    text = pytesseract.image_to_string(img, lang="chi_tra+eng")
    return text, 1


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: python extract_text.py <file_path>"}, ensure_ascii=False))
        sys.exit(1)

    file_path = os.path.abspath(sys.argv[1])
    if not os.path.isfile(file_path):
        print(json.dumps({"error": f"File not found: {file_path}"}, ensure_ascii=False))
        sys.exit(1)

    file_name = os.path.basename(file_path)
    file_ext = os.path.splitext(file_name)[1].lower()
    file_size = os.path.getsize(file_path)
    hash_sha256 = calc_hash(file_path)

    text = ""
    ocr_used = False
    page_count = 1

    try:
        if file_ext == ".docx":
            text, page_count = extract_word(file_path)
        elif file_ext == ".pdf":
            text, ocr_used, page_count = extract_pdf(file_path)
        elif file_ext in (".xlsx", ".xls"):
            text, page_count = extract_excel(file_path)
        elif file_ext in (".jpg", ".jpeg", ".png"):
            text, page_count = extract_image(file_path)
            ocr_used = True
        else:
            print(json.dumps({"error": f"Unsupported file type: {file_ext}"}, ensure_ascii=False))
            sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)

    result = {
        "text": text,
        "metadata": {
            "file_name": file_name,
            "file_ext": file_ext,
            "file_path": file_path,
            "file_size": file_size,
            "hash_sha256": hash_sha256,
        },
        "ocr_used": ocr_used,
        "page_count": page_count,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
