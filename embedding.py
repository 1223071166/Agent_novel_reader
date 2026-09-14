import os
import chromadb
import shutil
from collections.abc import Callable
from pathlib import Path
from FlagEmbedding import FlagAutoModel
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch
from config import (
    BOOK_ID,
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


def search(query,book_path: BookPaths,n=SEMANTIC_SEARCH_DEFAULT_N,top_k=SEMANTIC_SEARCH_TOP_K):
    collection = get_collection(book_path)
    if collection.count() == 0:
        return []

    vector=get_model().encode_queries(
        [query]
    )[0]

    result=collection.query(
        query_embeddings=[
            vector.tolist()
        ],
        n_results=top_k
    )

    documents=(result.get("documents") or [[]])[0]
    metadatas=(result.get("metadatas") or [[]])[0]
    if not documents or not metadatas:
        return []

    scores=rerank(query, documents)

    ranked=sorted(
        zip(scores,documents,metadatas),
        key=lambda x:x[0],
        reverse=True
    )

    return [
        {
            "score":score,
            "text":text,
            "metadata":meta
        }
        for score,text,meta in ranked[:n]
    ]


if __name__=="__main__":
    #第一次运行取消注释
    #reset_db(BookPaths(BOOK_ID))
    #build_embedding(BookPaths(BOOK_ID), BookPaths(BOOK_ID).vector_db_dir)

    for item in search("程斌初次遇见文雯", BookPaths(BOOK_ID)):
        meta=item["metadata"]
        print(
            f"\nscore={item['score']:.4f} chapter={meta['chapter']} chunk={meta['chunk']} title={meta['title']}\n"
        )
        print(item["text"][:500]+"...")
