from __future__ import annotations

import logging
import re
from functools import lru_cache

import jieba
from rank_bm25 import BM25Okapi

from backend.store import Store

jieba.setLogLevel(logging.ERROR)


@lru_cache(maxsize=4096)
def tokenize(text: str):
    return tuple(t.lower() for t in jieba.cut(text) if re.search(r"[\w\u4e00-\u9fff]", t))


def snapshot(store: Store, project_id: str, version: int):
    result = store.get("corpora", f"{project_id}_v{version}")
    if not result:
        raise ValueError("STALE_CORPUS: 资料版本不存在或尚未完成分析")
    return result


def search_corpus(store: Store, project_id: str, version: int, queries: list[dict], top_k: int = 5):
    corpus = snapshot(store, project_id, version)
    if not 1 <= len(queries) <= 100 or not 1 <= top_k <= 10:
        raise ValueError("INVALID_ARGUMENT: 批量查询最多 100 项，top_k 为 1–10")
    chunks = [store.get("chunks", ident) for ident in corpus["chunk_ids"]]
    chunks = [c for c in chunks if c]
    tokenized = [tokenize(c["text"]) for c in chunks]
    ranker = BM25Okapi(tokenized) if tokenized else None
    result = []
    for index, item in enumerate(queries):
        query = str(item.get("query", "")).strip()
        if not query or len(query) > 500:
            raise ValueError("INVALID_ARGUMENT: 查询须为 1–500 字")
        tokens = tokenize(query)
        scores = ranker.get_scores(tokens) if ranker else []
        ranked = []
        for i, chunk in enumerate(chunks):
            overlap = set(tokens) & set(tokenized[i])
            if not overlap:
                continue
            score = float(scores[i]) + len(overlap) * 2
            if query.lower() in chunk["text"].lower():
                score += 10
            ranked.append((score, chunk))
        matches = []
        for score, chunk in sorted(ranked, key=lambda p: p[0], reverse=True)[:top_k]:
            matches.append({"chunk_id": chunk["id"], "knowledge_point_id": item.get("knowledge_point_id"), "document_id": chunk["document_id"], "document_name": chunk["document_name"], "locator": chunk["locator"], "snippet": chunk["text"][:240], "snippet_source_ids": [seg["source_id"] for seg in chunk["segments"][:2]], "score": score})
        result.append({"query_id": str(item.get("query_id", f"q{index}")), "status": "ok" if matches else "empty", "matches": matches})
    return {"corpus_version": version, "results": result}


def chunk_context(store: Store, project_id: str, version: int, ids: list[str]):
    corpus = snapshot(store, project_id, version)
    if not 1 <= len(ids) <= 100:
        raise ValueError("INVALID_ARGUMENT: 每批 1–100 个原文 ID")
    allowed = set(corpus["chunk_ids"])
    results = []
    for ident in ids:
        chunk = store.get("chunks", ident) if ident in allowed else None
        if not chunk:
            results.append({"id": ident, "status": "error", "error_code": "CHUNK_NOT_FOUND"})
        else:
            results.append({**chunk, "status": "ok", "corpus_version": version})
    return {"corpus_version": version, "results": results}

