import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def load_embedding_module():
    config = types.ModuleType("config")
    config.BOOK_ID = "book-test"
    config.BookPaths = object
    config.EMBEDDING_BATCH_SIZE = 16
    config.EMBEDDING_PROGRESS_BATCH_SIZE = 128
    config.EMBEDDING_CHUNK_OVERLAP = 100
    config.EMBEDDING_CHUNK_SIZE = 500
    config.EMBEDDING_USE_FP16 = False
    config.MODEL_NAME = "model"
    config.RERANKER_MAX_LENGTH = 512
    config.RERANKER_MODEL_NAME = "reranker"
    config.SEMANTIC_SEARCH_DEFAULT_N = 5
    config.SEMANTIC_SEARCH_TOP_K = 50
    config.VECTOR_COLLECTION_NAME = "novel"

    chromadb = types.ModuleType("chromadb")
    chromadb.PersistentClient = object
    flag_embedding = types.ModuleType("FlagEmbedding")
    flag_embedding.FlagAutoModel = object
    transformers = types.ModuleType("transformers")
    transformers.AutoTokenizer = object
    transformers.AutoModelForSequenceClassification = object
    torch = types.ModuleType("torch")
    torch.no_grad = lambda: None

    spec = importlib.util.spec_from_file_location(
        "embedding_under_test",
        Path(__file__).parents[1] / "embedding.py",
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        "config": config,
        "chromadb": chromadb,
        "FlagEmbedding": flag_embedding,
        "transformers": transformers,
        "torch": torch,
        "embedding_under_test": module,
    }):
        spec.loader.exec_module(module)
    return module


embedding = load_embedding_module()


class FakeCollection:
    def __init__(self):
        self.query_arguments = None

    def count(self):
        return 2

    def query(self, **kwargs):
        self.query_arguments = kwargs
        return {
            "ids": [["1_0", "2_0"]],
            "documents": [["第一段", "第二段"]],
            "metadatas": [[
                {"chapter": 1, "title": "第一章", "chunk": 0},
                {"chapter": 2, "title": "第二章", "chunk": 0},
            ]],
        }

    def get(self, **kwargs):
        return {
            "ids": ["1_0", "2_0"],
            "documents": ["第一段", "第二段"],
            "metadatas": [
                {"chapter": 1, "title": "第一章", "chunk": 0},
                {"chapter": 2, "title": "第二章", "chunk": 0},
            ],
        }


class EmbeddingSearchTests(unittest.TestCase):
    def setUp(self):
        embedding._lexical_corpora.clear()

    def test_spoiler_limit_is_applied_inside_the_vector_query(self):
        collection = FakeCollection()
        vector = SimpleNamespace(tolist=lambda: [0.1, 0.2])
        model = SimpleNamespace(encode_queries=lambda queries: [vector])

        with (
            patch.object(embedding, "get_collection", return_value=collection),
            patch.object(embedding, "get_model", return_value=model),
            patch.object(embedding, "rerank", return_value=[0.9, 0.8]),
        ):
            book_path = SimpleNamespace(vector_db_dir=Path("vector-test"))
            results = embedding.search("问题", book_path, 2)

        self.assertEqual(
            collection.query_arguments["where"],
            {"chapter": {"$lte": 2}},
        )
        self.assertEqual(len(results), 2)

    def test_lexical_score_tolerates_a_small_name_typo(self):
        query = embedding._normalize_search_text("魔法女神米尔米那离开神位")
        relevant = embedding._normalize_search_text("魔法女神弥尔米娜主动离开了神位")
        unrelated = embedding._normalize_search_text("冬日的边境迎来了一场暴风雪")

        self.assertGreater(
            embedding._lexical_score(query, relevant),
            embedding._lexical_score(query, unrelated),
        )

    def test_adjacent_chunks_do_not_fill_the_result_list(self):
        ranked = [
            {"metadata": {"chapter": 10, "chunk": 2}},
            {"metadata": {"chapter": 10, "chunk": 3}},
            {"metadata": {"chapter": 11, "chunk": 0}},
        ]

        selected = embedding._select_diverse_results(ranked, 2)

        self.assertEqual(
            [(item["metadata"]["chapter"], item["metadata"]["chunk"]) for item in selected],
            [(10, 2), (11, 0)],
        )


if __name__ == "__main__":
    unittest.main()
