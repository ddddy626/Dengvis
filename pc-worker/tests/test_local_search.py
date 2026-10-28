import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

from worker.search import MODEL_NAME, embed, score, search_library


def sample_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    data = b"%PDF-1.4\n"
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(data)
    data += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    for offset in offsets[1:]:
        data += f"{offset:010d} 00000 n \n".encode()
    data += f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return data


class LocalSearchTests(unittest.TestCase):
    def test_embedding_ranks_related_text(self):
        query = embed("vector search")
        self.assertGreater(score(query, embed("vector search local PDF")), score(query, embed("calendar milk reminder")))

    def test_pdf_content_extracted_locally_and_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "notes.pdf").write_bytes(sample_pdf("vector search local PDF"))
            with patch.dict(os.environ, {"DENGVIS_EMBEDDING_CACHE": str(root / "missing-model")}):
                outcome = search_library(root, "vector search")
            self.assertTrue(outcome["success"])
            self.assertEqual(outcome["modelName"], MODEL_NAME)
            self.assertEqual(outcome["excerpts"][0]["source"], "notes.pdf")
            self.assertEqual(outcome["excerpts"][0]["page"], 1)
            self.assertIn("vector search", outcome["excerpts"][0]["text"])
            self.assertNotIn(str(root), str(outcome))


if __name__ == "__main__":
    unittest.main()
