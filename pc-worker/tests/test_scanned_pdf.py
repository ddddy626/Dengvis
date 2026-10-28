"""A page with image-only text must be searchable locally through OCR."""

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader
import pytest

from worker.search import search_library


def scanned_pdf() -> bytes:
    font = None
    for candidate in ("C:/Windows/Fonts/arial.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                      "/System/Library/Fonts/Supplemental/Arial.ttf"):
        try:
            font = ImageFont.truetype(candidate, 64)
            break
        except OSError:
            continue
    if font is None:
        pytest.skip("A local test font is required for the scanned PDF fixture")
    image = Image.new("RGB", (1200, 220), "white")
    ImageDraw.Draw(image).text(
        (35, 65), "VECTOR SEARCH NOTES", fill="black",
        font=font,
    )
    target = BytesIO()
    image.save(target, format="JPEG", quality=90)
    jpeg = target.getvalue()
    content = b"q 540 0 0 110 36 620 cm /Im0 Do Q"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /XObject /Subtype /Image /Width 1200 /Height 220 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length %d >>\nstream\n" % len(jpeg) + jpeg + b"\nendstream",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, item in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + item + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return bytes(data)


def test_scanned_pdf_uses_local_ocr(tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(scanned_pdf())
    assert not (PdfReader(str(path)).pages[0].extract_text() or "").strip()
    result = search_library(tmp_path, "vector search")
    assert result["success"]
    assert result["modelName"].endswith("+rapidocr")
    assert result["excerpts"][0]["source"] == "scan.pdf"
    assert result["excerpts"][0]["page"] == 1
    assert "VECTOR" in result["excerpts"][0]["text"].upper()
