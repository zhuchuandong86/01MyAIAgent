# modules/rag/config.py
import os
import core.paths
from dotenv import load_dotenv

# 加载全局环境变量
load_dotenv(core.paths.ENV_FILE)

class Config:
    INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")
    INTERNAL_BASE_URL = os.getenv("INTERNAL_API_BASE")
    MODEL_NAME = os.getenv("MODEL_TEXT", "deepseek-v3-0324")
    MODEL_VISION = os.getenv("MODEL_VISION", "deepseek-v3-0324")
    
    # 请确保你在全局的 .env 文件里配了这两个变量，如果没有，会使用这里的默认值
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "bge-m3") 
    RERANK_MODEL = os.getenv("RERANK_MODEL", "bge-reranker-v2-m3")

    # ==========================================
    # 【核心升级】：底层资产路径与全平台打通！
    # ==========================================
    # 向量库放在全局数据库目录下
    DB_DIR = os.path.join(core.paths.GLOBAL_DATA_DIR, "databases", "rag_faiss_bm25")
    PROCESSED_RECORD_FILE = os.path.join(core.paths.GLOBAL_DATA_DIR, "databases", "rag_records.json")
    
    # 🌟 神级复用：直接将 MD 缓存目录指向全局的 md_cache，实现多应用资产互通！
    DEBUG_MD_DIR = os.path.join(core.paths.GLOBAL_DATA_DIR, "md_cache") 

    CHUNK_SIZE = 1000
    CHUNK_OVERLAP = 100
    RETRIEVER_TOP_K = 15
    RERANK_TOP_K = 5