import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


# Resolve paths from this file so execution does not depend on the current directory.
PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

# Project files and directories.
NOVEL_FILE = PROJECT_ROOT / "novel.txt"
NOVEL_BACKUP_FILE = PROJECT_ROOT / "novel.txt.bak"
CHAPTER_DIR = PROJECT_ROOT / "chapters"
CHAPTER_LIST = PROJECT_ROOT / "chapters.txt"
INFO_FILE = PROJECT_ROOT / "info.txt"
SUMMARY_DIR = PROJECT_ROOT / "summaries"
DB_DIR = PROJECT_ROOT / "vector_db"
VECTOR_COLLECTION_NAME = "novel"

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
VECTOR_DB_BATCH_SIZE = 5000
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
