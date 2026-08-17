import os
import chromadb
import shutil
from FlagEmbedding import FlagAutoModel
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch
from config import (
    CHAPTER_DIR,
    DB_DIR,
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_CHUNK_OVERLAP,
    EMBEDDING_CHUNK_SIZE,
    EMBEDDING_USE_FP16,
    MODEL_NAME,
    RERANKER_MAX_LENGTH,
    RERANKER_MODEL_NAME,
    SEMANTIC_SEARCH_DEFAULT_N,
    SEMANTIC_SEARCH_TOP_K,
    VECTOR_COLLECTION_NAME,
    VECTOR_DB_BATCH_SIZE,
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


_collection=None
def get_collection():
    global _collection
    if _collection is None:
        client=chromadb.PersistentClient(
            path=DB_DIR
        )
        _collection=client.get_or_create_collection(
            name=VECTOR_COLLECTION_NAME
        )
    return _collection


def reset_db():
    """删除向量库。必须在任何 chromadb 连接建立之前调用。"""
    global _collection
    if _collection is not None:
        raise RuntimeError(
            "向量库已经被连接，无法安全删除。请在调用 search/build_embedding 之前执行 reset_db。"
        )
    shutil.rmtree(
        DB_DIR,
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

def build_embedding():

    ids=[]
    documents=[]
    metadatas=[]

    for filename in os.listdir(CHAPTER_DIR):

        if not filename.endswith(".txt"):
            continue

        chapter_id=filename[:-4]

        with open(
            os.path.join(CHAPTER_DIR,filename),
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

    vectors=get_model().encode(
        documents,
        batch_size=EMBEDDING_BATCH_SIZE
    )


    collection=get_collection()
    for i in range(0,len(ids),VECTOR_DB_BATCH_SIZE):
        collection.add(
            ids=ids[i:i+VECTOR_DB_BATCH_SIZE],
            documents=documents[i:i+VECTOR_DB_BATCH_SIZE],
            embeddings=vectors[i:i+VECTOR_DB_BATCH_SIZE].tolist(),
            metadatas=metadatas[i:i+VECTOR_DB_BATCH_SIZE]
        )

    print("embedding完成")


def search(query,n=SEMANTIC_SEARCH_DEFAULT_N,top_k=SEMANTIC_SEARCH_TOP_K):
    vector=get_model().encode_queries(
        [query]
    )[0]

    result=get_collection().query(
        query_embeddings=[
            vector.tolist()
        ],
        n_results=top_k
    )

    documents=result["documents"][0]
    metadatas=result["metadatas"][0]

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
    #reset_db()
    #build_embedding()

    for item in search("程斌初次遇见文雯"):
        meta=item["metadata"]
        print(
            f"\nscore={item['score']:.4f} chapter={meta['chapter']} chunk={meta['chunk']} title={meta['title']}\n"
        )
        print(item["text"][:500]+"...")
