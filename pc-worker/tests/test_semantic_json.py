"""Neural similarity scores must be safe to send in Worker JSON results."""

import json

import numpy as np

from worker import search
from test_local_search import sample_pdf


class LocalModel:
    def query_embed(self, _query):
        yield np.array([0.8, 0.6], dtype=np.float32)

    def passage_embed(self, passages, batch_size):
        for _ in passages:
            yield np.array([0.8, 0.6], dtype=np.float32)


def test_semantic_result_serializes_for_worker_http(monkeypatch, tmp_path):
    (tmp_path / "notes.pdf").write_bytes(sample_pdf("vector search local PDF"))
    monkeypatch.setattr(search, "_semantic_model", lambda _cache: LocalModel())
    result = search.search_library(tmp_path, "vector search")
    assert result["modelName"] == search.SEMANTIC_MODEL_NAME
    assert result["excerpts"]
    assert isinstance(result["excerpts"][0]["score"], float)
    json.dumps(result)
