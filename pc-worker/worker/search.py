"""Local PDF extraction and deterministic character-gram embeddings."""

import hashlib
import math
import os
import re
import time
from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader


MODEL_NAME = "hashing-char-3gram-v1"
SEMANTIC_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
VECTOR_SIZE = 512
MAX_FILES = 200
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_PAGES = 500
MAX_OCR_PAGES = 30
MAX_OCR_PIXELS = 6_000_000


def _embedding_cache() -> Path:
    configured = os.environ.get("DENGVIS_EMBEDDING_CACHE", "").strip()
    return Path(configured).expanduser() if configured else Path(__file__).resolve().parents[2] / ".runtime" / "embedding"


@lru_cache(maxsize=2)
def _semantic_model(cache_dir: str):
    from fastembed import TextEmbedding

    return TextEmbedding(SEMANTIC_MODEL_NAME, cache_dir=cache_dir,
                         local_files_only=True, threads=2)


def prepare_embedding() -> Path:
    """Explicit setup step; normal searches are restricted to local model files."""
    from fastembed import TextEmbedding

    cache_dir = _embedding_cache().resolve()
    model = TextEmbedding(SEMANTIC_MODEL_NAME, cache_dir=str(cache_dir), threads=2)
    next(model.query_embed("本地模型准备"))
    _semantic_model.cache_clear()
    return cache_dir


@lru_cache(maxsize=1)
def _ocr_engine():
    from rapidocr import RapidOCR

    return RapidOCR()


def _ocr_page(path: Path, index: int) -> str:
    import numpy as np
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(path))
    try:
        page = document[index]
        width, height = page.get_size()
        scale = min(2.0, math.sqrt(MAX_OCR_PIXELS / (width * height)))
        bitmap = page.render(scale=scale)
        try:
            result = _ocr_engine()(np.asarray(bitmap.to_pil().convert("RGB")))
            return re.sub(r"\s+", " ", " ".join(result.txts or ())).strip()
        finally:
            bitmap.close()
            page.close()
    finally:
        document.close()


def embed(text: str) -> list[float]:
    normalized = re.sub(r"\s+", " ", text.lower()).strip()
    vector = [0.0] * VECTOR_SIZE
    if not normalized:
        return vector
    grams = [normalized[i:i + 3] for i in range(max(1, len(normalized) - 2))]
    for gram in grams:
        digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=4).digest()
        bucket = int.from_bytes(digest, "big") % VECTOR_SIZE
        vector[bucket] += 1.0
    magnitude = math.sqrt(sum(value * value for value in vector))
    return [value / magnitude for value in vector]


def score(left: list[float], right: list[float]) -> float:
    return max(0.0, min(1.0, sum(a * b for a, b in zip(left, right))))


def search_library(root: Path, query: str, max_results: int = 3) -> dict:
    start = time.monotonic()
    root = root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("指定的本地资料目录不存在。")
    query_vector = embed(query)
    if not any(query_vector):
        raise ValueError("查询内容不能为空。")
    files = sorted(path for path in root.rglob("*.pdf") if path.is_file() and not path.is_symlink())[:MAX_FILES]
    if not files:
        raise ValueError("指定目录中没有 PDF 文件。")
    ranked: list[dict] = []
    pages_seen = 0
    readable_pages = 0
    ocr_pages = 0
    ocr_used = False
    ocr_error = False
    for path in files:
        if root not in path.resolve().parents or path.stat().st_size > MAX_FILE_BYTES:
            continue
        try:
            reader = PdfReader(str(path), strict=False)
            for index, page in enumerate(reader.pages):
                if pages_seen >= MAX_PAGES:
                    break
                pages_seen += 1
                page_text = re.sub(r"\s+", " ", page.extract_text() or "").strip()
                if not page_text and ocr_pages < MAX_OCR_PAGES:
                    ocr_pages += 1
                    try:
                        page_text = _ocr_page(path, index)
                        ocr_used = ocr_used or bool(page_text)
                    except Exception:
                        ocr_error = True
                if not page_text:
                    continue
                readable_pages += 1
                for offset in range(0, len(page_text), 600):
                    snippet = page_text[offset:offset + 600]
                    similarity = score(query_vector, embed(snippet))
                    ranked.append({"source": path.name[:255], "page": index + 1,
                                   "text": snippet[:500], "score": round(similarity, 4)})
        except Exception:
            continue
        if pages_seen >= MAX_PAGES:
            break
    if readable_pages == 0:
        if ocr_error:
            raise ValueError("扫描件 OCR 未能运行；请检查 PC Worker 的 OCR 依赖与文件。")
        raise ValueError("PDF 中没有可提取的文字；扫描件需要先做 OCR。")
    model_name = MODEL_NAME
    try:
        model = _semantic_model(str(_embedding_cache().resolve()))
        query_embedding = next(model.query_embed(query))
        for item, passage_embedding in zip(ranked, model.passage_embed(
                (item["text"] for item in ranked), batch_size=32)):
            item["score"] = round(float(score(query_embedding, passage_embedding)), 4)
        model_name = SEMANTIC_MODEL_NAME
    except Exception:
        # Keep the local deterministic search available when the optional model is absent.
        pass
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return {"success": True, "modelName": model_name + ("+rapidocr" if ocr_used else ""),
            "elapsedMs": min(600_000, int((time.monotonic() - start) * 1000)),
            "excerpts": [item for item in ranked[:max_results] if item["score"] > 0]}
