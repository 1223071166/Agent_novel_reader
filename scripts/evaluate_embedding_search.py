import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import BookPaths
from embedding import search


DEFAULT_QUERIES = [
    "高文从棺材里醒来，遇见自己的后代",
    "瑞贝卡为什么被称为火球术大师",
    "塞西尔领如何用魔导技术发展工业",
    "提丰帝国皇帝是谁，他做了什么",
    "永眠者利用梦境网络做什么",
    "琥珀偷高文东西被抓住",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run repeatable semantic-search probes.")
    parser.add_argument("book_id", help="Book ID under data/books")
    parser.add_argument("query", nargs="*", help="Queries; defaults to a small regression set")
    parser.add_argument("--limit", type=int, default=5, help="Results printed per query")
    parser.add_argument("--top-k", type=int, default=50, help="Vector candidates before reranking")
    args = parser.parse_args()

    book_path = BookPaths(args.book_id)
    queries = args.query or DEFAULT_QUERIES
    for query in queries:
        print(f"\n=== {query} ===", flush=True)
        results = search(
            query,
            book_path,
            max_chapter=None,
            n=args.limit,
            top_k=args.top_k,
        )
        for rank, item in enumerate(results, 1):
            metadata = item["metadata"]
            snippet = item["text"].replace("\n", " ")[:180]
            print(
                f"{rank}. score={item['score']:.4f} "
                f"ranks=v{item.get('vector_rank')}/l{item.get('lexical_rank')}"
                f"/r{item.get('reranker_rank')} "
                f"lex={item.get('lexical_score', 0.0):.3f} "
                f"chapter={metadata['chapter']} chunk={metadata['chunk']} "
                f"title={metadata['title']} :: {snippet}",
                flush=True,
            )


if __name__ == "__main__":
    main()
