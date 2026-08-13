from openai import OpenAI
import os
from dotenv import load_dotenv
load_dotenv()
CHAPTER_DIR = "chapters"
CHAPTER_LIST = "chapters.txt"
INFO= "info.txt"



CHAPTER_DIR="chapters"
DB_DIR="vector_db"
MODEL_NAME="BAAI/bge-base-zh-v1.5" #使用较大的模型进行向量化（大概需40分钟完成，小模型只需4分钟）
RERANKER_MODEL_NAME="BAAI/bge-reranker-v2-m3" 



MODEL = "deepseek-ai/DeepSeek-V4-Flash"
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url="https://api.siliconflow.cn/v1"
)

client_summary = client
MODEL_summary = MODEL

SUMMARY_DIR="summaries"