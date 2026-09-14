import os
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv
from openai import OpenAI


# Resolve paths from this file so execution does not depend on the current directory.
PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

# Project files and directories.
DATA_DIR = PROJECT_ROOT / "data"
BOOKS_DIR = DATA_DIR / "books"
SELECTED_BOOK_FILE = DATA_DIR / "selected_book.txt"
DATABASE_DIR = DATA_DIR / "database"

BOOK_ID = "shengweizhilv"


@dataclass(frozen=True)
class BookPaths:
    book_id: str
    @property
    def root(self) -> Path:
        return BOOKS_DIR / self.book_id
    @property
    def novel_file(self) -> Path:
        return self.root / "novel.txt"
    @property
    def info_file(self) -> Path:
        return self.root / "info.txt"
    @property
    def chapter_dir(self) -> Path:
        return self.root / "chapters"
    @property
    def chapter_list(self) -> Path:
        return self.root / "chapters.txt"
    @property
    def summary_dir(self) -> Path:
        return self.root / "summaries"
    @property
    def vector_db_dir(self) -> Path:
        return DATABASE_DIR / "vector_db" / self.book_id


DEFAULT_BOOK_PATHS = BookPaths(BOOK_ID)

# Backward-compatible aliases for modules that have not been migrated yet.
BOOK_INFORMATION_DIR = DEFAULT_BOOK_PATHS.root
NOVEL_FILE = DEFAULT_BOOK_PATHS.novel_file
NOVEL_BACKUP_FILE = DEFAULT_BOOK_PATHS.root / "novel.txt.bak"
CHAPTER_DIR = DEFAULT_BOOK_PATHS.chapter_dir
CHAPTER_LIST = DEFAULT_BOOK_PATHS.chapter_list
INFO_FILE = DEFAULT_BOOK_PATHS.info_file
SUMMARY_DIR = DEFAULT_BOOK_PATHS.summary_dir
DB_DIR = DEFAULT_BOOK_PATHS.vector_db_dir

VECTOR_COLLECTION_NAME = "novel"
MESSAGE_STORAGE_FILE = DATABASE_DIR / "conversations.db"
# API configuration.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
API_BASE_URL = "https://api.siliconflow.cn/v1"
MODEL = "deepseek-ai/DeepSeek-V4-Flash"
client = OpenAI(api_key=OPENAI_API_KEY, base_url=API_BASE_URL)
client_summary = client
MODEL_summary = MODEL

# Embedding and retrieval configuration.
MODEL_NAME = "BAAI/bge-base-zh-v1.5"
RERANKER_MODEL_NAME = "BAAI/bge-reranker-v2-m3"
EMBEDDING_CHUNK_SIZE = 500
EMBEDDING_CHUNK_OVERLAP = 100
EMBEDDING_BATCH_SIZE = 16
EMBEDDING_PROGRESS_BATCH_SIZE = 128
RERANKER_MAX_LENGTH = 512
EMBEDDING_USE_FP16 = True
SEMANTIC_SEARCH_DEFAULT_N = 5
SEMANTIC_SEARCH_TOP_K = 50

# Summary generation configuration.
MID_SIZE = 20
MIDS_PER_BIG = 5
BIG_SIZE = MID_SIZE * MIDS_PER_BIG
MAX_WORKERS = 5
CHAPTER_SUMMARY_CHARS = 250
MID_SUMMARY_CHARS = 1000
BIG_SUMMARY_CHARS = 1000
WHOLE_SUMMARY_CHARS = 4000

# Main program switches.
USE_SUMMARY_TOOL = True
SHOW_USAGE = True
