import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def load_embedding_module():
    config = types.ModuleType("config")
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

    def test_chapter_range_applies_to_vector_and_lexical_candidates(self):
        collection = FakeCollection()
        vector = SimpleNamespace(tolist=lambda: [0.1, 0.2])
        model = SimpleNamespace(encode_queries=lambda queries: [vector])

        with (
            patch.object(embedding, "get_collection", return_value=collection),
            patch.object(embedding, "get_model", return_value=model),
            patch.object(embedding, "rerank", return_value=[0.9]),
        ):
            book_path = SimpleNamespace(vector_db_dir=Path("vector-range-test"))
            results = embedding.search(
                "问题",
                book_path,
                max_chapter=2,
                min_chapter=2,
            )

        self.assertEqual(collection.query_arguments["where"], {
            "$and": [
                {"chapter": {"$gte": 2}},
                {"chapter": {"$lte": 2}},
            ],
        })
        self.assertEqual(
            [int(item["metadata"]["chapter"]) for item in results],
            [2],
        )

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

    def test_build_embedding_skips_chunks_already_saved(self):
        class BuildCollection:
            def __init__(self):
                self.added_ids = []

            def get(self, **_kwargs):
                return {"ids": ["1_0"]}

            def add(self, *, ids, **_kwargs):
                self.added_ids.extend(ids)

        class Client:
            def __init__(self, collection):
                self.collection = collection

            def get_or_create_collection(self, **_kwargs):
                return self.collection

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            chapter_dir = root / "chapters"
            chapter_dir.mkdir()
            (chapter_dir / "1.txt").write_text("第一章\n正文", encoding="utf-8")
            (chapter_dir / "2.txt").write_text("第二章\n正文", encoding="utf-8")
            collection = BuildCollection()
            encoded_documents = []
            progress = []

            def encode(documents, **_kwargs):
                encoded_documents.extend(documents)
                return SimpleNamespace(tolist=lambda: [[0.1]] * len(documents))

            with (
                patch.object(
                    embedding.chromadb,
                    "PersistentClient",
                    return_value=Client(collection),
                ),
                patch.object(
                    embedding,
                    "get_model",
                    return_value=SimpleNamespace(encode=encode),
                ),
            ):
                embedding.build_embedding(
                    SimpleNamespace(chapter_dir=chapter_dir),
                    root / "vectors",
                    lambda processed, total: progress.append((processed, total)),
                )

        self.assertEqual(collection.added_ids, ["2_0"])
        self.assertEqual(encoded_documents, ["第二章\n正文"])
        self.assertEqual(progress, [(1, 2), (2, 2)])


if __name__ == "__main__":
    unittest.main()
