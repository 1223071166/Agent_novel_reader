import os
import chromadb
import re
import shutil
import unicodedata
from collections.abc import Callable
from pathlib import Path
from FlagEmbedding import FlagAutoModel
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch
from config import (
    BookPaths,
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_PROGRESS_BATCH_SIZE,
    EMBEDDING_CHUNK_OVERLAP,
    EMBEDDING_CHUNK_SIZE,
    EMBEDDING_USE_FP16,
    MODEL_NAME,
    RERANKER_MAX_LENGTH,
    RERANKER_MODEL_NAME,
    SEMANTIC_SEARCH_DEFAULT_N,
    SEMANTIC_SEARCH_TOP_K,
    VECTOR_COLLECTION_NAME,
)


_model=None
def get_model():
    global _model
    if _model is None:
        _model=FlagAutoModel.from_finetuned(
            MODEL_NAME,
            query_instruction_for_retrieval="为这个句子生成用于检索小说内容的向量：",
            use_fp16=EMBEDDING_USE_FP16
        )
    return _model


_reranker_tokenizer=None
_reranker_model=None
def get_reranker():
    global _reranker_tokenizer, _reranker_model
    if _reranker_model is None:
        _reranker_tokenizer=AutoTokenizer.from_pretrained(
            RERANKER_MODEL_NAME
        )
        _reranker_model=AutoModelForSequenceClassification.from_pretrained(
            RERANKER_MODEL_NAME
        )
        _reranker_model.eval()
    return _reranker_tokenizer, _reranker_model


_collections={}
_lexical_corpora={}
def get_collection(book_path: BookPaths):
    """获取指定小说的向量集合。"""
    db_dir = book_path.vector_db_dir

    db_key = str(db_dir.resolve())
    if db_key not in _collections:
        client=chromadb.PersistentClient(path=db_dir)
        _collections[db_key]=client.get_or_create_collection(
            name=VECTOR_COLLECTION_NAME
        )
    return _collections[db_key]


def reset_db(book_path: BookPaths):
    """删除指定小说的向量库，必须在连接建立之前调用。"""
    db_key = str(book_path.vector_db_dir.resolve())
    if db_key in _collections:
        raise RuntimeError(
            "向量库已经被连接，无法安全删除。请在调用 search/build_embedding 之前执行 reset_db。"
        )
    shutil.rmtree(
        book_path.vector_db_dir,
        ignore_errors=True
    )
    _lexical_corpora.pop(db_key, None)


def rerank(query, documents):
    reranker_tokenizer, reranker_model = get_reranker()
    pairs=[
        [query, doc]
        for doc in documents
    ]

    inputs=reranker_tokenizer(
        pairs,
        padding=True,
        truncation=True,
        return_tensors="pt",
        max_length=RERANKER_MAX_LENGTH
    )

    with torch.no_grad():
        scores=reranker_model(**inputs).logits.squeeze(-1)

    return scores.tolist()


def _normalize_search_text(text: str) -> str:
    """Normalize punctuation/spacing while retaining Chinese and word characters."""
    normalized = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", normalized)


def _ngram_coverage(query: str, document: str, size: int) -> float:
    if len(query) < size:
        return 0.0
    grams = {query[index:index + size] for index in range(len(query) - size + 1)}
    if not grams:
        return 0.0
    return sum(gram in document for gram in grams) / len(grams)


def _lexical_score(query: str, document: str) -> float:
    """Character n-gram recall complements embeddings for names and small typos."""
    if not query or not document:
        return 0.0
    score = (
        0.15 * _ngram_coverage(query, document, 1)
        + 0.35 * _ngram_coverage(query, document, 2)
        + 0.50 * _ngram_coverage(query, document, 3)
    )
    if query in document:
        score += 0.5
    return score


def _get_lexical_corpus(collection, book_path: BookPaths):
    db_key = str(book_path.vector_db_dir.resolve())
    if db_key not in _lexical_corpora:
        data = collection.get(include=["documents", "metadatas"])
        documents = data.get("documents") or []
        metadatas = data.get("metadatas") or []
        ids = data.get("ids") or [str(index) for index in range(len(documents))]
        _lexical_corpora[db_key] = [
            {
                "id": item_id,
                "document": document,
                "metadata": metadata,
                "normalized": _normalize_search_text(
                    f"{metadata.get('title', '')}\n{document}"
                ),
            }
            for item_id, document, metadata in zip(ids, documents, metadatas)
        ]
    return _lexical_corpora[db_key]


def _select_diverse_results(ranked, n: int):
    """Avoid spending the result list on adjacent chunks from one chapter."""
    selected = []
    deferred = []
    chunks_by_chapter = {}
    for item in ranked:
        metadata = item["metadata"]
        chapter = int(metadata["chapter"])
        chunk = int(metadata["chunk"])
        existing = chunks_by_chapter.get(chapter, [])
        if len(existing) >= 2 or any(abs(chunk - other) <= 1 for other in existing):
            deferred.append(item)
            continue
        selected.append(item)
        chunks_by_chapter.setdefault(chapter, []).append(chunk)
        if len(selected) == n:
            return selected

    for item in deferred:
        selected.append(item)
        if len(selected) == n:
            break
    return selected


def split_text(text,size=EMBEDDING_CHUNK_SIZE,overlap=EMBEDDING_CHUNK_OVERLAP):
    step=size-overlap
    return [
        text[i:i+size]
        for i in range(0,len(text),step)
    ]

