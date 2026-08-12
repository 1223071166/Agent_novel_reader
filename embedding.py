import os
import chromadb
import shutil
from FlagEmbedding import FlagAutoModel,FlagReranker
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch
from config import CHAPTER_DIR, DB_DIR, MODEL_NAME,RERANKER_MODEL_NAME


_model=None
def get_model():
    global _model
    if _model is None:
        _model=FlagAutoModel.from_finetuned(
            MODEL_NAME,
            query_instruction_for_retrieval="为这个句子生成用于检索小说内容的向量：",
            use_fp16=True
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
            name="novel"
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
        max_length=512
    )

    with torch.no_grad():
        scores=reranker_model(**inputs).logits.squeeze(-1)

    return scores.tolist()
def split_text(text,size=500,overlap=100):
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
        batch_size=16
    )


    batch_size=5000

    collection=get_collection()
    for i in range(0,len(ids),batch_size):
        collection.add(
            ids=ids[i:i+batch_size],
            documents=documents[i:i+batch_size],
            embeddings=vectors[i:i+batch_size].tolist(),
            metadatas=metadatas[i:i+batch_size]
        )

    print("embedding完成")


def search(query,n=5,top_k=50):
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

    for item in search("什么雯与魔法少女交流"):
        meta=item["metadata"]
        print(
            f"\nscore={item['score']:.4f} chapter={meta['chapter']} chunk={meta['chunk']} title={meta['title']}\n"
        )
        print(item["text"][:500]+"...")
    