def build_embedding(
    book_path: BookPaths,
    output_dir: Path,
    on_progress: Callable[[int, int], None] | None = None,
):
    chapter_dir = book_path.chapter_dir

    ids=[]
    documents=[]
    metadatas=[]

    for filename in os.listdir(chapter_dir):

        if not filename.endswith(".txt"):
            continue

        chapter_id=filename[:-4]

        with open(
            os.path.join(chapter_dir,filename),
            encoding="utf-8"
        ) as f:
            text=f.read()
            title=text.splitlines()[0].strip()


        chunks=split_text(text)


        for i,chunk in enumerate(chunks):

            ids.append(
                f"{chapter_id}_{i}"
            )

            documents.append(chunk)

            metadatas.append({
                "chapter":int(chapter_id),
                "title":title,
                "chunk":i
            })


    print(f"共{len(documents)}个文本块")

    if not documents:
        raise ValueError("没有可用于向量化的章节正文")

    output_dir.mkdir(parents=True, exist_ok=True)
    vector_client = chromadb.PersistentClient(path=output_dir)
    try:
        collection = vector_client.get_or_create_collection(name=VECTOR_COLLECTION_NAME)
        model = get_model()
        total = len(documents)

        for i in range(0, total, EMBEDDING_PROGRESS_BATCH_SIZE):
            end = min(i + EMBEDDING_PROGRESS_BATCH_SIZE, total)
            vectors = model.encode(
                documents[i:end],
                batch_size=EMBEDDING_BATCH_SIZE,
            )
            collection.add(
                ids=ids[i:end],
                documents=documents[i:end],
                embeddings=vectors.tolist(),
                metadatas=metadatas[i:end],
            )
            if on_progress is not None:
                on_progress(end, total)
    finally:
        vector_client.close()

    print("embedding完成")


def search(
    query,
    book_path: BookPaths,
    max_chapter: int | None,
    n=SEMANTIC_SEARCH_DEFAULT_N,
    top_k=SEMANTIC_SEARCH_TOP_K,
):
    collection = get_collection(book_path)
    collection_count = collection.count()
    if collection_count == 0 or n <= 0 or not query.strip():
        return []

    vector=get_model().encode_queries(
        [query]
    )[0]

    query_arguments = {
        "query_embeddings": [vector.tolist()],
        "n_results": min(top_k, collection_count),
    }
    if max_chapter is not None:
        query_arguments["where"] = {"chapter": {"$lte": max_chapter}}
    result=collection.query(**query_arguments)

    documents=(result.get("documents") or [[]])[0]
    metadatas=(result.get("metadatas") or [[]])[0]
    raw_result_ids = (result.get("ids") or [[]])[0]
    result_ids = raw_result_ids or [
        f"{metadata.get('chapter', 'unknown')}_{metadata.get('chunk', index)}"
        for index, metadata in enumerate(metadatas)
    ]
    if not documents or not metadatas:
        return []

    candidates = {}
    vector_ranks = {}
    for rank, (item_id, document, metadata) in enumerate(
        zip(result_ids, documents, metadatas),
        1,
    ):
        candidates[item_id] = {
            "id": item_id,
            "document": document,
            "metadata": metadata,
        }
        vector_ranks[item_id] = rank

    normalized_query = _normalize_search_text(query)
    lexical_scored = []
    for item in _get_lexical_corpus(collection, book_path):
        chapter = int(item["metadata"]["chapter"])
        if max_chapter is not None and chapter > max_chapter:
            continue
        lexical_scored.append((_lexical_score(normalized_query, item["normalized"]), item))
    lexical_scored = [pair for pair in lexical_scored if pair[0] > 0]
    lexical_scored.sort(key=lambda pair: pair[0], reverse=True)
    lexical_limit = min(max(n * 4, top_k // 2), len(lexical_scored))
    lexical_ranks = {}
    lexical_scores = {}
    for rank, (score, item) in enumerate(lexical_scored[:lexical_limit], 1):
        candidates.setdefault(item["id"], item)
        lexical_ranks[item["id"]] = rank
        lexical_scores[item["id"]] = score

    # Keep cross-encoder work bounded while retaining candidates from both recall paths.
    pre_ranked = sorted(
        candidates.values(),
        key=lambda item: (
            0.55 / (10 + vector_ranks.get(item["id"], top_k + 10))
            + 0.45 / (10 + lexical_ranks.get(item["id"], lexical_limit + 10))
        ),
        reverse=True,
    )[:max(top_k, n * 5)]

    reranker_documents = [
        f"{item['metadata'].get('title', '')}\n{item['document']}"
        for item in pre_ranked
    ]
    reranker_scores = rerank(query, reranker_documents)
    reranker_order = sorted(
        range(len(pre_ranked)),
        key=lambda index: reranker_scores[index],
        reverse=True,
    )
    reranker_ranks = {
        pre_ranked[index]["id"]: rank
        for rank, index in enumerate(reranker_order, 1)
    }
    reranker_scores_by_id = {
        item["id"]: float(score)
        for item, score in zip(pre_ranked, reranker_scores)
    }

    ranked = []
    for item in pre_ranked:
        item_id = item["id"]
        vector_rank = vector_ranks.get(item_id, top_k + 10)
        lexical_rank = lexical_ranks.get(item_id, lexical_limit + 10)
        reranker_rank = reranker_ranks[item_id]
        hybrid_score = 11 * (
            0.45 / (10 + reranker_rank)
            + 0.30 / (10 + vector_rank)
            + 0.25 / (10 + lexical_rank)
        )
        ranked.append({
            "score": hybrid_score,
            "reranker_score": reranker_scores_by_id[item_id],
            "lexical_score": lexical_scores.get(item_id, 0.0),
            "vector_rank": vector_rank if item_id in vector_ranks else None,
            "lexical_rank": lexical_rank if item_id in lexical_ranks else None,
            "reranker_rank": reranker_rank,
            "text": item["document"],
            "metadata": item["metadata"],
        })

    ranked.sort(key=lambda item: item["score"], reverse=True)
    return _select_diverse_results(ranked, n)
